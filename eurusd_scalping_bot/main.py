"""
╔══════════════════════════════════════════════════════════════╗
║         EUR/USD Scalping Bot — Loop Principal                ║
╚══════════════════════════════════════════════════════════════╝

Uso:
    python main.py

El bot ejecuta el siguiente ciclo cada LOOP_INTERVAL segundos:
  1. Verificar conexión MT5
  2. Obtener OHLCV de M5 / M15 / H1
  3. Calcular indicadores (EMA, RSI, MACD, ATR, BB, VWAP, S&R)
  4. Detectar 35+ patrones de velas japonesas
  5. Generar score ponderado (−12 a +12)
  6. Verificar condiciones de riesgo
  7. Abrir trade si score ≥ |4.5|
  8. Gestionar posiciones existentes (trailing stop, break-even)
  9. Dormir el tiempo restante del intervalo

Detención: Ctrl+C → cierre limpio (las posiciones abiertas se conservan en MT5)
"""
import time
import signal
import sys
from datetime import datetime

import MetaTrader5 as mt5

from logger_config import logger
from config import (
    SYMBOL, LOOP_INTERVAL, MAX_OPEN_TRADES,
    MIN_SIGNAL_SCORE, RISK_PER_TRADE, MIN_RR,
    SL_ATR_MULT, TP_ATR_MULT, ATR_VOLATILITY_MIN, TF_LABELS,
)
from connection import connect, disconnect, is_market_open
from data_handler import (
    get_market_data, get_tick, get_account_info,
    get_symbol_info, get_open_positions
)
from indicators import calculate_all
from patterns import analyze_patterns
from signals import generate_signal
from risk_manager import (
    calculate_lot, calculate_sl_tp, check_risk_reward,
    can_open_trade, get_total_daily_pnl
)
from trade_manager import (
    open_trade, close_all_trades,
    manage_open_trades, is_too_close_to_existing
)


# ─── Estado global del bot ────────────────────────────────────────────────────
_running      = True    # Controla el loop principal
_cycle_num    = 0       # Contador de ciclos ejecutados
_trades_today = 0       # Trades abiertos en la sesión actual
_symbol_info  = None    # Cache de mt5.SymbolInfo (se carga una vez al inicio)


# ═══════════════════════════════════════════════════════════════════════════════
# MANEJADORES DE SEÑAL DEL SO
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_exit(sig, frame):
    """Captura Ctrl+C y SIGTERM para un cierre ordenado."""
    global _running
    logger.info("⚠  Señal de cierre recibida. Finalizando ciclo actual...")
    _running = False


# ═══════════════════════════════════════════════════════════════════════════════
# MENSAJES DE INICIO
# ═══════════════════════════════════════════════════════════════════════════════

def _print_banner():
    sep = "═" * 64
    logger.info(sep)
    logger.info("🤖  EUR/USD Scalping Bot  |  by mt5-python")
    logger.info(sep)


def _print_config(acc):
    """Muestra un resumen de la configuración activa al arrancar."""
    logger.info(
        f"⚙   Símbolo: {SYMBOL} | TF: {TF_LABELS} | "
        f"Score mín: ±{MIN_SIGNAL_SCORE} | "
        f"Riesgo: {RISK_PER_TRADE*100:.0f}%/trade | "
        f"Máx trades: {MAX_OPEN_TRADES}"
    )
    logger.info(
        f"📐  SL: {SL_ATR_MULT}×ATR | TP: {TP_ATR_MULT}×ATR | "
        f"Ciclo: {LOOP_INTERVAL}s | "
        f"ATR mín: {ATR_VOLATILITY_MIN}"
    )
    logger.info(
        f"💰  Balance: {acc.balance:,.2f} {acc.currency} | "
        f"Equity: {acc.equity:,.2f} | "
        f"Margen libre: {acc.margin_free:,.2f} | "
        f"Apalancamiento: 1:{acc.leverage}"
    )
    logger.info("▶   Bot activo. Presiona Ctrl+C para detener.")
    logger.info("═" * 64)


# ═══════════════════════════════════════════════════════════════════════════════
# CICLO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_trend_simple(ind: dict) -> str:
    """
    Determina la tendencia de fondo con EMA9 vs EMA50.
    Se usa para contextualizar los patrones de 1 vela (Hammer, Shooting Star…)
    """
    e9, e50 = ind.get("ema9"), ind.get("ema50")
    if None in [e9, e50]:
        return "neutral"
    if e9 > e50:
        return "up"
    if e9 < e50:
        return "down"
    return "neutral"


def _run_cycle():
    """
    Ejecuta un ciclo completo de análisis y ejecución.
    Toda la lógica de trading vive aquí.
    """
    global _cycle_num, _trades_today

    _cycle_num += 1

    # ── 1. Verificar conexión ─────────────────────────────────────────────────
    if not mt5.terminal_info():
        logger.warning("⚡ Conexión perdida. Reconectando...")
        if not connect(retries=2, delay=3):
            logger.error("No se pudo reconectar. Ciclo omitido.")
            return

    # ── 2. Verificar liquidez del mercado ─────────────────────────────────────
    if not is_market_open():
        logger.debug("🕐 Mercado cerrado o spread alto. Saltando ciclo.")
        return

    # ── 3. Obtener tick actual ────────────────────────────────────────────────
    tick = get_tick()
    if tick is None:
        return
    price = (tick.ask + tick.bid) / 2

    # ── 4. Obtener datos OHLCV (M5 + M15 + H1) ───────────────────────────────
    data = get_market_data()
    if data is None:
        logger.warning("No se pudieron obtener datos de mercado. Ciclo omitido.")
        return

    # ── 5. Calcular indicadores ───────────────────────────────────────────────
    ind_primary = calculate_all(data["primary"], price)  # M5 — análisis principal
    ind_trend   = calculate_all(data["trend"],   price)  # M15 — confirmación

    # ── 6. Filtro de volatilidad (ATR mínimo) ─────────────────────────────────
    atr = ind_primary.get("atr")
    if atr is None or atr < ATR_VOLATILITY_MIN:
        logger.debug(f"ATR {atr} < mínimo {ATR_VOLATILITY_MIN}. Mercado plano, sin operar.")
        return

    # ── 7. Gestionar posiciones ANTES de buscar señales ───────────────────────
    #      (break-even y trailing se ejecutan en cada ciclo)
    manage_open_trades(atr, _symbol_info)

    # ── 8. Detectar patrones de velas + generar señal ─────────────────────────
    trend   = _detect_trend_simple(ind_primary)
    patterns = analyze_patterns(data["primary"], trend)
    signal  = generate_signal(price, ind_primary, ind_trend, patterns, atr)

    # ── 9. Intentar abrir un nuevo trade si hay señal válida ──────────────────
    if signal["action"] in ("BUY", "SELL"):
        _try_open_trade(signal, price, tick, atr)

    # ── 10. Resumen periódico ─────────────────────────────────────────────────
    if _cycle_num % 20 == 0:
        _print_status()


def _try_open_trade(signal: dict, price: float, tick, atr: float):
    """
    Orquesta la apertura de un trade después de validar todas las condiciones.

    Flujo:
      can_open_trade() → is_too_close_to_existing() → calculate_lot()
      → calculate_sl_tp() → open_trade()
    """
    global _trades_today

    action = signal["action"]

    # A. Validar condiciones de riesgo (pérdida diaria, máx trades, margen)
    ok, reason = can_open_trade(action)
    if not ok:
        logger.info(f"🚫 Trade {action} bloqueado: {reason}")
        return

    # B. Anti-duplicado: evita abrir al mismo nivel de precio
    if is_too_close_to_existing(action, price, atr):
        logger.info(f"⚠  {action} ignorado: posición existente demasiado cercana.")
        return

    # C. Precio de ejecución real (ask para BUY, bid para SELL)
    exec_price = tick.ask if action == "BUY" else tick.bid

    # D. Calcular SL y TP
    sl, tp = calculate_sl_tp(action, exec_price, atr, _symbol_info)

    # D2. Verificar R:R real (el broker puede deformarlo con su distancia mínima)
    rr_ok, rr = check_risk_reward(exec_price, sl, tp)
    if not rr_ok:
        logger.info(f"🚫 Trade {action} descartado: R:R real {rr:.2f} < mínimo {MIN_RR}")
        return

    # E. Calcular lote basado en el balance actual
    acc = get_account_info()
    if acc is None:
        return
    lot = calculate_lot(acc, _symbol_info, atr)

    # F. Log previo a la ejecución
    logger.info(
        f"🎯 Señal {action} | Score: {signal['score']:+.2f} | "
        f"Lote: {lot} | Entry: {exec_price:.2f} | "
        f"SL: {sl:.2f} | TP: {tp:.2f} | ATR: {atr:.3f}"
    )
    # Mostrar el resumen del score por componente
    bd = signal.get("breakdown", {})
    if bd:
        logger.debug(
            f"   Score breakdown → "
            f"EMA:{bd.get('ema',0):+.2f} RSI:{bd.get('rsi',0):+.2f} "
            f"MACD:{bd.get('macd',0):+.2f} BB:{bd.get('bollinger',0):+.2f} "
            f"Pat:{bd.get('patterns',0):+.2f} S/R:{bd.get('sr',0):+.2f} "
            f"VWAP:{bd.get('vwap',0):+.2f}"
        )
    for reason_text in signal.get("reasons", [])[:5]:
        logger.debug(f"   ↳ {reason_text}")

    # G. Enviar orden a MT5
    ticket = open_trade(action, sl, tp, lot, _symbol_info,
                        comment=f"s{signal['score']:+.1f}")
    if ticket:
        _trades_today += 1


# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN DE ESTADO
# ═══════════════════════════════════════════════════════════════════════════════

def _print_status():
    """Imprime un resumen del estado del bot cada 20 ciclos (~10 minutos)."""
    acc       = get_account_info()
    positions = get_open_positions()
    daily_pnl = get_total_daily_pnl()
    now       = datetime.now().strftime("%H:%M:%S")

    open_detail = ""
    if positions:
        unrealized = sum(p.profit for p in positions)
        types = [("BUY" if p.type == 0 else "SELL") for p in positions]
        open_detail = (
            f" | Abiertas: {len(positions)} [{', '.join(types)}] "
            f"(no realizado: {unrealized:+.2f})"
        )

    balance_str = f" | Balance: {acc.balance:,.2f} {acc.currency}" if acc else ""

    logger.info(
        f"── STATUS {now} ── "
        f"Ciclo #{_cycle_num} | "
        f"Trades sesión: {_trades_today} | "
        f"P&L hoy: {daily_pnl:+.2f} USD"
        f"{open_detail}"
        f"{balance_str}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    """
    Inicializa el bot y ejecuta el loop principal.
    Llama a esta función desde el bloque __main__.
    """
    global _symbol_info

    # Registrar manejadores de cierre limpio
    signal.signal(signal.SIGINT,  _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    _print_banner()

    # ── Conexión a MT5 ────────────────────────────────────────────────────────
    if not connect():
        logger.critical("No se pudo conectar a MT5. Abortando.")
        sys.exit(1)

    # ── Información del símbolo (se cachea globalmente) ───────────────────────
    _symbol_info = get_symbol_info()
    if _symbol_info is None:
        logger.critical(f"No se pudo obtener información de {SYMBOL}. Abortando.")
        disconnect()
        sys.exit(1)

    # ── Resumen inicial ───────────────────────────────────────────────────────
    acc = get_account_info()
    if acc:
        _print_config(acc)

    # ── Loop principal ────────────────────────────────────────────────────────
    logger.info(f"🔄 Loop iniciado (cada {LOOP_INTERVAL}s). Ctrl+C para detener.")

    while _running:
        t_start = time.time()

        try:
            _run_cycle()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.error(
                f"❌ Error inesperado en ciclo #{_cycle_num}: {exc}",
                exc_info=True
            )
            time.sleep(5)  # Pausa breve antes de reintentar el ciclo

        # Dormir el tiempo restante del intervalo
        elapsed    = time.time() - t_start
        sleep_time = max(0.5, LOOP_INTERVAL - elapsed)
        time.sleep(sleep_time)

    # ── Cierre limpio ─────────────────────────────────────────────────────────
    logger.info("🛑 Deteniendo bot...")
    _print_status()

    # Las posiciones abiertas se mantienen en MT5.
    # Si quieres cerrarlas descomenta la siguiente línea:
    # close_all_trades(_symbol_info)

    disconnect()
    logger.info(
        f"✅ Bot detenido. Ciclos ejecutados: {_cycle_num} | "
        f"Trades abiertos en esta sesión: {_trades_today}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    run()