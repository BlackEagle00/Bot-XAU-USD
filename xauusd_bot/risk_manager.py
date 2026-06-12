"""
Gestión de Riesgo — XAU/USD Scalping Bot

Responsabilidades:
  • Calcular tamaño de lote basado en balance y ATR (Wilder)
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
import MetaTrader5 as mt5
from datetime import datetime, date
from typing import Tuple

from logger_config import logger
from config import (
    SYMBOL, MAGIC_NUMBER,
    RISK_PER_TRADE, MAX_OPEN_TRADES, MAX_DAILY_LOSS_PCT,
    SL_ATR_MULT, TP_ATR_MULT, MIN_LOT, MAX_LOT
)
from data_handler import get_open_positions, get_account_info


# ═══════════════════════════════════════════════════════════════════════════════
# TAMAÑO DE LOTE
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_lot(account, symbol_info, atr: float) -> float:
    """
    Calcula el lote óptimo para arriesgar exactamente RISK_PER_TRADE % del balance.

    Usa los valores reales del símbolo (trade_tick_size y trade_tick_value)
    para ser preciso con cualquier broker y cuenta.
    """
    risk_amount = account.balance * RISK_PER_TRADE

    sl_distance = atr * SL_ATR_MULT           # Distancia del SL en precio (USD)
    tick_size   = symbol_info.trade_tick_size  # Mínimo movimiento de precio
    tick_value  = symbol_info.trade_tick_value # USD por lote por tick

    if tick_size <= 0 or tick_value <= 0:
        logger.warning("tick_size/tick_value inválidos. Usando lote mínimo.")
        return MIN_LOT

    sl_in_ticks      = sl_distance / tick_size
    sl_value_per_lot = sl_in_ticks * tick_value

    if sl_value_per_lot <= 0:
        return MIN_LOT

    lot = risk_amount / sl_value_per_lot

    # Redondear al volume_step del broker (usualmente 0.01)
    step = symbol_info.volume_step
    if step > 0:
        lot = round(round(lot / step) * step, 8)

    # Respetar límites del símbolo y de la config
    lot = max(max(MIN_LOT, symbol_info.volume_min),
              min(min(MAX_LOT, symbol_info.volume_max), lot))

    return round(lot, 2)


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


# ═══════════════════════════════════════════════════════════════════════════════
# P&L DIARIO
# ═══════════════════════════════════════════════════════════════════════════════

def get_realized_pnl_today() -> float:
    """
    Retorna la ganancia/pérdida realizada del día actual.
    Incluye profit, swap y comisión de los deals de cierre.
    """
    try:
        today_start = datetime.combine(date.today(), datetime.min.time())
        deals = mt5.history_deals_get(today_start, datetime.now())
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
    Cuando se cumple, registra una advertencia y bloquea nuevas operaciones.
    """
    acc = get_account_info()
    if acc is None:
        return False

    daily_pnl = get_total_daily_pnl()

    if daily_pnl < 0:
        loss_pct = abs(daily_pnl) / acc.balance
        if loss_pct >= MAX_DAILY_LOSS_PCT:
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

    # 2. Máximo de trades simultáneos
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