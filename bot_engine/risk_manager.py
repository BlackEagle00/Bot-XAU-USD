"""
Gestión de Riesgo — XAU/USD Scalping Bot

Responsabilidades:
  • Lote dinámico: capital = min(balance, equity) y distancia real del SL
  • Calcular precios de Stop Loss y Take Profit en precio absoluto
  • Verificar límite de pérdida diaria (realizados + no realizados)
  • Validar todas las condiciones antes de abrir una operación

Fórmula de lote para XAUUSD (cuenta USD):
  lot = (balance × riesgo%) / (SL_ticks × tick_value_por_lote)

  Ejemplo: balance=$10,000 · riesgo=1% · ATR=$1.50
    → Monto a arriesgar = $100
    → SL = 1.5 × $1.50 = $2.25 → 225 ticks (a $0.01/tick)
    → Valor del SL por lote = 225 × $1.00 = $225
    → Lote = $100 / $225 = 0.44 lotes
"""
import math
import MetaTrader5 as mt5
from datetime import timedelta
from typing import Tuple

from .logger_config import logger
from config import (
    SYMBOL, MAGIC_NUMBER,
    RISK_PER_TRADE, MAX_OPEN_TRADES, MAX_DAILY_LOSS_PCT,
    SL_ATR_MULT, TP_ATR_MULT, MIN_LOT, MAX_LOT, MIN_RR
)
import config as _cfg
from .data_handler import get_open_positions, get_account_info, server_now
from .telegram_notifier import notify

_halt_day = None    # día (hora servidor) en que se tocó el límite diario → bloquea hasta el siguiente
_alerted = set()    # (día, alcance, umbral) ya avisados con DAILY_LOSS_ALERT_ONLY
_peak = 0.0         # equity máxima vista por este proceso (corte total MAX_DD_PCT)
_dd_stopped = False # el corte total no se suelta solo: hay que reiniciar el bot

# Niveles por capital: (capital mínimo, nombre, máx. operaciones abiertas, pérdida diaria máx.).
# None = usar el valor del config. Un config puede definir su propio CAPITAL_TIERS.
DEFAULT_CAPITAL_TIERS = (
    (0,    "Micro",    1,    0.05),
    (500,  "Pequeño",  2,    0.07),
    (2000, "Estándar", None, None),
)
MAX_SPREAD_SL_FRAC = 0.25   # el spread no puede costar más del 25% de la distancia al SL
MAX_RISK_MIN_LOT   = 0.05   # cuentas pequeñas: el lote mínimo se permite hasta 5% de riesgo
ACCOUNT_MAX_DAILY_LOSS_PCT = 0.10   # corte diario de TODA la cuenta (todos los bots y el panel juntos)
ENFORCE_CAPITAL_LEVEL = True       # False: el nivel de cuenta y el tope del lote mínimo solo informan, no bloquean


def _enforce() -> bool:
    return getattr(_cfg, "ENFORCE_CAPITAL_LEVEL", ENFORCE_CAPITAL_LEVEL)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPORTAMIENTO SEGÚN EL CAPITAL
# ═══════════════════════════════════════════════════════════════════════════════

def capital_tier(capital: float) -> dict:
    """
    Nivel de la cuenta según su capital: cuentas pequeñas abren menos operaciones a la vez
    y cortan antes el día. El riesgo por operación (RISK_PER_TRADE) es el mismo en todos.
    """
    tiers = sorted(getattr(_cfg, "CAPITAL_TIERS", DEFAULT_CAPITAL_TIERS))
    floor, name, max_open, daily = next((t for t in reversed(tiers) if capital >= t[0]), tiers[0])
    if not _enforce():                                     # nivel informativo: mandan los valores del config
        max_open = daily = None
    return {
        "name": name, "min_capital": floor,
        "max_open": min(MAX_OPEN_TRADES, max_open) if max_open else MAX_OPEN_TRADES,
        "daily_loss": min(MAX_DAILY_LOSS_PCT, daily) if daily else MAX_DAILY_LOSS_PCT,
    }


def spread_ok(spread: float, sl_distance: float) -> bool:
    """El spread es un costo fijo por operación: con stops cortos se come la ventaja."""
    frac = getattr(_cfg, "MAX_SPREAD_SL_FRAC", MAX_SPREAD_SL_FRAC)
    return sl_distance > 0 and spread <= sl_distance * frac


# ═══════════════════════════════════════════════════════════════════════════════
# TAMAÑO DE LOTE
# ═══════════════════════════════════════════════════════════════════════════════

def _tick_value(symbol_info) -> float:
    """
    USD que gana/pierde 1 lote por cada tick, según el cálculo real de MT5.
    trade_tick_value no siempre es fiable: en MetaQuotes-Demo el oro (calc_mode
    CFD-leverage) declara 0.1 y paga 1.0 por tick → el lote arriesgaba 10× el riesgo.
    """
    name = getattr(symbol_info, "name", None)
    px   = getattr(symbol_info, "bid", 0) or getattr(symbol_info, "ask", 0)
    if name and px:
        real = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, name, 1.0, px, px + symbol_info.trade_tick_size)
        if real:
            return abs(real)
    return symbol_info.trade_tick_value


def lot_plan(account, symbol_info, sl_distance: float) -> Tuple[float, float]:
    """
    Lote dinámico: arriesga como MÁXIMO RISK_PER_TRADE % del capital, y dice cuánto
    capital hace falta para el siguiente escalón de lote. No registra nada (se llama cada ciclo).

    Capital = min(balance, equity): con posiciones en pérdida el lote baja; al crecer
    el balance, sube solo. sl_distance es la distancia REAL entrada→SL.

    Returns:
        (lote redondeado HACIA ABAJO al volume_step, o 0.0 si ni el mínimo cabe;
         capital necesario para el siguiente lote, o None si ya está en el máximo
         o los datos del símbolo son inválidos)
    """
    tick_size  = symbol_info.trade_tick_size   # Mínimo movimiento de precio
    tick_value = _tick_value(symbol_info)      # USD por lote por tick (real)
    if tick_size <= 0 or tick_value <= 0 or sl_distance <= 0:
        return 0.0, None

    capital          = min(account.balance, account.equity)
    sl_value_per_lot = sl_distance / tick_size * tick_value
    max_lot          = min(MAX_LOT, symbol_info.volume_max)
    lot = min(capital * RISK_PER_TRADE / sl_value_per_lot, max_lot)

    # Hacia abajo al volume_step: redondear hacia arriba arriesgaría de más
    step = symbol_info.volume_step
    if step > 0:
        lot = math.floor(lot / step + 1e-9) * step

    min_lot = max(MIN_LOT, symbol_info.volume_min)
    if lot < min_lot:
        # Cuenta pequeña: se permite el lote mínimo aunque arriesgue más que RISK_PER_TRADE,
        # siempre que no pase de MAX_RISK_MIN_LOT. need = capital con el que vuelve a caber en el 1%.
        cap = getattr(_cfg, "MAX_RISK_MIN_LOT", MAX_RISK_MIN_LOT)
        min_risk = min_lot * sl_value_per_lot
        if capital > 0 and min_lot <= max_lot + 1e-9 and (min_risk <= capital * cap or not _enforce()):
            return round(min_lot, 8), min_risk / RISK_PER_TRADE
        return 0.0, min_risk / cap                         # capital mínimo para operar este activo
    lot, next_lot = round(lot, 8), (lot + step if step > 0 else None)

    if next_lot is None or next_lot > max_lot + 1e-9:
        return lot, None
    return lot, next_lot * sl_value_per_lot / RISK_PER_TRADE


def micro_sl_distance(capital: float, symbol_info, atr: float):
    """
    Cuenta pequeña (MICRO_SL_FIT=True): distancia de SL con la que el lote mínimo arriesga justo
    MAX_RISK_MIN_LOT del capital. None si está apagado o si quedaría por debajo de MICRO_MIN_SL_ATR×ATR
    (un stop más corto que eso es ruido puro y no se opera).
    """
    if not getattr(_cfg, "MICRO_SL_FIT", False) or capital <= 0 or atr <= 0 or symbol_info.trade_tick_size <= 0:
        return None
    cap = getattr(_cfg, "MAX_RISK_MIN_LOT", MAX_RISK_MIN_LOT)
    per_price = _tick_value(symbol_info) / symbol_info.trade_tick_size     # USD por 1.0 de precio y lote
    min_lot = max(MIN_LOT, symbol_info.volume_min)
    dist = capital * cap / (min_lot * per_price) * 0.995                    # margen por el redondeo del precio
    min_stop = symbol_info.trade_stops_level * symbol_info.point
    if dist < getattr(_cfg, "MICRO_MIN_SL_ATR", 0.5) * atr or dist <= min_stop:
        return None
    return dist


def fit_sl_to_capital(action: str, exec_price: float, sl: float, tp: float, account, symbol_info, atr: float):
    """
    Si el lote mínimo no cabe con el SL por ATR, acerca SL y TP (mismo R:R) hasta que quepa en
    MAX_RISK_MIN_LOT. Devuelve (sl, tp) nuevos o None (no hace falta o no se puede).
    """
    dist = micro_sl_distance(min(account.balance, account.equity), symbol_info, atr)
    risk = abs(exec_price - sl)
    if dist is None or risk <= 0 or dist >= risk:
        return None
    d, rr = (1 if action == "BUY" else -1), abs(tp - exec_price) / risk
    return round(exec_price - d * dist, symbol_info.digits), round(exec_price + d * dist * rr, symbol_info.digits)


def lot_risk_pct(account, symbol_info, sl_distance: float, lot: float) -> float:
    """Fracción del capital que pierde `lot` si salta el SL (0.012 = 1.2%)."""
    capital = min(account.balance, account.equity)
    if capital <= 0 or symbol_info.trade_tick_size <= 0:
        return 0.0
    return lot * sl_distance / symbol_info.trade_tick_size * _tick_value(symbol_info) / capital


def over_min_lot_cap(account, symbol_info, sl_distance: float) -> bool:
    """
    El lote de lot_plan no cabe (0) o, con ENFORCE_CAPITAL_LEVEL=False, el lote mínimo arriesga más que
    MAX_RISK_MIN_LOT: es cuando MICRO_SL_FIT acerca el SL. Si no se puede, sigue con el SL normal.
    """
    lot = lot_plan(account, symbol_info, sl_distance)[0]
    return lot <= 0 or lot_risk_pct(account, symbol_info, sl_distance, lot) > getattr(_cfg, "MAX_RISK_MIN_LOT", MAX_RISK_MIN_LOT)


def calculate_lot(account, symbol_info, sl_distance: float) -> float:
    """Lote para el trade (ver lot_plan). 0.0 → no operar, con el motivo en el log."""
    lot, need = lot_plan(account, symbol_info, sl_distance)
    if lot <= 0:
        if need is None:
            logger.warning("tick_size/tick_value/distancia SL inválidos. Trade omitido.")
        else:
            cap = getattr(_cfg, "MAX_RISK_MIN_LOT", MAX_RISK_MIN_LOT)
            logger.warning(
                f"El lote mínimo arriesgaría más del {cap*100:.0f}% con SL de {sl_distance:.2f}: "
                f"necesita capital ≥ {need:,.2f}. Trade omitido."
            )
    else:
        risk = lot_risk_pct(account, symbol_info, sl_distance, lot)
        if risk > RISK_PER_TRADE + 1e-9:
            logger.warning(f"⚠ Riesgo elevado: el lote mínimo {lot} arriesga {risk*100:.1f}% "
                           f"(con capital ≥ {need:,.2f} vuelve al {RISK_PER_TRADE*100:.0f}%).")
    return lot


# ═══════════════════════════════════════════════════════════════════════════════
# STOP LOSS Y TAKE PROFIT
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_sl_tp(action: str, exec_price: float, atr: float, symbol_info,
                    sl_mult: float = None, tp_mult: float = None) -> Tuple[float, float]:
    """
    Calcula SL y TP en precio absoluto desde el precio de ejecución real.

    Args:
        action:     "BUY" o "SELL"
        exec_price: Precio real de ejecución (ask para BUY, bid para SELL)
        atr:        ATR actual en precio (USD para XAUUSD)
        symbol_info: Información del símbolo (para dígitos y stops_level)
        sl_mult/tp_mult: múltiplos de ATR (None → SL_ATR_MULT/TP_ATR_MULT del config;
                     el filtro predictivo usa los suyos)

    Returns:
        (stop_loss_price, take_profit_price)
    """
    sl_dist  = atr * (sl_mult or SL_ATR_MULT)
    tp_dist  = atr * (tp_mult or TP_ATR_MULT)
    digits   = symbol_info.digits
    buf      = symbol_info.point * 10  # Margen extra sobre el mínimo exigido

    # Distancia mínima broker (algunos brokers exigen SL/TP alejados X puntos)
    min_dist = symbol_info.trade_stops_level * symbol_info.point

    if action == "BUY":
        sl = round(exec_price - sl_dist, digits)
        tp = round(exec_price + tp_dist, digits)
        if min_dist > 0:
            sl = min(sl, round(exec_price - min_dist - buf, digits))
            tp = max(tp, round(exec_price + min_dist + buf, digits))
    else:  # SELL
        sl = round(exec_price + sl_dist, digits)
        tp = round(exec_price - tp_dist, digits)
        if min_dist > 0:
            sl = max(sl, round(exec_price + min_dist + buf, digits))
            tp = min(tp, round(exec_price - min_dist - buf, digits))

    return sl, tp


def check_risk_reward(exec_price: float, sl: float, tp: float, min_rr: float = None) -> Tuple[bool, float]:
    """
    Verifica que el ratio Riesgo:Beneficio REAL cumpla MIN_RR.

    Aunque SL_ATR_MULT/TP_ATR_MULT fijan un R:R teórico, la distancia mínima
    que exige el broker (trade_stops_level) puede deformar el SL/TP final y
    degradar ese ratio. Este guard descarta el trade si el R:R real < MIN_RR.

    Returns:
        (cumple, rr_real)
    """
    risk   = abs(exec_price - sl)
    reward = abs(tp - exec_price)
    if risk <= 0:
        return False, 0.0
    rr = reward / risk
    return rr >= (MIN_RR if min_rr is None else min_rr), rr


# ═══════════════════════════════════════════════════════════════════════════════
# P&L DIARIO
# ═══════════════════════════════════════════════════════════════════════════════

def get_realized_pnl_today() -> float:
    """
    Retorna la ganancia/pérdida realizada del día actual.
    Incluye profit, swap y comisión de los deals de cierre.
    """
    try:
        now = server_now()      # el "día" es el del servidor, no el de tu PC
        if now is None:
            return 0.0
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(day_start, now + timedelta(minutes=1))
        if deals is None:
            return 0.0
        return sum(
            d.profit + d.swap + d.commission
            for d in deals
            if d.magic == MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_OUT
        )
    except Exception as exc:
        logger.error(f"Error obteniendo P&L diario: {exc}")
        return 0.0


def get_account_daily_pnl() -> float:
    """P&L de hoy de TODA la cuenta: cierres de cualquier número mágico (también manuales) + flotante."""
    try:
        now = server_now()
        if now is None:
            return 0.0
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(day_start, now + timedelta(minutes=1)) or []
        closed = sum(d.profit + d.swap + d.commission for d in deals
                     if d.entry == mt5.DEAL_ENTRY_OUT and d.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL))
        return closed + sum(p.profit for p in (mt5.positions_get() or []))
    except Exception as exc:
        logger.error(f"Error obteniendo P&L diario de la cuenta: {exc}")
        return 0.0


def get_total_daily_pnl() -> float:
    """P&L total del día = realizados + no realizados (posiciones aún abiertas).
    El flotante suma TODOS los activos de este MAGIC_NUMBER (el panel web opera varios)."""
    realized   = get_realized_pnl_today()
    unrealized = sum(p.profit for p in (mt5.positions_get() or []) if p.magic == MAGIC_NUMBER)
    return realized + unrealized


def is_daily_loss_exceeded() -> bool:
    """
    Retorna True si la pérdida del día supera MAX_DAILY_LOSS_PCT del balance.
    Una vez tocado, queda bloqueado hasta el siguiente día del servidor: si no,
    el bloqueo se levantaba en cuanto el flotante mejoraba unos centavos.
    """
    global _halt_day
    now   = server_now()
    today = now.date() if now else _halt_day    # sin hora del servidor: mantener el bloqueo
    if _halt_day is not None and _halt_day == today:
        return True

    acc = get_account_info()
    if acc is None or acc.balance <= 0:
        return False

    daily_pnl = get_total_daily_pnl()
    limit = capital_tier(min(acc.balance, getattr(acc, "equity", acc.balance)))["daily_loss"]

    alert_only = getattr(_cfg, "DAILY_LOSS_ALERT_ONLY", False)
    if daily_pnl < 0:
        loss_pct = abs(daily_pnl) / acc.balance
        if alert_only:
            _daily_loss_alert(today, "del bot", daily_pnl, loss_pct, limit)
        elif loss_pct >= limit:
            _halt_day = today
            logger.warning(
                f"⛔ Límite diario alcanzado: P&L hoy = {daily_pnl:.2f} USD "
                f"({loss_pct*100:.2f}% ≥ {limit*100:.0f}%). "
                f"Sin nuevas operaciones hasta mañana."
            )
            return True

    # Corte de la cuenta completa: dos bots con 10% cada uno ya no pueden perder 20% el mismo día
    acc_limit = getattr(_cfg, "ACCOUNT_MAX_DAILY_LOSS_PCT", ACCOUNT_MAX_DAILY_LOSS_PCT)
    acc_pnl = get_account_daily_pnl()
    if acc_pnl < 0 and alert_only:
        _daily_loss_alert(today, "de la cuenta", acc_pnl, abs(acc_pnl) / acc.balance, acc_limit)
    elif acc_pnl < 0 and abs(acc_pnl) / acc.balance >= acc_limit:
        _halt_day = today
        logger.warning(
            f"⛔ Límite diario de la CUENTA alcanzado: P&L de todos los bots hoy = {acc_pnl:.2f} USD "
            f"(≥ {acc_limit*100:.0f}%). Sin nuevas operaciones hasta mañana."
        )
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN GLOBAL ANTES DE ABRIR
# ═══════════════════════════════════════════════════════════════════════════════

def dd_halted(equity: float, peak: float, pct) -> bool:
    """Corte total: la equity cayó `pct` desde su máximo (pct None o 0 = apagado)."""
    return bool(pct) and peak > 0 and equity <= peak * (1 - pct)


def _daily_loss_alert(today, scope: str, pnl: float, frac: float, limit: float) -> None:
    """DAILY_LOSS_ALERT_ONLY: avisa al 80 % y al 100 % del límite, una vez por día y umbral; no bloquea (decide el usuario)."""
    for level in (0.8, 1.0):
        if frac >= limit * level and (today, scope, level) not in _alerted:
            _alerted.add((today, scope, level))
            msg = (f"⚠ Pérdida diaria {scope}: {pnl:.2f} USD ({frac*100:.1f}%, límite {limit*100:.0f}%) — "
                   f"{'límite SUPERADO' if level == 1.0 else 'cerca del límite'}. "
                   f"El bot sigue operando: deténlo si no quieres continuar.")
            logger.warning(msg)
            notify(msg)


def can_open_trade(action: str, symbol: str = None) -> Tuple[bool, str]:
    """
    Verifica TODAS las condiciones de riesgo antes de abrir un nuevo trade.

    Checks:
      1. Límite de pérdida diaria no superado
      2. Número de trades simultáneos < MAX_OPEN_TRADES
      3. Margen libre suficiente (> 10% del balance)

    Returns:
        (True,  "")       si se puede abrir
        (False, "motivo") si NO se puede abrir
    """
    # 1. Pérdida diaria
    if is_daily_loss_exceeded():
        return False, "Límite de pérdida diaria alcanzado"

    # 2. Máximo de trades simultáneos (un error de lectura NO cuenta como "0 abiertas")
    if mt5.positions_get(symbol=symbol or SYMBOL) is None:
        return False, f"No se pudieron leer las posiciones abiertas: {mt5.last_error()}"
    acc = get_account_info()
    if acc is None:
        return False, "No se pudo obtener info de la cuenta"
    global _peak, _dd_stopped
    _peak = max(_peak, acc.equity)
    pct = getattr(_cfg, "MAX_DD_PCT", None)
    if _dd_stopped or dd_halted(acc.equity, _peak, pct):
        _dd_stopped = True
        return False, f"Corte total: la equity cayó {pct:.0%} desde su máximo ({_peak:,.2f}); reinicia el bot para seguir"
    tier = capital_tier(min(acc.balance, acc.equity))
    # Todas las posiciones de este MAGIC, en cualquier activo: el nivel limita el riesgo TOTAL abierto
    open_pos = [p for p in (mt5.positions_get() or []) if p.magic == MAGIC_NUMBER]
    if len(open_pos) >= tier["max_open"]:
        return False, f"Máximo de trades abiertos ({tier['max_open']}, nivel {tier['name']}) alcanzado"

    # 3. Margen libre
    if acc.balance > 0 and (acc.margin_free / acc.balance) < 0.10:
        return False, f"Margen libre insuficiente ({acc.margin_free:.2f} < 10% del balance)"

    return True, ""