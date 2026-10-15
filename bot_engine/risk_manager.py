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
from .data_handler import get_open_positions, get_account_info, server_now

_halt_day = None    # día (hora servidor) en que se tocó el límite diario → bloquea hasta el siguiente


# ═══════════════════════════════════════════════════════════════════════════════
# TAMAÑO DE LOTE
# ═══════════════════════════════════════════════════════════════════════════════

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
    tick_value = symbol_info.trade_tick_value  # USD por lote por tick
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
        lot, next_lot = 0.0, min_lot
    else:
        lot, next_lot = round(lot, 8), (lot + step if step > 0 else None)

    if next_lot is None or next_lot > max_lot + 1e-9:
        return lot, None
    return lot, next_lot * sl_value_per_lot / RISK_PER_TRADE


def calculate_lot(account, symbol_info, sl_distance: float) -> float:
    """Lote para el trade (ver lot_plan). 0.0 → no operar, con el motivo en el log."""
    lot, need = lot_plan(account, symbol_info, sl_distance)
    if lot <= 0:
        if need is None:
            logger.warning("tick_size/tick_value/distancia SL inválidos. Trade omitido.")
        else:
            logger.warning(
                f"El lote mínimo no cabe en el riesgo de {RISK_PER_TRADE*100:.1f}% con SL de "
                f"{sl_distance:.2f}: necesita capital ≥ {need:,.2f}. Trade omitido."
            )
    return lot


# ═══════════════════════════════════════════════════════════════════════════════
# STOP LOSS Y TAKE PROFIT
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_sl_tp(action: str, exec_price: float,
                    atr: float, symbol_info) -> Tuple[float, float]:
    """
    Calcula SL y TP en precio absoluto desde el precio de ejecución real.

    Args:
        action:     "BUY" o "SELL"
        exec_price: Precio real de ejecución (ask para BUY, bid para SELL)
        atr:        ATR actual en precio (USD para XAUUSD)
        symbol_info: Información del símbolo (para dígitos y stops_level)

    Returns:
        (stop_loss_price, take_profit_price)
    """
    sl_dist  = atr * SL_ATR_MULT
    tp_dist  = atr * TP_ATR_MULT
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


def check_risk_reward(exec_price: float, sl: float, tp: float) -> Tuple[bool, float]:
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
    return rr >= MIN_RR, rr


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


def get_total_daily_pnl() -> float:
    """P&L total del día = realizados + no realizados (posiciones aún abiertas)."""
    realized   = get_realized_pnl_today()
    unrealized = sum(p.profit for p in get_open_positions())
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

    if daily_pnl < 0:
        loss_pct = abs(daily_pnl) / acc.balance
        if loss_pct >= MAX_DAILY_LOSS_PCT:
            _halt_day = today
            logger.warning(
                f"⛔ Límite diario alcanzado: P&L hoy = {daily_pnl:.2f} USD "
                f"({loss_pct*100:.2f}% ≥ {MAX_DAILY_LOSS_PCT*100:.0f}%). "
                f"Sin nuevas operaciones hasta mañana."
            )
            return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN GLOBAL ANTES DE ABRIR
# ═══════════════════════════════════════════════════════════════════════════════

def can_open_trade(action: str) -> Tuple[bool, str]:
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
    if mt5.positions_get(symbol=SYMBOL) is None:
        return False, f"No se pudieron leer las posiciones abiertas: {mt5.last_error()}"
    open_pos = get_open_positions()
    if len(open_pos) >= MAX_OPEN_TRADES:
        return False, f"Máximo de trades abiertos ({MAX_OPEN_TRADES}) alcanzado"

    # 3. Margen libre
    acc = get_account_info()
    if acc is None:
        return False, "No se pudo obtener info de la cuenta"
    if acc.balance > 0 and (acc.margin_free / acc.balance) < 0.10:
        return False, f"Margen libre insuficiente ({acc.margin_free:.2f} < 10% del balance)"

    return True, ""