"""
Gestión de Trades — XAU/USD Scalping Bot

Responsabilidades:
  • Abrir órdenes de mercado BUY/SELL en MT5
  • Cerrar posiciones por ticket o cerrar todas
  • Modificar SL/TP de posiciones existentes
  • Trailing stop automático (sigue al precio cada ciclo)
  • Break-even automático con dos modos configurables:
      - "pct_tp"     → regla matemática (dispara al alcanzar X% del TP)
      - "structure"  → regla técnica (vela de ruptura + micro-fractal en M1)

Notas de compatibilidad MT5:
  • filling_mode: bitmask del símbolo (1=FOK, 2=IOC soportados)
  • trade_stops_level: distancia mínima en puntos para SL/TP (algunos brokers = 0)
  • Comentarios de orden: MT5 limita a 31 caracteres
"""
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from typing import Optional

from logger_config import logger
from config import (
    SYMBOL, MAGIC_NUMBER, MAX_SLIPPAGE,
    USE_TRAILING_STOP, USE_BREAKEVEN,
    BREAKEVEN_MODE, BREAKEVEN_TRIGGER_PCT_OF_TP,
    BREAKEVEN_ATR_MULT, BREAKEVEN_BUFFER_USD,
    ESTIMATED_COMMISSION_USD, TRAILING_ATR_MULT,
    TP_ATR_MULT, MICRO_TF, MICRO_FRACTAL_LOOKBACK,
    BREAKOUT_CANDLE_BODY_ATR_MULT,
)
from data_handler import get_open_positions, get_tick, fetch_ohlcv
from indicators import calc_atr


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES INTERNAS
# ═══════════════════════════════════════════════════════════════════════════════

def _get_filling_mode(symbol_info) -> int:
    """
    Detecta el modo de ejecución aceptado por el broker para este símbolo.
    filling_mode bitmask: 1=FOK, 2=IOC.
    """
    fm = getattr(symbol_info, "filling_mode", 0)
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def _min_stop_dist(symbol_info) -> float:
    """Distancia mínima entre precio y SL/TP exigida por el broker (en precio)."""
    return symbol_info.trade_stops_level * symbol_info.point


# ═══════════════════════════════════════════════════════════════════════════════
# ABRIR TRADE
# ═══════════════════════════════════════════════════════════════════════════════

def open_trade(action: str, sl: float, tp: float, lot: float,
               symbol_info, comment: str = "") -> Optional[int]:
    """
    Envía una orden de mercado a MT5.

    BUY  → se ejecuta al precio ASK
    SELL → se ejecuta al precio BID

    Args:
        action:     "BUY" o "SELL"
        sl:         Precio de Stop Loss (ya calculado con la distancia correcta)
        tp:         Precio de Take Profit
        lot:        Tamaño del lote
        symbol_info: Objeto mt5.SymbolInfo del símbolo
        comment:    Etiqueta extra en el comentario de la orden

    Returns:
        Número de ticket (int) si la orden se ejecutó correctamente.
        None si falló.
    """
    tick = get_tick()
    if tick is None:
        logger.error("No se pudo obtener tick para abrir trade.")
        return None

    if action == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        exec_price = tick.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        exec_price = tick.bid

    digits  = symbol_info.digits
    filling = _get_filling_mode(symbol_info)

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       float(lot),
        "type":         order_type,
        "price":        round(exec_price, digits),
        "sl":           round(sl, digits),
        "tp":           round(tp, digits),
        "deviation":    MAX_SLIPPAGE,
        "magic":        MAGIC_NUMBER,
        "comment":      f"XAU {comment}"[:31],
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)

    # Fallback: si el filling mode fue rechazado, probar con RETURN
    if result and result.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
        logger.debug(f"Filling {filling} rechazado. Reintentando con ORDER_FILLING_RETURN...")
        request["type_filling"] = mt5.ORDER_FILLING_RETURN
        result = mt5.order_send(request)

    if result is None:
        logger.error(f"order_send retornó None: {mt5.last_error()}")
        return None

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(
            f"✅ {action} abierto | Ticket: #{result.order} | Lote: {lot} | "
            f"Entry: {exec_price:.{digits}f} | SL: {sl:.{digits}f} | TP: {tp:.{digits}f}"
        )
        return result.order

    logger.error(
        f"❌ Error abriendo {action} | retcode: {result.retcode} | "
        f"Descripción: {result.comment} | Último error: {mt5.last_error()}"
    )
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# CERRAR TRADES
# ═══════════════════════════════════════════════════════════════════════════════

def close_trade(ticket: int, symbol_info) -> bool:
    """
    Cierra una posición específica por número de ticket.

    Returns:
        True si se cerró correctamente, False si falló.
    """
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        logger.warning(f"Posición #{ticket} no encontrada para cerrar.")
        return False

    pos  = positions[0]
    tick = get_tick()
    if tick is None:
        return False

    # Tipo opuesto al de la posición abierta
    if pos.type == mt5.ORDER_TYPE_BUY:
        close_type  = mt5.ORDER_TYPE_SELL
        close_price = tick.bid
    else:
        close_type  = mt5.ORDER_TYPE_BUY
        close_price = tick.ask

    digits  = symbol_info.digits
    filling = _get_filling_mode(symbol_info)

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       SYMBOL,
        "volume":       pos.volume,
        "type":         close_type,
        "position":     ticket,
        "price":        round(close_price, digits),
        "deviation":    MAX_SLIPPAGE,
        "magic":        MAGIC_NUMBER,
        "comment":      "XAU close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": filling,
    }

    result = mt5.order_send(request)

    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
        logger.info(
            f"🔒 {direction} #{ticket} cerrado | "
            f"P&L: {pos.profit:+.2f} USD | Lote: {pos.volume}"
        )
        return True

    logger.error(
        f"❌ Error cerrando #{ticket} | "
        f"retcode: {result.retcode if result else 'None'} | "
        f"{mt5.last_error()}"
    )
    return False


def close_all_trades(symbol_info) -> int:
    """
    Cierra todas las posiciones abiertas del bot (filtradas por MAGIC_NUMBER).

    Returns:
        Número de posiciones que se lograron cerrar.
    """
    positions = get_open_positions()
    if not positions:
        logger.info("No hay posiciones abiertas para cerrar.")
        return 0

    logger.info(f"Cerrando {len(positions)} posición(es)...")
    closed = sum(1 for pos in positions if close_trade(pos.ticket, symbol_info))
    logger.info(f"🔒 {closed}/{len(positions)} posiciones cerradas.")
    return closed


# ═══════════════════════════════════════════════════════════════════════════════
# MODIFICAR SL / TP
# ═══════════════════════════════════════════════════════════════════════════════

def _modify_sl(ticket: int, new_sl: float, current_tp: float, digits: int) -> bool:
    """
    Modifica solo el SL de una posición (mantiene el TP).
    Usa TRADE_ACTION_SLTP que no requiere precio de ejecución.
    """
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol":   SYMBOL,
        "sl":       round(new_sl, digits),
        "tp":       round(current_tp, digits),
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        return True
    logger.debug(
        f"Fallo al modificar SL de #{ticket}: "
        f"retcode={result.retcode if result else 'None'}"
    )
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# BREAK-EVEN
# ═══════════════════════════════════════════════════════════════════════════════

def _warn_if_buffer_too_small(pos, buf: float) -> float:
    """
    Calcula el valor en USD que protege el buffer actual y advierte UNA vez
    si no alcanza a cubrir la comisión estimada del broker.
    Returns: buf_value_usd (para incluirlo en el log de confirmación).
    """
    buf_value_usd = buf * 100 * pos.volume  # 100 oz por lote estándar en XAUUSD
    if buf_value_usd < ESTIMATED_COMMISSION_USD * pos.volume:
        logger.warning(
            f"⚠  BREAKEVEN_BUFFER_USD={buf} genera solo ${buf_value_usd:.2f} "
            f"protegidos en #{pos.ticket}, pero la comisión estimada es "
            f"${ESTIMATED_COMMISSION_USD * pos.volume:.2f}. Sube BREAKEVEN_BUFFER_USD "
            f"en config.py para garantizar profit neto real."
        )
    return buf_value_usd


def update_breakeven(pos, atr: float, symbol_info) -> bool:
    """
    Despacha al modo de break-even configurado en BREAKEVEN_MODE:
      • "pct_tp"    → regla matemática: dispara al alcanzar X% de la distancia al TP
      • "structure" → regla técnica: vela de ruptura confirmada o micro-fractal en M1
    """
    if not USE_BREAKEVEN:
        return False

    if BREAKEVEN_MODE == "structure":
        return _update_breakeven_structure(pos, symbol_info)
    return _update_breakeven_pct_tp(pos, atr, symbol_info)


def _update_breakeven_pct_tp(pos, atr: float, symbol_info) -> bool:
    """
    Regla matemática (50-70%): mueve el SL a break-even + buffer cuando el
    profit alcanza BREAKEVEN_TRIGGER_PCT_OF_TP de la distancia al TP.

    Usa el TP REAL guardado en la posición (pos.tp), no el ATR actual —
    así el disparo no cambia si la volatilidad varía después de abrir el trade.
    Si la posición no tiene TP definido (ej. abierta manualmente), cae al
    fallback BREAKEVEN_ATR_MULT × ATR actual.

    Lógica:
      • BUY:  si price_current - price_open ≥ trigger → SL = price_open + buf
      • SELL: si price_open - price_current ≥ trigger → SL = price_open - buf

    El buffer (BREAKEVEN_BUFFER_USD) es un valor FIJO en USD que cubre
    spread + comisión, para no salir exactamente en 0 y terminar en pérdida
    neta tras costos.
    """
    digits = symbol_info.digits
    buf    = BREAKEVEN_BUFFER_USD

    # Distancia al TP real de la posición (más preciso que recalcular con ATR actual)
    if pos.tp and pos.tp != 0:
        tp_distance = abs(pos.tp - pos.price_open)
    else:
        tp_distance = atr * TP_ATR_MULT  # Fallback si no hay TP definido

    trigger = tp_distance * BREAKEVEN_TRIGGER_PCT_OF_TP
    buf_value_usd = _warn_if_buffer_too_small(pos, buf)

    if pos.type == mt5.ORDER_TYPE_BUY:
        if pos.sl >= pos.price_open:   # Ya está en BE o con profit protegido
            return False
        profit_distance = pos.price_current - pos.price_open
        if profit_distance >= trigger:
            new_sl = round(pos.price_open + buf, digits)
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                pct_reached = (profit_distance / tp_distance * 100) if tp_distance else 0
                logger.info(
                    f"☑  BE (%TP) BUY #{pos.ticket} | SL: {pos.sl:.{digits}f} → "
                    f"{new_sl:.{digits}f} | {pct_reached:.0f}% del TP recorrido | "
                    f"+${buf_value_usd:.2f} protegidos"
                )
                return True

    else:  # SELL
        if pos.sl <= pos.price_open:
            return False
        profit_distance = pos.price_open - pos.price_current
        if profit_distance >= trigger:
            new_sl = round(pos.price_open - buf, digits)
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                pct_reached = (profit_distance / tp_distance * 100) if tp_distance else 0
                logger.info(
                    f"☑  BE (%TP) SELL #{pos.ticket} | SL: {pos.sl:.{digits}f} → "
                    f"{new_sl:.{digits}f} | {pct_reached:.0f}% del TP recorrido | "
                    f"+${buf_value_usd:.2f} protegidos"
                )
                return True

    return False


# ── Regla técnica: vela de ruptura + micro-fractal ─────────────────────────────

def _detect_micro_fractal(df: pd.DataFrame, lookback: int, kind: str) -> Optional[float]:
    """
    Detecta el micro-fractal CONFIRMADO más reciente en el DataFrame.

      kind="low"  → mínimo rodeado de `lookback` velas más altas a cada lado
                    (fractal alcista: "escudo" para mover el SL en un BUY)
      kind="high" → máximo rodeado de `lookback` velas más bajas a cada lado
                    (fractal bajista: "escudo" para mover el SL en un SELL)

    Un fractal solo se considera "confirmado" cuando ya existen `lookback`
    velas cerradas DESPUÉS de él (si no, podría cambiar / repintarse).
    Recorre de la vela más reciente confirmable hacia atrás y retorna
    el primer fractal que encuentra (el más cercano al precio actual).
    """
    if len(df) < (2 * lookback + 1):
        return None

    col = "low" if kind == "low" else "high"
    # i va desde la última vela con margen de confirmación, hacia atrás
    for i in range(len(df) - lookback - 1, lookback - 1, -1):
        window = df[col].iloc[i - lookback: i + lookback + 1]
        center = df[col].iloc[i]
        if kind == "low" and center == window.min():
            return float(center)
        if kind == "high" and center == window.max():
            return float(center)
    return None


def _has_breakout_confirmation(df: pd.DataFrame, entry_time: datetime,
                               direction: str, atr_m1: float) -> bool:
    """
    Busca la primera vela M1 cerrada DESPUÉS de la entrada cuyo cuerpo sea
    ≥ BREAKOUT_CANDLE_BODY_ATR_MULT × ATR(M1) y vaya en la dirección del trade.

    Esto representa la regla: "si la siguiente vela cierra con cuerpo grande
    a tu favor" — confirma que la ruptura tiene fuerza real, no es ruido.
    """
    after_entry = df[df.index > entry_time]
    if after_entry.empty:
        return False

    min_body = atr_m1 * BREAKOUT_CANDLE_BODY_ATR_MULT
    for _, c in after_entry.iterrows():
        body = abs(c["close"] - c["open"])
        if body < min_body:
            continue
        if direction == "BUY" and c["close"] > c["open"]:
            return True
        if direction == "SELL" and c["close"] < c["open"]:
            return True
    return False


def _update_breakeven_structure(pos, symbol_info) -> bool:
    """
    Regla técnica: mueve el SL a break-even solo cuando hay confirmación
    estructural en M1, no por un porcentaje fijo de profit.

    Prioridad de la señal de protección:
      1. Micro-fractal a favor: si ya se formó un mínimo más alto (BUY) o
         máximo más bajo (SELL) que la entrada, ese nivel actúa como "escudo"
         — el SL se coloca justo debajo/encima de él (no en la entrada exacta).
      2. Vela de ruptura confirmada: si no hay fractal aún pero ya cerró una
         vela M1 con cuerpo grande a favor, se usa el break-even clásico
         (entrada + buffer).

    Si ninguna de las dos condiciones se cumple, el SL no se mueve —
    incluso si el precio ya está en profit. Esto evita mover el SL por
    rupturas falsas o ruido de 1 minuto.
    """
    direction = "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL"
    digits    = symbol_info.digits
    buf       = BREAKEVEN_BUFFER_USD

    # Ya protegido — nada que hacer (el trailing stop sigue desde aquí)
    if direction == "BUY" and pos.sl >= pos.price_open:
        return False
    if direction == "SELL" and pos.sl <= pos.price_open:
        return False

    # Velas M1 suficientes para detectar fractales + confirmar ruptura
    df = fetch_ohlcv(SYMBOL, MICRO_TF, 60)
    if df is None or len(df) < (2 * MICRO_FRACTAL_LOOKBACK + 5):
        return False

    atr_m1_series = calc_atr(df["high"], df["low"], df["close"])
    if atr_m1_series.empty or pd.isna(atr_m1_series.iloc[-1]):
        return False
    atr_m1 = float(atr_m1_series.iloc[-1])

    entry_time   = datetime.utcfromtimestamp(pos.time)
    fractal_kind = "low" if direction == "BUY" else "high"
    fractal      = _detect_micro_fractal(df, MICRO_FRACTAL_LOOKBACK, fractal_kind)
    breakout_ok  = _has_breakout_confirmation(df, entry_time, direction, atr_m1)

    candidate_sl, source = None, ""

    if direction == "BUY":
        if fractal is not None and fractal > pos.price_open:
            candidate_sl = fractal - buf * 0.3   # Un poco por debajo del fractal
            source = f"micro-fractal alcista ${fractal:.2f}"
        elif breakout_ok:
            candidate_sl = pos.price_open + buf
            source = "vela de ruptura confirmada (M1)"

        if candidate_sl is not None and candidate_sl > pos.price_open:
            new_sl = round(candidate_sl, digits)
            buf_value_usd = _warn_if_buffer_too_small(pos, candidate_sl - pos.price_open)
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.info(
                    f"☑  BE (estructura) BUY #{pos.ticket} | "
                    f"SL: {pos.sl:.{digits}f} → {new_sl:.{digits}f} | "
                    f"origen: {source} | +${buf_value_usd:.2f} protegidos"
                )
                return True

    else:  # SELL
        if fractal is not None and fractal < pos.price_open:
            candidate_sl = fractal + buf * 0.3   # Un poco por encima del fractal
            source = f"micro-fractal bajista ${fractal:.2f}"
        elif breakout_ok:
            candidate_sl = pos.price_open - buf
            source = "vela de ruptura confirmada (M1)"

        if candidate_sl is not None and candidate_sl < pos.price_open:
            new_sl = round(candidate_sl, digits)
            buf_value_usd = _warn_if_buffer_too_small(pos, pos.price_open - candidate_sl)
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.info(
                    f"☑  BE (estructura) SELL #{pos.ticket} | "
                    f"SL: {pos.sl:.{digits}f} → {new_sl:.{digits}f} | "
                    f"origen: {source} | +${buf_value_usd:.2f} protegidos"
                )
                return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# TRAILING STOP
# ═══════════════════════════════════════════════════════════════════════════════

def update_trailing_stop(pos, atr: float, symbol_info) -> bool:
    """
    Trailing stop dinámico: el SL sigue al precio actual manteniendo
    una distancia de TRAILING_ATR_MULT × ATR.

    Reglas:
      • Solo mueve el SL en la dirección FAVORABLE (nunca lo empeora)
      • Respeta la distancia mínima exigida por el broker (trade_stops_level)
      • Se ejecuta en CADA ciclo → el trail es continuo
    """
    if not USE_TRAILING_STOP:
        return False

    trail_dist = atr * TRAILING_ATR_MULT
    digits     = symbol_info.digits
    min_dist   = _min_stop_dist(symbol_info) + symbol_info.point * 3

    if pos.type == mt5.ORDER_TYPE_BUY:
        new_sl = round(pos.price_current - trail_dist, digits)
        # Mover solo si mejora el SL actual y es seguro
        if new_sl > pos.sl and (pos.price_current - new_sl) >= min_dist:
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.debug(
                    f"↑  Trailing BUY #{pos.ticket} | "
                    f"SL {pos.sl:.{digits}f} → {new_sl:.{digits}f}"
                )
                return True

    else:  # SELL
        new_sl = round(pos.price_current + trail_dist, digits)
        if new_sl < pos.sl and (new_sl - pos.price_current) >= min_dist:
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.debug(
                    f"↓  Trailing SELL #{pos.ticket} | "
                    f"SL {pos.sl:.{digits}f} → {new_sl:.{digits}f}"
                )
                return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# GESTIÓN GLOBAL EN CADA CICLO
# ═══════════════════════════════════════════════════════════════════════════════

def manage_open_trades(atr: float, symbol_info) -> None:
    """
    Ejecuta break-even y trailing stop sobre TODAS las posiciones abiertas del bot.
    Se llama al inicio de cada ciclo del loop, ANTES de buscar nuevas señales.

    Orden de prioridad:
      1. Break-even (protege capital primero)
      2. Trailing stop (maximiza profit después)
    """
    positions = get_open_positions()
    if not positions:
        return

    for pos in positions:
        update_breakeven(pos, atr, symbol_info)
        update_trailing_stop(pos, atr, symbol_info)