"""
Gestión de Trades — EUR/USD Scalping Bot

Responsabilidades:
  • Abrir órdenes de mercado BUY/SELL en MT5
  • Cerrar posiciones por ticket o cerrar todas
  • Modificar SL/TP de posiciones existentes
  • Trailing stop automático (sigue al precio cada ciclo)
  • Break-even automático (protege capital cuando hay profit ≥ 1×ATR)
  • Verificar duplicados (no abrir al mismo precio dos veces)

Notas de compatibilidad MT5:
  • filling_mode: bitmask del símbolo (1=FOK, 2=IOC soportados)
  • trade_stops_level: distancia mínima en puntos para SL/TP (algunos brokers = 0)
  • Comentarios de orden: MT5 limita a 31 caracteres
"""
import MetaTrader5 as mt5
from typing import Optional

from logger_config import logger
from config import (
    SYMBOL, MAGIC_NUMBER, MAX_SLIPPAGE,
    USE_TRAILING_STOP, USE_BREAKEVEN, USE_ANTI_DUPLICATE,
    BREAKEVEN_ATR_MULT, TRAILING_ATR_MULT,
)
from data_handler import get_open_positions, get_tick


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
        "comment":      f"EURs {comment}"[:31],
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

def update_breakeven(pos, atr: float, symbol_info) -> bool:
    """
    Mueve el SL a break-even + buffer cuando el profit ≥ BREAKEVEN_ATR_MULT × ATR.

    Lógica:
      • BUY:  si price_current - price_open ≥ trigger → SL = price_open + buf
      • SELL: si price_open - price_current ≥ trigger → SL = price_open - buf
    
    Solo actúa si el SL aún está "en pérdida" (por debajo/encima de la entrada).
    Una vez que el SL está en BE o mejor, no vuelve a moverse con esta función.
    """
    if not USE_BREAKEVEN:
        return False

    trigger = atr * BREAKEVEN_ATR_MULT
    digits  = symbol_info.digits
    buf     = symbol_info.point * 5  # +5 puntos sobre la entrada (no exactamente en 0)

    if pos.type == mt5.ORDER_TYPE_BUY:
        if pos.sl >= pos.price_open:   # Ya está en BE o con profit protegido
            return False
        profit_distance = pos.price_current - pos.price_open
        if profit_distance >= trigger:
            new_sl = round(pos.price_open + buf, digits)
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.info(
                    f"☑  Break-even BUY #{pos.ticket} | "
                    f"SL: {pos.sl:.{digits}f} → {new_sl:.{digits}f}"
                )
                return True

    else:  # SELL
        if pos.sl <= pos.price_open:
            return False
        profit_distance = pos.price_open - pos.price_current
        if profit_distance >= trigger:
            new_sl = round(pos.price_open - buf, digits)
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.info(
                    f"☑  Break-even SELL #{pos.ticket} | "
                    f"SL: {pos.sl:.{digits}f} → {new_sl:.{digits}f}"
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
# ANTI-DUPLICADO
# ═══════════════════════════════════════════════════════════════════════════════

def is_too_close_to_existing(action: str, current_price: float, atr: float) -> bool:
    """
    Devuelve True si ya hay una posición abierta en la misma dirección
    a menos de 0.5 × ATR del precio actual.

    Cuando USE_ANTI_DUPLICATE = False retorna False directamente (sin filtro).
    Cuando USE_ANTI_DUPLICATE = True exige al menos 0.5×ATR de distancia.
    """
    if not USE_ANTI_DUPLICATE:
        return False

    positions    = get_open_positions()
    min_dist     = atr * 0.5
    target_type  = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL

    for pos in positions:
        if pos.type == target_type:
            dist = abs(pos.price_open - current_price)
            if dist < min_dist:
                logger.debug(
                    f"Anti-dup: {action} bloqueado. #{pos.ticket} abierto en "
                    f"{pos.price_open:.2f} a solo {dist:.3f} de distancia "
                    f"(mín {min_dist:.3f})"
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