"""
Gestión de Trades — XAU/USD Scalping Bot

Responsabilidades:
  • Abrir órdenes de mercado BUY/SELL en MT5
  • Cerrar posiciones por ticket o cerrar todas
  • Modificar SL/TP de posiciones existentes
  • Trailing stop automático (sigue al precio cada ciclo)
  • Break-even "BE+" automático: cuando el precio recorre ≥ BE_TRIGGER_PCT del
    camino al TP, mueve el SL a la entrada + un margen que cubre el spread
    (para salir en cero/positivo si el precio se devuelve).
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
    BE_TRIGGER_PCT, BE_PLUS_POINTS,
    ANTI_DUP_ATR_MULT,
    USE_PROGRESSIVE_TRAIL, TRAIL_LOCK_START_ATR,
    TRAIL_LOCK_PCT_MIN, TRAIL_LOCK_PCT_MAX, TRAIL_LOCK_FULL_ATR,
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

def update_breakeven(pos, atr: float, symbol_info) -> bool:
    """
    Mueve el SL a "BE+" (entrada + margen que cubre el spread) cuando el precio
    ya recorrió al menos BE_TRIGGER_PCT del camino hacia el TP (regla 50-70%).

    Disparo:
      • Con TP definido: profit ≥ BE_TRIGGER_PCT × distancia(entrada → TP).
      • Sin TP (fallback): profit ≥ BREAKEVEN_ATR_MULT × ATR.

    Colocación BE+ (no en la entrada exacta, para salir realmente en cero/positivo):
      • margen = spread_actual + BE_PLUS_POINTS × point
      • BUY:  SL = price_open + margen
      • SELL: SL = price_open - margen

    Solo actúa una vez (mientras el SL siga del lado perdedor de la entrada).
    El trailing stop se encarga de seguir asegurando ganancia a partir de ahí.
    """
    if not USE_BREAKEVEN:
        return False

    digits = symbol_info.digits
    point  = symbol_info.point

    # Margen BE+ : cubre el spread vivo + un extra configurable a tu favor
    tick      = get_tick()
    spread    = (tick.ask - tick.bid) if tick is not None else 0.0
    be_offset = spread + BE_PLUS_POINTS * point

    # Disparo por % del recorrido hacia el TP (fallback a ATR si la posición no tiene TP)
    tp_distance = abs(pos.tp - pos.price_open) if pos.tp else 0.0
    trigger = tp_distance * BE_TRIGGER_PCT if tp_distance > 0 else atr * BREAKEVEN_ATR_MULT

    if pos.type == mt5.ORDER_TYPE_BUY:
        if pos.sl >= pos.price_open:   # Ya está en BE+ o con profit protegido
            return False
        profit_distance = pos.price_current - pos.price_open
        if profit_distance >= trigger:
            new_sl = round(pos.price_open + be_offset, digits)
            if new_sl < pos.price_current and _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.info(
                    f"☑  BE+ BUY #{pos.ticket} | SL: {pos.sl:.{digits}f} → {new_sl:.{digits}f} "
                    f"(entrada {pos.price_open:.{digits}f} + {be_offset:.{digits}f} | "
                    f"recorrido {profit_distance:.{digits}f}/{trigger:.{digits}f})"
                )
                return True

    else:  # SELL
        if pos.sl <= pos.price_open:
            return False
        profit_distance = pos.price_open - pos.price_current
        if profit_distance >= trigger:
            new_sl = round(pos.price_open - be_offset, digits)
            if new_sl > pos.price_current and _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                logger.info(
                    f"☑  BE+ SELL #{pos.ticket} | SL: {pos.sl:.{digits}f} → {new_sl:.{digits}f} "
                    f"(entrada {pos.price_open:.{digits}f} - {be_offset:.{digits}f} | "
                    f"recorrido {profit_distance:.{digits}f}/{trigger:.{digits}f})"
                )
                return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# TRAILING STOP
# ═══════════════════════════════════════════════════════════════════════════════

def _progressive_lock_sl(pos, atr: float, is_buy: bool):
    """
    SL del "lock progresivo": asegura una fracción CRECIENTE del profit abierto a
    medida que el trade avanza. La fracción sube linealmente de TRAIL_LOCK_PCT_MIN
    a TRAIL_LOCK_PCT_MAX entre TRAIL_LOCK_START_ATR y TRAIL_LOCK_FULL_ATR (profit
    medido en múltiplos de ATR), de modo que un retroceso salga en positivo (→ ~1:1).

    Devuelve (new_sl, lock_pct) o None si el progresivo está desactivado o el profit
    todavía no supera TRAIL_LOCK_START_ATR (aún se deja correr).
    """
    if not USE_PROGRESSIVE_TRAIL or atr <= 0:
        return None

    profit = (pos.price_current - pos.price_open) if is_buy else (pos.price_open - pos.price_current)
    if profit <= 0:
        return None

    profit_atr = profit / atr
    if profit_atr < TRAIL_LOCK_START_ATR:
        return None

    span     = max(TRAIL_LOCK_FULL_ATR - TRAIL_LOCK_START_ATR, 1e-9)
    ramp     = min(max((profit_atr - TRAIL_LOCK_START_ATR) / span, 0.0), 1.0)
    lock_pct = TRAIL_LOCK_PCT_MIN + ramp * (TRAIL_LOCK_PCT_MAX - TRAIL_LOCK_PCT_MIN)
    locked   = profit * lock_pct

    new_sl = pos.price_open + locked if is_buy else pos.price_open - locked
    return new_sl, lock_pct


def _log_trail(direction: str, pos, new_sl: float, driver: str, lock_pct, digits: int) -> None:
    """Loguea el movimiento del trailing. El lock progresivo va a INFO (visible)."""
    arrow = "↑" if direction == "BUY" else "↓"
    if driver == "LOCK":
        logger.info(
            f"{arrow}  Trailing {direction} #{pos.ticket} | SL {pos.sl:.{digits}f} → {new_sl:.{digits}f} "
            f"| lock progresivo asegura {lock_pct * 100:.0f}% del profit"
        )
    else:
        logger.debug(
            f"{arrow}  Trailing {direction} #{pos.ticket} | "
            f"SL {pos.sl:.{digits}f} → {new_sl:.{digits}f} (ATR)"
        )


def update_trailing_stop(pos, atr: float, symbol_info) -> bool:
    """
    Trailing stop dinámico. En cada ciclo elige el SL MÁS protector entre:
      • Trail clásico ATR : precio ∓ TRAILING_ATR_MULT × ATR (deja respirar la tendencia)
      • Lock progresivo   : asegura una fracción creciente del profit abierto (→ ~1:1,
                            ver _progressive_lock_sl). Hace que la línea de SL avance
                            progresivamente hasta blindar casi toda la ganancia, para
                            que un "back" del precio cierre en positivo, no en pérdida.

    Reglas:
      • Solo mueve el SL en la dirección FAVORABLE (nunca lo empeora)
      • Respeta la distancia mínima exigida por el broker (trade_stops_level)
      • Se ejecuta en CADA ciclo → el trail es continuo
    """
    if not USE_TRAILING_STOP:
        return False

    digits   = symbol_info.digits
    min_dist = _min_stop_dist(symbol_info) + symbol_info.point * 3

    if pos.type == mt5.ORDER_TYPE_BUY:
        candidate, driver, lock_pct = pos.price_current - atr * TRAILING_ATR_MULT, "ATR", None
        lock = _progressive_lock_sl(pos, atr, is_buy=True)
        if lock is not None and lock[0] > candidate:   # el lock asegura más → úsalo
            candidate, lock_pct, driver = lock[0], lock[1], "LOCK"

        new_sl = round(candidate, digits)
        # Mover solo si mejora el SL actual y es seguro
        if new_sl > pos.sl and (pos.price_current - new_sl) >= min_dist:
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                _log_trail("BUY", pos, new_sl, driver, lock_pct, digits)
                return True

    else:  # SELL
        candidate, driver, lock_pct = pos.price_current + atr * TRAILING_ATR_MULT, "ATR", None
        lock = _progressive_lock_sl(pos, atr, is_buy=False)
        if lock is not None and lock[0] < candidate:   # el lock asegura más → úsalo
            candidate, lock_pct, driver = lock[0], lock[1], "LOCK"

        new_sl = round(candidate, digits)
        if new_sl < pos.sl and (new_sl - pos.price_current) >= min_dist:
            if _modify_sl(pos.ticket, new_sl, pos.tp, digits):
                _log_trail("SELL", pos, new_sl, driver, lock_pct, digits)
                return True

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# ANTI-DUPLICADO
# ═══════════════════════════════════════════════════════════════════════════════

def is_too_close_to_existing(action: str, current_price: float, atr: float) -> bool:
    """
    Devuelve True si ya hay una posición abierta en la misma dirección
    a menos de ANTI_DUP_ATR_MULT × ATR del precio actual.

    Cuando USE_ANTI_DUPLICATE = False retorna False directamente (sin filtro).
    Cuando USE_ANTI_DUPLICATE = True exige al menos ANTI_DUP_ATR_MULT×ATR de distancia.
    """
    if not USE_ANTI_DUPLICATE:
        return False

    positions    = get_open_positions()
    min_dist     = atr * ANTI_DUP_ATR_MULT
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

    Si el break-even movió el SL en este ciclo, NO corremos el trailing acto
    seguido: el objeto `pos` en memoria aún tiene el SL viejo y el trailing
    podría calcular mal y deshacer el BE+. El trailing retoma el ciclo siguiente
    con la posición ya refrescada.
    """
    positions = get_open_positions()
    if not positions:
        return

    for pos in positions:
        moved_be = update_breakeven(pos, atr, symbol_info)
        if not moved_be:
            update_trailing_stop(pos, atr, symbol_info)