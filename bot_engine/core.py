"""
╔══════════════════════════════════════════════════════════════╗
║   Motor compartido — Loop Principal (Oro/EUR · swing/scalp)  ║
╚══════════════════════════════════════════════════════════════╝

Punto de entrada: run(). Cada bot lo arranca desde su carpeta con un main.py
lanzador que pone su config.py en sys.path. Las temporalidades, símbolo y demás
parámetros se leen de ESE config.py.

El bot ejecuta el siguiente ciclo cada LOOP_INTERVAL segundos:
  1. Verificar conexión MT5
  2. Obtener OHLCV de las 3 temporalidades (primaria / tendencia / superior)
  3. Calcular indicadores (EMA, RSI, MACD, ATR, ADX, BB, VWAP, S&R)
  4. Detectar 35+ patrones de velas japonesas
  5. Generar score ponderado + filtros (gates)
  6. Verificar condiciones de riesgo
  7. Abrir trade si la señal supera MIN_SIGNAL_SCORE y pasa los filtros
  8. Gestionar posiciones existentes (trailing stop, break-even)
  9. Dormir el tiempo restante del intervalo

Detención: Ctrl+C → cierre limpio (las posiciones abiertas se conservan en MT5)
"""
import time
import signal
import sys
from datetime import datetime

import MetaTrader5 as mt5

from .logger_config import logger
from config import (
    SYMBOL, LOOP_INTERVAL, MAX_OPEN_TRADES,
    MIN_SIGNAL_SCORE, RISK_PER_TRADE, MIN_RR,
    SL_ATR_MULT, TP_ATR_MULT, ATR_VOLATILITY_MIN, TF_LABELS,
    USE_ORDERFLOW, USE_INTERMARKET, USE_NEWS_FILTER,
    USE_MACRO_CONTEXT, BOT_LABEL,
)
from .connection import connect, disconnect, is_market_open
from .data_handler import (
    get_market_data, get_tick, get_account_info,
    get_symbol_info, get_open_positions,
    get_orderflow_delta, get_intermarket_bias, server_now,
)
from .indicators import calculate_all
from .patterns import analyze_patterns
from .signals import generate_signal
from .news_filter import in_news_blackout
from .risk_manager import (
    calculate_lot, lot_plan, calculate_sl_tp, check_risk_reward,
    can_open_trade, get_total_daily_pnl, capital_tier, spread_ok, fit_sl_to_capital, over_min_lot_cap,
)
from . import ml_filter, grid
import config as _cfg
from .trade_manager import (
    open_trade, close_all_trades,
    manage_open_trades, is_too_close_to_existing
)
from .telegram_notifier import (
    notify, check_closed_positions,
    notify_connection_lost, notify_connection_restored,
)


# ─── Estado global del bot ────────────────────────────────────────────────────
_running      = True    # Controla el loop principal
_cycle_num    = 0       # Contador de ciclos ejecutados
_trades_today = 0       # Trades abiertos en la sesión actual
_symbol_info  = None    # Cache de mt5.SymbolInfo (se carga una vez al inicio)
_last_balance = None    # Balance del último chequeo de lote dinámico
USE_GRID      = getattr(_cfg, "USE_GRID", False)   # bot grid + cesta (bot_engine/grid.py)
GRID_EXEC_TF  = getattr(_cfg, "GRID_EXEC_TF", None) # "M1"/"M5": el grid analiza en PRIMARY_TF y opera con este ATR
_last_basket_bar = None                             # vela de análisis de la última cesta (1 cesta por vela)
GRID_ONE_PER_BAR = getattr(_cfg, "GRID_ONE_PER_BAR", True)   # False: varias cestas por vela (las separa grid.extra_basket_block)
_last_trade_bar  = None                             # vela de señal de la última entrada (1 por vela, como el backtest)
ENTRY_WINDOW_MIN = getattr(_cfg, "ENTRY_WINDOW_MIN", None)   # min tras el cierre de la vela en que se puede entrar (None = sin límite)


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
    logger.info(f"🤖  {BOT_LABEL}  |  by mt5-python")
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
    global _cycle_num, _trades_today, _last_balance, _last_trade_bar

    _cycle_num += 1

    # ── 1. Verificar conexión ─────────────────────────────────────────────────
    if not mt5.terminal_info():
        logger.warning("⚡ Conexión perdida. Reconectando...")
        if not connect(retries=2, delay=3):
            logger.error("No se pudo reconectar. Ciclo omitido.")
            notify_connection_lost()
            return
        notify_connection_restored()

    # ── 2. Obtener tick actual ────────────────────────────────────────────────
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
    ind_primary = calculate_all(data["primary"], price)  # TF primario — análisis principal
    ind_trend   = calculate_all(data["trend"],   price)  # TF tendencia — confirmación
    # TF macro (D1 oro / H1 oro-scalp): sesga el score y, en oro swing, veta la
    # contra-tendencia macro fuerte. Solo se computa si el bot usa contexto macro
    # (USE_MACRO_CONTEXT); puede faltar si el broker no devolvió el TF superior.
    ind_higher  = (
        calculate_all(data["higher"], price)
        if USE_MACRO_CONTEXT and data.get("higher") is not None else None
    )

    # ── 6. Gestionar posiciones ANTES de cualquier filtro de entrada ──────────
    #      (break-even y trailing corren en cada ciclo, aunque el spread esté
    #       alto o el mercado plano: esos filtros solo frenan entradas NUEVAS)
    atr = ind_primary.get("atr")
    gatr = None
    if USE_GRID:
        grid.manage_basket(_symbol_info)               # TP/stop/tiempo de la cesta + re-armar niveles
        gatr = grid.exec_atr(atr)
    if atr is not None:
        manage_open_trades(atr, _symbol_info)
        # Lote dinámico: re-evaluar con el saldo cuando cambia el balance y cada 20 ciclos
        acc = get_account_info()
        if acc and (acc.balance != _last_balance or _cycle_num % 20 == 0) and (gatr or not USE_GRID):
            _last_balance = acc.balance
            _log_lot_capacity(acc, tick, gatr or atr)

    # Avisar por Telegram las posiciones que se cerraron (SL/TP/manual) desde el ciclo previo
    check_closed_positions(get_open_positions())

    # ── 7. Filtros de entrada: liquidez (spread) y volatilidad (ATR mínimo) ───
    if not is_market_open():
        logger.debug("🕐 Mercado cerrado o spread alto. Sin entradas nuevas.")
        return
    if atr is None or atr < ATR_VOLATILITY_MIN:
        logger.debug(f"ATR {atr} < mínimo {ATR_VOLATILITY_MIN}. Mercado plano, sin operar.")
        return

    # ── 8. Factores direccionales extra (order-flow + inter-mercado) ──────────
    of_delta = get_orderflow_delta() if USE_ORDERFLOW else None
    im_bias  = get_intermarket_bias() if USE_INTERMARKET else None

    # ── 9. Detectar patrones de velas + generar señal ─────────────────────────
    trend   = _detect_trend_simple(ind_primary)
    patterns = analyze_patterns(data["primary"], trend)
    signal  = generate_signal(price, ind_primary, ind_trend, patterns, atr,
                              ind_higher, orderflow=of_delta, intermarket=im_bias)

    # ── 9. Intentar abrir un nuevo trade si hay señal válida ──────────────────
    if USE_GRID and signal["action"] in ("BUY", "SELL") and gatr:
        _try_open_basket(signal["action"], tick, data["primary"].index[-1].timestamp(), gatr, signal["score"])
    elif signal["action"] in ("BUY", "SELL") and _entry_bar_ok(data["primary"].index[-1].timestamp(), signal.get("score", 0.0)):
        bundle = _ml_bundle()                      # None si el filtro predictivo está apagado
        feats = ml_filter.features(1 if signal["action"] == "BUY" else -1, price, ind_primary,
                                   ind_trend, ind_higher, signal, tick.ask - tick.bid,
                                   tick.time) if bundle else None
        if _try_open_trade(signal, price, tick, atr, (bundle, feats)):
            _last_trade_bar = data["primary"].index[-1].timestamp()

    # ── 10. Resumen periódico ─────────────────────────────────────────────────
    if _cycle_num % 20 == 0:
        _print_status()


def _tf_minutes(tf) -> int:
    """Minutos de un TF de MT5 ("M5" o la constante: M1..M30 = minutos; H1..D1 = 0x4000 | horas)."""
    if isinstance(tf, str):
        return int(tf[1:]) * (60 if tf[0] == "H" else 1)
    return tf if tf < 0x4000 else (tf & 0x3FFF) * 60


def _ml_bundle():
    """Filtro predictivo activo, salvo con capital ≥ ML_FILTER_MAX_CAPITAL (swing: desde 500 USD rinde más sin él)."""
    bundle = ml_filter.bundle_for(SYMBOL)
    cap = getattr(_cfg, "ML_FILTER_MAX_CAPITAL", None)
    acc = get_account_info() if bundle and cap else None
    return None if acc and min(acc.balance, acc.equity) >= cap else bundle


def _entry_bar_ok(bar_open: float, score: float = 0.0) -> bool:
    """
    Una entrada por vela de señal, y solo en los primeros ENTRY_WINDOW_MIN minutos tras su cierre: el
    backtest entra en la apertura siguiente a la señal. Sin esto, tras un SL la misma señal reabría en la
    misma vela (lo que quemó al grid M1 el 2026-10-26) y una señal tardía entraba a mitad de vela.
    Pedido del usuario 2026-10-26: con ENTRY_RETRY_MIN la ventana se repite cada N min (swing: cada vela
    H1 dentro de la H4) y con |score| ≥ LATE_ENTRY_SCORE entra aunque la vela ya haya arrancado.
    """
    if bar_open == _last_trade_bar:
        return False
    if ENTRY_WINDOW_MIN is None or abs(score) >= getattr(_cfg, "LATE_ENTRY_SCORE", float("inf")):
        return True
    now = server_now()
    if now is None:
        return False
    since = now.timestamp() - (bar_open + _tf_minutes(_cfg.PRIMARY_TF) * 60)
    every = getattr(_cfg, "ENTRY_RETRY_MIN", None)
    return since >= 0 and (since % (every * 60) if every else since) < ENTRY_WINDOW_MIN * 60


def _try_open_basket(action: str, tick, bar_open: float, atr: float, score: float = None):
    """
    Una cesta por vela de análisis, y solo durante la primera vela de ejecución tras su cierre: es lo que
    simula el backtest (simulate_grid entra en la apertura siguiente a la señal). Sin esto, una señal H1
    seguía "viva" toda la hora y cada cesta cerrada en TP abría otra con la misma señal.
    """
    global _last_basket_bar
    now = server_now()
    bar_close = bar_open + _tf_minutes(_cfg.PRIMARY_TF) * 60
    window = _tf_minutes(GRID_EXEC_TF or _cfg.PRIMARY_TF) * 60
    if now is None or not 0 <= now.timestamp() - bar_close < window:
        return
    # Varias por vela solo como EXTRA de una cesta abierta: si la anterior ya cerró, no se reabre con la misma
    # señal (2026-10-26 14:31–14:37: 10 cestas en 6 min reabriendo tras cada SL, −15 USD)
    if bar_open == _last_basket_bar and (GRID_ONE_PER_BAR or not grid.baskets(symbol_info=_symbol_info)):
        return
    res = grid.try_open_basket(action, tick, atr, _symbol_info, score=score)
    if res["ok"]:
        _last_basket_bar = bar_open
    else:
        logger.debug(f"🧺 Cesta {action} no abierta: {res['reason']}")


def _log_lot_capacity(acc, tick, atr: float):
    """Qué lote permite el capital de hoy con el SL actual y cuánto falta para subirlo."""
    if USE_GRID:                                       # el grid se dimensiona por cesta, no por trade
        capital = min(acc.balance, acc.equity)
        g = grid.plan("BUY", tick, atr, _symbol_info, capital)
        if g["levels"]:
            logger.info(f"💰 Capital {capital:,.2f} · cesta de {len(g['levels'])} nivel(es), lote "
                        f"{g['levels'][0]['lot']} · riesgo {g['risk_usd']:.2f} ({g['risk_pct']}%) · TP cesta {g['tp_usd']:.2f}"
                        + (f" · RIESGO ELEVADO (recomendado ≥ {g['capital_needed']:,.2f})" if g["elevated"] else ""))
        else:
            logger.info(f"💰 Capital {capital:,.2f} · ni una cesta de 1 nivel con el lote mínimo cabe en el "
                        f"{g['cap_pct']:.0f}%: necesitas ≥ {g['capital_needed']:,.2f}")
        return
    sl, _ = calculate_sl_tp("BUY", tick.ask, atr, _symbol_info)
    sl_dist = tick.ask - sl
    lot, need = lot_plan(acc, _symbol_info, sl_dist)
    nxt = (f"siguiente lote con capital ≥ {need:,.2f}" if need is not None
           else "lote máximo alcanzado")
    capital = min(acc.balance, acc.equity)
    tier = capital_tier(capital)
    logger.info(
        f"💰 Capital {capital:,.2f} · nivel {tier['name']} (máx {tier['max_open']} abiertas, "
        f"corte diario {tier['daily_loss']*100:.0f}%) · riesgo {RISK_PER_TRADE*100:.1f}% → "
        f"lote {lot if lot > 0 else 'ninguno: no cabe el mínimo'} con SL {sl_dist:.2f} | {nxt}"
    )


def _try_open_trade(signal: dict, price: float, tick, atr: float, ml=(None, None)):
    """
    Orquesta la apertura de un trade después de validar todas las condiciones.

    Flujo:
      can_open_trade() → is_too_close_to_existing() → calculate_lot()
      → calculate_sl_tp() → open_trade()
    """
    global _trades_today

    action = signal["action"]

    # A0. Filtro de noticias de alto impacto (blackout alrededor del evento)
    if USE_NEWS_FILTER:
        in_black, ev = in_news_blackout()
        if in_black:
            logger.info(f"📰 Trade {action} bloqueado por noticia de alto impacto: {ev}")
            return

    # A. Validar condiciones de riesgo (pérdida diaria, máx trades, margen)
    ok, reason = can_open_trade(action)
    if not ok:
        logger.info(f"🚫 Trade {action} bloqueado: {reason}")
        return

    # B. Anti-duplicado: evita abrir al mismo nivel de precio
    if is_too_close_to_existing(action, price, atr):
        logger.info(f"⚠  {action} ignorado: posición existente demasiado cercana.")
        return

    # B2. Filtro predictivo: solo señales con P(TP antes que SL) ≥ τ, con el SL/TP del modelo
    bundle, feats = ml
    sl_m = tp_m = min_rr = None
    if bundle:
        allowed, p = ml_filter.allows(bundle, feats)
        if not allowed:
            logger.info(f"🧠 {action} descartado: P(éxito) {p:.0%} < umbral {bundle['tau']:.0%}")
            return
        sl_m, tp_m = bundle["sl_mult"], bundle["tp_mult"]
        min_rr = tp_m / sl_m * 0.9
        logger.info(f"🧠 {action} aprobado: P(éxito) {p:.0%} ≥ {bundle['tau']:.0%} "
                    f"(SL {sl_m}×ATR / TP {tp_m}×ATR)")

    # C. Precio de ejecución real (ask para BUY, bid para SELL)
    exec_price = tick.ask if action == "BUY" else tick.bid

    # D. Calcular SL y TP
    sl, tp = calculate_sl_tp(action, exec_price, atr, _symbol_info, sl_m, tp_m)

    # D2. Verificar R:R real (el broker puede deformarlo con su distancia mínima)
    rr_ok, rr = check_risk_reward(exec_price, sl, tp, min_rr)
    if not rr_ok:
        logger.info(f"🚫 Trade {action} descartado: R:R real {rr:.2f} < mínimo {min_rr or MIN_RR}")
        return

    # D3. El spread es un costo fijo: con stops cortos se come la ventaja
    if not spread_ok(tick.ask - tick.bid, abs(exec_price - sl)):
        logger.info(f"🚫 Trade {action} descartado: spread {tick.ask - tick.bid:.2f} > 25% del stop")
        return

    # E. Calcular lote con la distancia REAL del SL (el broker puede haberla ampliado)
    acc = get_account_info()
    if acc is None:
        return
    # E2. Cuenta pequeña: si el lote mínimo arriesga más que el tope, SL/TP más cercanos con el mismo R:R (MICRO_SL_FIT)
    if over_min_lot_cap(acc, _symbol_info, abs(exec_price - sl)):
        fit = fit_sl_to_capital(action, exec_price, sl, tp, acc, _symbol_info, atr)
        if fit:
            if not spread_ok(tick.ask - tick.bid, abs(exec_price - fit[0])):
                logger.info(f"🚫 Trade {action} descartado: con el SL de cuenta pequeña el spread pesa > 25%")
                return
            logger.info(f"🪙 Cuenta pequeña: SL {sl:.2f}→{fit[0]:.2f} y TP {tp:.2f}→{fit[1]:.2f} "
                        f"para que el lote mínimo quepa en el riesgo máximo")
            sl, tp = fit
    lot = calculate_lot(acc, _symbol_info, abs(exec_price - sl))
    if lot <= 0:
        return

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
    return ticket


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
        notify(
            f"🟢 Bot iniciado | {SYMBOL} {TF_LABELS} | "
            f"Balance: {acc.balance:,.2f} {acc.currency}"
        )
    else:
        notify(f"🟢 Bot iniciado | {SYMBOL} {TF_LABELS}")

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

    notify(
        f"🔴 Bot detenido | Ciclos: {_cycle_num} | "
        f"Trades en esta sesión: {_trades_today}",
        block=True,
    )
    disconnect()
    logger.info(
        f"✅ Bot detenido. Ciclos ejecutados: {_cycle_num} | "
        f"Trades abiertos en esta sesión: {_trades_today}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    run()