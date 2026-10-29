"""
Trabajador del panel web: un proceso por PERFIL (xauusd_swing, xauusd_scalping, xauusd_grid).

Lo lanza dashboard/server.py. Habla por líneas JSON:
  stdin  ← {"type": "trade", "id": 1, "symbol": "XAUUSD", "action": "BUY"}
  stdout → {"type": "hello" | "analysis" | "trade_result" | "fatal", ...}
Todas las llamadas a MT5 ocurren en el hilo principal (la API de MT5 no es multihilo).
"""
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

PROFILE = sys.argv[1] if len(sys.argv) > 1 else "xauusd_scalping"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if PROFILE.startswith("_") or not (HERE / "profiles" / PROFILE / "config.py").exists():
    sys.exit(f"perfil inválido: {PROFILE}")

_OUT = sys.stdout               # canal del protocolo
sys.stdout = sys.stderr         # cualquier print/log del motor va a stderr, no al protocolo
sys.path[:0] = [str(HERE / "profiles" / PROFILE), str(ROOT)]
os.chdir(HERE)                  # el log del perfil (dashboard_<modo>.log) queda en dashboard/

import MetaTrader5 as mt5       # noqa: E402
import config                   # noqa: E402  (perfil de la clase)
from bot_engine.symbols import resolve_symbol   # noqa: E402
_base_sym = config.SYMBOL
config.SYMBOL = resolve_symbol(_base_sym, getattr(config, "SYMBOL_ALIASES", ()))   # antes de importar el motor
config.SECTIONS = {k: [config.SYMBOL if s == _base_sym else s for s in v] for k, v in config.SECTIONS.items()}
MODE = config.MODE
GRID = MODE == "grid"           # perfil xauusd_grid: la orden abre una cesta (bot_engine/grid.py)
from bot_engine.connection import connect                                   # noqa: E402
from bot_engine.data_handler import fetch_ohlcv, get_account_info, get_tick  # noqa: E402
from bot_engine.indicators import calculate_all                             # noqa: E402
from bot_engine.patterns import analyze_patterns                            # noqa: E402
from bot_engine.signals import generate_signal                              # noqa: E402
from bot_engine.core import _detect_trend_simple                            # noqa: E402
from bot_engine.news_filter import in_news_blackout                         # noqa: E402
from bot_engine.risk_manager import (                                       # noqa: E402
    calculate_sl_tp, check_risk_reward, calculate_lot, lot_plan, can_open_trade, _tick_value, lot_risk_pct,
    capital_tier, spread_ok, fit_sl_to_capital, over_min_lot_cap)
from bot_engine import ml_filter, grid                                      # noqa: E402
from bot_engine.trade_manager import open_trade, is_too_close_to_existing   # noqa: E402

REFRESH_SECS   = 10
STALE_TICK_SEC = 300            # sin ticks en 5 min → mercado cerrado
TRADE_MAX_AGE  = 15             # s: una orden más vieja se descarta (el servidor espera 30 s)
_queue         = queue.Queue()  # mensajes del servidor (los lee un hilo; los atiende el principal)
_state         = {"exit": False}
SYMBOLS        = [s for group in config.SECTIONS.values() for s in group]
_last = {}                      # último análisis por símbolo


def calibration_edge(profile: str):
    """Resultado fuera de muestra de backtesting/calibrate.py para la configuración vigente del perfil."""
    f = ROOT / "backtesting" / "reports" / f"calibration_{profile}.json"
    try:
        res = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    current = res["oos"] if res.get("written") else res["baseline_oos"]
    return {**current, "date": res.get("date"), "edge": bool(current.get("pf") and current["pf"] > 1.0)}


EDGE = calibration_edge(PROFILE)


def send(msg: dict):
    _OUT.write(json.dumps(msg) + "\n")      # ASCII escapado: inmune a la codificación de la consola
    _OUT.flush()


def _read_stdin(q: queue.Queue):
    for line in sys.stdin:
        try:
            q.put(json.loads(line))
        except ValueError:
            continue
    q.put({"type": "exit"})


# ═══════════════════════════════════════════════════════════════════════════════
# ANÁLISIS
# ═══════════════════════════════════════════════════════════════════════════════

def analyze(sym: str, now: int) -> dict:
    info = mt5.symbol_info(sym)
    if info is None:
        return {"symbol": sym, "available": False}
    if not info.visible:
        mt5.symbol_select(sym, True)
    tick = mt5.symbol_info_tick(sym)
    prim = fetch_ohlcv(sym, config.PRIMARY_TF, config.CANDLES_PRIMARY)
    trend = fetch_ohlcv(sym, config.TREND_TF, config.CANDLES_TREND)
    if prim is None or trend is None or len(prim) < 50 or len(trend) < 5:
        return {"symbol": sym, "available": True, "name": info.description, "error": "sin histórico suficiente"}
    higher = fetch_ohlcv(sym, config.HIGHER_TF, config.CANDLES_HIGHER) if config.USE_MACRO_CONTEXT else None

    has_quote = tick is not None and tick.bid > 0 and tick.ask > 0
    price = (tick.bid + tick.ask) / 2 if has_quote else float(prim["close"].iloc[-1])
    ip, it = calculate_all(prim, price), calculate_all(trend, price)
    ih = calculate_all(higher, price) if higher is not None and len(higher) >= 5 else None
    atr = ip.get("atr") or 0.0
    pats = analyze_patterns(prim, _detect_trend_simple(ip))
    sig = generate_signal(price, ip, it, pats, atr, ih)

    is_open = (has_quote and info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL
               and now - int(tick.time) <= STALE_TICK_SEC)
    score = float(sig["score"])
    bias = "BUY" if score > 0 else ("SELL" if score < 0 else "NEUTRAL")
    plan = ml = None
    bundle = ml_filter.bundle_for(sym)
    if bundle and bias != "NEUTRAL" and atr > 0:
        spread = (tick.ask - tick.bid) if has_quote else 0.0
        feats = ml_filter.features(1 if bias == "BUY" else -1, price, ip, it, ih, sig, spread,
                                   int(tick.time) if tick else now)
        prob = ml_filter.probability(bundle, feats)
        ml = {"p": round(prob, 3), "tau": bundle["tau"], "ok": prob >= bundle["tau"],
              "sl_mult": bundle["sl_mult"], "tp_mult": bundle["tp_mult"],
              "oos_win": bundle.get("oos", {}).get("win_rate_pct")}
    if bias != "NEUTRAL" and atr > 0 and has_quote:
        px = tick.ask if bias == "BUY" else tick.bid
        sl, tp = calculate_sl_tp(bias, px, atr, info, ml and ml["sl_mult"], ml and ml["tp_mult"])
        acc = get_account_info()
        lot, need = lot_plan(acc, info, abs(px - sl)) if acc else (0.0, None)
        fitted = False
        if acc and over_min_lot_cap(acc, info, abs(px - sl)):   # cuenta pequeña: SL/TP más cercanos, mismo R:R
            fit = fit_sl_to_capital(bias, px, sl, tp, acc, info, atr)
            if fit and spread_ok(tick.ask - tick.bid, abs(px - fit[0])):
                (sl, tp), fitted = fit, True
                lot, need = lot_plan(acc, info, abs(px - sl))
        plan = {"entry": px, "sl": sl, "tp": tp, "lot": lot, "fitted": fitted,
                "cap_pct": round(getattr(config, "MAX_RISK_MIN_LOT", 0.05) * 100),
                "capital_needed": round(need, 2) if need is not None else None,
                "risk_usd": round(abs(px - sl) / info.trade_tick_size * _tick_value(info) * lot, 2),
                "risk_pct": round(lot_risk_pct(acc, info, abs(px - sl), lot) * 100, 2) if acc and lot else None,
                "elevated": bool(acc and lot and lot_risk_pct(acc, info, abs(px - sl), lot) > config.RISK_PER_TRADE + 1e-9)}

    grid_view = None
    if GRID:
        acc = get_account_info()
        gatr = grid.exec_atr(atr, sym)                             # el grid opera con el ATR de GRID_EXEC_TF
        grid_view = {"basket": grid.basket_status(sym, info), "atr": gatr}
        if bias != "NEUTRAL" and gatr and has_quote and acc:
            gp = grid.plan(bias, tick, gatr, info, min(acc.balance, acc.equity))
            grid_view.update(gp)
            lv0 = gp["levels"][0] if gp["levels"] else None
            plan = ({"entry": lv0["price"], "sl": gp["sl"], "tp": lv0["tp"], "lot": lv0["lot"], "capital_needed": gp["capital_needed"],
                     "risk_usd": round(gp["risk_usd"], 2), "risk_pct": gp["risk_pct"], "elevated": gp["elevated"]}
                    if lv0 else {"lot": 0, "capital_needed": gp["capital_needed"], "cap_pct": gp["cap_pct"]})

    res = {
        "symbol": sym, "available": True, "name": info.description, "digits": info.digits,
        "price": round(price, info.digits), "open": bool(is_open),
        "spread_pts": int(round((tick.ask - tick.bid) / info.point)) if has_quote else None,
        "atr": round(atr, info.digits), "action": sig["action"], "score": round(score, 2),
        "threshold": config.MIN_SIGNAL_SCORE, "bias": bias, "trend": sig.get("trend"),
        "blockers": [r for r in sig.get("reasons", []) if "⛔" in r],
        "reasons": sig.get("reasons", [])[:8],
        "patterns": {"bullish": pats.get("bullish", []), "bearish": pats.get("bearish", [])},
        "rsi": round(ip["rsi"], 1) if ip.get("rsi") is not None else None,
        "adx": round(ip["adx"], 1) if ip.get("adx") is not None else None,
        "plan": plan, "ml": ml, "grid": grid_view, "updated": now,
    }
    _last[sym] = res
    return res


def analyze_all() -> dict:
    ticks = [mt5.symbol_info_tick(s) for s in SYMBOLS]
    now = max([int(t.time) for t in ticks if t] or [int(time.time())])   # hora del servidor
    cards = {}
    for sym in SYMBOLS:
        if GRID and mt5.symbol_info(sym):
            grid.manage_basket(mt5.symbol_info(sym), sym)      # TP/stop/tiempo de las cestas del panel
        _serve_pending()                                # un clic no espera al análisis completo
        try:
            cards[sym] = analyze(sym, now)
        except Exception as exc:                        # un activo roto no tumba el panel
            cards[sym] = {"symbol": sym, "available": True, "error": str(exc)[:200]}
    acc = get_account_info()
    return {
        "profile": PROFILE, "mode": MODE, "label": config.MODE_LABEL, "tfs": config.TF_LABELS, "server_time": now,
        "sections": {name: [cards[s] for s in group] for name, group in config.SECTIONS.items()},
        "edge": EDGE,
        "account": {"balance": acc.balance, "equity": acc.equity, "currency": acc.currency,
                    "demo": acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,
                    "risk_pct": config.RISK_PER_TRADE * 100,
                    "tier": capital_tier(min(acc.balance, acc.equity))} if acc else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ÓRDENES
# ═══════════════════════════════════════════════════════════════════════════════

def trade(sym: str, action: str) -> dict:
    """Mismas compuertas que core._try_open_trade, para el activo elegido en el panel."""
    if sym not in SYMBOLS or action not in ("BUY", "SELL"):
        return {"ok": False, "reason": "Activo u orden no permitidos."}
    a = _last.get(sym)
    if not a or not a.get("available") or "atr" not in a:
        return {"ok": False, "reason": "Aún no hay análisis de este activo."}
    if not a["open"]:
        return {"ok": False, "reason": "El mercado de este activo está cerrado."}
    if GRID:
        return _grid_trade(sym, action, a)
    blocked, ev = in_news_blackout()
    if blocked:
        return {"ok": False, "reason": f"Noticia de alto impacto: {ev}"}
    ok, why = can_open_trade(action, sym)
    if not ok:
        return {"ok": False, "reason": why}
    info, tick = mt5.symbol_info(sym), get_tick(sym)
    if info is None or tick is None:
        return {"ok": False, "reason": "Sin precio en este momento."}
    atr = a["atr"]
    if is_too_close_to_existing(action, (tick.bid + tick.ask) / 2, atr, sym):
        return {"ok": False, "reason": "Ya hay una posición en la misma dirección muy cerca de este precio."}
    ml = a.get("ml")
    if ml and not ml["ok"]:
        return {"ok": False, "reason": f"El filtro predictivo estima P(éxito) {ml['p']:.0%}, "
                                       f"por debajo de su umbral {ml['tau']:.0%}."}
    px = tick.ask if action == "BUY" else tick.bid
    sl, tp = calculate_sl_tp(action, px, atr, info, ml and ml["sl_mult"], ml and ml["tp_mult"])
    min_rr = ml["tp_mult"] / ml["sl_mult"] * 0.9 if ml else None
    rr_ok, rr = check_risk_reward(px, sl, tp, min_rr)
    if not rr_ok:
        return {"ok": False, "reason": f"R:R real {rr:.2f} menor al mínimo {min_rr or config.MIN_RR:.2f}."}
    dist = abs(px - sl)
    if not spread_ok(tick.ask - tick.bid, dist):
        return {"ok": False, "reason": "El spread es demasiado alto frente al stop (más del 25%)."}
    acc = get_account_info()
    if acc and over_min_lot_cap(acc, info, dist):           # cuenta pequeña: SL/TP más cercanos, mismo R:R
        fit = fit_sl_to_capital(action, px, sl, tp, acc, info, atr)
        if fit and spread_ok(tick.ask - tick.bid, abs(px - fit[0])):
            sl, tp = fit
            dist = abs(px - sl)
    lot = calculate_lot(acc, info, dist) if acc else 0.0
    if lot <= 0:
        need = lot_plan(acc, info, dist)[1] if acc else None
        extra = f" Necesitas un capital de al menos {need:,.2f} {acc.currency}." if need else ""
        cap = getattr(config, "MAX_RISK_MIN_LOT", 0.05)
        return {"ok": False, "reason": f"Ni el lote mínimo cabe: arriesgaría más del {cap*100:.0f}% "
                                       f"de tu capital.{extra}"}
    ticket = open_trade(action, sl, tp, lot, info, comment=f"web {PROFILE}", symbol=sym)
    if not ticket:
        return {"ok": False, "reason": f"MT5 rechazó la orden: {mt5.last_error()}"}
    return {"ok": True, "ticket": ticket, "symbol": sym, "action": action, "lot": lot,
            "price": round(px, info.digits), "sl": sl, "tp": tp,
            "risk_usd": round(dist / info.trade_tick_size * _tick_value(info) * lot, 2),
            "risk_pct": round(lot_risk_pct(acc, info, dist, lot) * 100, 2)}


def _grid_trade(sym: str, action: str, a: dict) -> dict:
    """Abre una cesta del grid con las compuertas del motor (noticias, riesgo, spread)."""
    info, tick = mt5.symbol_info(sym), get_tick(sym)
    if info is None or tick is None:
        return {"ok": False, "reason": "Sin precio en este momento."}
    gatr = (a.get("grid") or {}).get("atr")
    if not gatr:
        return {"ok": False, "reason": "Sin ATR del TF de ejecución del grid."}
    r = grid.try_open_basket(action, tick, gatr, info, sym)
    if not r["ok"]:
        return r
    lv0, acc = r["levels"][0], get_account_info()
    return {"ok": True, "ticket": r["ticket"], "symbol": sym, "action": action, "lot": lv0["lot"],
            "price": lv0["price"], "sl": r["sl"], "tp": lv0["tp"], "levels": len(r["levels"]),
            "risk_usd": round(r["risk_usd"], 2),
            "risk_pct": round(r["risk_usd"] / min(acc.balance, acc.equity) * 100, 2) if acc else None}


# ═══════════════════════════════════════════════════════════════════════════════
# BUCLE
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    if not connect(retries=2, delay=3):
        send({"type": "fatal", "error": "No se pudo conectar a MT5 o la cuenta no es DEMO "
                                        "(revisa el terminal y ALLOW_LIVE_TRADING)."})
        return
    send({"type": "hello", "profile": PROFILE, "mode": MODE, "label": config.MODE_LABEL, "tfs": config.TF_LABELS,
          "sections": config.SECTIONS, "threshold": config.MIN_SIGNAL_SCORE})
    # Cargar los modelos ANTES de arrancar el hilo que lee stdin: en Windows, importar scikit-learn
    # mientras otro hilo está bloqueado leyendo sys.stdin se queda colgado (comparten su candado).
    for sym in SYMBOLS:
        bundle = ml_filter.bundle_for(sym)
        if bundle:
            ml_filter.probability(bundle, [0.0] * len(ml_filter.FEATURE_NAMES))   # calienta imports perezosos
    threading.Thread(target=_read_stdin, args=(_queue,), daemon=True).start()
    next_run = 0.0
    while not _state["exit"]:
        if time.time() >= next_run:
            send({"type": "analysis", "data": analyze_all()})
            next_run = time.time() + REFRESH_SECS
        try:
            _handle(_queue.get(timeout=max(0.1, next_run - time.time())))
        except queue.Empty:
            continue
    mt5.shutdown()


def _handle(msg: dict):
    """Atiende un mensaje del servidor. Una orden que llegó tarde NO se ejecuta: el servidor ya
    respondió "sin respuesta" al usuario y abrirla después sería una operación que nadie vio."""
    if msg.get("type") == "exit":
        _state["exit"] = True
    elif msg.get("type") == "trade":
        if time.time() - float(msg.get("ts") or 0) > TRADE_MAX_AGE:
            res = {"ok": False, "reason": "La orden llegó tarde porque el análisis estaba ocupado; "
                                          "no se envió. Inténtalo de nuevo."}
        else:
            try:
                res = trade(str(msg.get("symbol", "")), str(msg.get("action", "")))
            except Exception as exc:
                res = {"ok": False, "reason": f"Error interno: {exc}"}
        send({"type": "trade_result", "id": msg.get("id"), **res})


def _serve_pending():
    """Atiende las órdenes en cola sin esperar a que termine el análisis de todos los activos."""
    while not _state["exit"]:
        try:
            _handle(_queue.get_nowait())
        except queue.Empty:
            return


if __name__ == "__main__":
    main()
