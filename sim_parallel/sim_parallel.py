"""
Sombra Balance × Bróker del bot de Scalping (pedido del usuario 2026-10-28: "Shadow Trading … sin tocar el balance
real de la cuenta ni abrir órdenes reales"). Proceso APARTE del bot real; las funciones de órdenes de MT5 quedan
anuladas en este proceso y solo se leen ticks y velas.

Feed: los eventos "signal" del diario del bot (xauusd_scalping_bot/journal.jsonl). Si el bot rechazó la señal por un
filtro que no depende del capital ni del bróker (🌡 🌪 📰 🧭 🧠), todas las combinaciones la marcan BLOQUEADA_BOT; si no,
cada combinación (balance hipotético × perfil de bróker) aplica su propio spread, la guarda de spread al enviar, el lote
de risk_manager.lot_plan (1 % + tope duro 15 %) y sigue la operación en velas M1 hasta SL / TP / tiempo.

Uso:
    python run.py sim_parallel                       # en vivo (bucle cada 5 s)
    python sim_parallel/sim_parallel.py --since 2026-10-28T16:00:00+00:00 --once   # repetir señales pasadas y salir
"""
import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "xauusd_scalping_bot"
OUT = ROOT / "logs" / "sim_parallel"
DOC = ROOT / "docs" / "SIM_COMP_2026-10.md"
PROFILES = Path(__file__).with_name("brokers_profile.json")
BALANCES = (67.77, 100, 500, 1000, 5000)           # 67.77 = balance real del usuario (2026-10-29)
TRACKS = ("", "VETO|")                             # "" = señales del bot; "VETO|" = vetadas por ⛔ ADX/tendencia
BOT_GATES = ("🌡", "🌪", "📰", "🧭", "🧠")          # filtros del bot iguales para todo capital y bróker
STATES = ("EJECUTADA", "TRADE_REJECTED", "SIGNAL_BLOCKED", "BLOQUEADA_BOT", "OCUPADA")
sys.path[:0] = [str(BOT), str(ROOT)]

import MetaTrader5 as mt5  # noqa: E402


def _no_orders(*a, **k):
    raise RuntimeError("SIM: órdenes anuladas en sim_parallel")


for _f in ("order_send", "order_check", "order_send_async", "positions_get"):
    setattr(mt5, _f, _no_orders)                    # riesgo cero: este proceso no puede operar ni leer posiciones

OUT.mkdir(parents=True, exist_ok=True)
import config  # noqa: E402
BOT_LOG = BOT / Path(config.LOG_FILE).name               # log del bot: fuente de los vetos ⛔
config.LOG_FILE = str(OUT / "sim_parallel.log")     # el logger del motor escribe aquí, nunca en el log del bot real
from bot_engine import risk_manager as rm  # noqa: E402
from bot_engine.indicators import anomalous_bars  # noqa: E402
from bot_engine.logger_config import logger  # noqa: E402


# ── Decisión y recorrido (puros: se prueban sin MT5) ─────────────────────────
def decide(balance: float, prof: dict, side: str, bid: float, ask: float, atr: float, sym, free: bool = False) -> dict:
    """Guardas que dependen del bróker y del capital, en el orden del bot real (spread al enviar → SL/TP → lote).
    free=True (pista VETO, pedido del usuario "déjalo libre totalmente"): sin tope del 15 %, lote mínimo si no cabe."""
    sp = (ask - bid) * prof.get("spread_multiplier", 1.0) + prof.get("fixed_spread_offset_points", 0.0) * sym.point
    pts = sp / sym.point
    if pts >= config.MAX_SPREAD_POINTS:
        return {"estado": "SIGNAL_BLOCKED", "motivo": f"Spread abuse detected ({pts:.0f} pts ≥ {config.MAX_SPREAD_POINTS})",
                "entry": None, "lot": 0.0, "sp": sp}
    entry = bid + sp if side == "BUY" else bid
    sl, tp = rm.calculate_sl_tp(side, entry, atr, sym)
    if not rm.spread_ok(sp, abs(entry - sl)):
        return {"estado": "SIGNAL_BLOCKED", "motivo": f"spread {sp:.2f} > 25 % del stop", "entry": entry, "lot": 0.0, "sp": sp}
    lot = rm.lot_plan(NS(balance=balance, equity=balance), sym, abs(entry - sl))[0]
    lot = lot if lot > 0 or not free else sym.volume_min
    if lot <= 0:
        cap = getattr(config, "MAX_RISK_MIN_LOT", rm.MAX_RISK_MIN_LOT)
        return {"estado": "TRADE_REJECTED", "entry": entry, "lot": 0.0, "sp": sp,
                "motivo": f"Account balance insufficient for technical SL under {cap:.0%} risk rule (SL {abs(entry - sl):.2f})"}
    return {"estado": "EJECUTADA", "motivo": "", "entry": entry, "sl": sl, "tp": tp, "lot": lot, "sp": sp}


def walk(pos: dict, bars, point: float, prof: dict, hold_s: float):
    """bars: (t_apertura, high, low, close, spread_pts) en orden. BUY sale por BID; SELL por ASK simulado.
    Si una vela toca SL y TP cuenta SL. Devuelve (precio, motivo, t) o None si sigue abierta."""
    buy = pos["side"] == "BUY"
    for t, h, low, c, sp_pts in bars:
        add = 0.0 if buy else (sp_pts * prof.get("spread_multiplier", 1.0) + prof.get("fixed_spread_offset_points", 0.0)) * point
        hi, lo = h + add, low + add
        if (lo <= pos["sl"]) if buy else (hi >= pos["sl"]):
            return pos["sl"], "SL", t
        if (hi >= pos["tp"]) if buy else (lo <= pos["tp"]):
            return pos["tp"], "TP", t
        if t + 60 - pos["t0"] >= hold_s:
            return c + add, "TIEMPO", t
    return None


def new_combo(balance: float) -> dict:
    return {"start": balance, "balance": balance, "open": [], "trades": 0, "wins": 0, "gross_win": 0.0,
            "gross_loss": 0.0, "commission": 0.0, "counts": {s: 0 for s in STATES}}


# ── Reporte ───────────────────────────────────────────────────────────────────
def write_section(tag: str, body: str) -> None:
    """Reemplaza solo la sección <!-- tag --> … <!-- /tag --> de docs/SIM_COMP_2026-10.md (vivo e histórico conviven)."""
    head = "# Comparativa Balance × Bróker (simulación, NO operaciones reales)\n\n"
    s = DOC.read_text(encoding="utf-8") if DOC.exists() else head
    a, b = f"<!-- {tag} -->", f"<!-- /{tag} -->"
    block = f"{a}\n{body.rstrip()}\n{b}"
    s = s[:s.index(a)] + block + s[s.index(b) + len(b):] if a in s and b in s else s.rstrip() + "\n\n" + block + "\n"
    DOC.write_text(s, encoding="utf-8")


def live_report(state: dict, profiles: list, since: str = None) -> None:
    rows = [f"## Repetición de señales desde {since} UTC" if since else "## Sombra en vivo", "",
            f"Actualizado {datetime.now():%Y-%m-%d %H:%M} (hora local). Señales leídas: {len(state['seen'])}. "
            "Lote: regla del bot (1 % + tope duro 15 %). Sin break-even ni trailing. Pista de vetos: LIBRE (sin tope 15 %, lote mínimo si no cabe, varias posiciones a la vez)."]
    for track, title in (("", "Señales del bot (diario)"),
                         ("VETO|", "Señales vetadas por ⛔ ADX/tendencia, si se hubieran operado (sin 🌡/🌪/📰)")):
        rows += ["", f"### {title}", "",
                 "| Balance | Bróker | Ops | Acierto | Neto USD | Neto % | PF | Comisión | TRADE_REJECTED | SIGNAL_BLOCKED "
                 "| BLOQUEADA_BOT | OCUPADA | Abierta |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for b in BALANCES:
            for p in profiles:
                c = state["combos"][f"{track}{b}|{p['name']}"]
                net = c["balance"] - c["start"]
                pf = c["gross_win"] / c["gross_loss"] if c["gross_loss"] else (float("inf") if c["gross_win"] else 0.0)
                k = c["counts"]
                rows.append(f"| {b:,} | {p['name']} | {c['trades']} | {(c['wins'] / c['trades'] * 100 if c['trades'] else 0):.0f} % "
                            f"| {net:+.2f} | {net / c['start'] * 100:+.2f} % | {pf:.2f} | {c['commission']:.2f} "
                            f"| {k['TRADE_REJECTED']} | {k['SIGNAL_BLOCKED']} | {k['BLOQUEADA_BOT']} | {k['OCUPADA']} "
                            f"| {len(c['open'])} |")
    write_section("REPLAY" if since else "LIVE", "\n".join(rows))


# ── Bucle en vivo ─────────────────────────────────────────────────────────────
def server_offset() -> int:
    """Segundos entre la hora del servidor (epoch de MT5) y la real. shortcut: tick viejo < 57 min (pausa diaria)."""
    tick = mt5.symbol_info_tick(config.SYMBOL)
    return math.ceil((tick.time - time.time()) / 3600 - 0.05) * 3600


def read_journal(path: Path, pos: int):
    """Eventos nuevos desde el byte pos → (signals, rechazos por id, autorizados, nueva pos)."""
    sigs, rej, auth = [], {}, set()
    with open(path, "rb") as f:
        f.seek(pos)
        for raw in f:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if e.get("event") == "signal":
                sigs.append(e)
            elif e.get("event") == "rejected" and e.get("id"):
                rej.setdefault(e["id"], e.get("reason", ""))
            elif e.get("event") == "authorized":
                auth.add(e.get("id"))
        pos = f.tell()
    return sigs, rej, auth, pos


VETO_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\].*📊.*Score:\s*([-+\d.]+).*ATR: ([\d.]+).*⛔ (BUY|SELL) bloqueado: ([^(|]+)")


def read_vetoes(path: Path, pos: int, window_min: int):
    """Líneas 📊 con veto ⛔ del log del bot desde el byte pos → (pseudo-señales, nueva pos). Solo la primera de cada
    vela M15 dentro de la ventana de entrada (los primeros window_min minutos), como decidiría el bot real."""
    out, bars = [], set()
    with open(path, "rb") as f:
        f.seek(pos if pos <= path.stat().st_size else 0)   # el log rotó: empezar de nuevo (seen evita duplicados)
        for raw in f:
            m = VETO_RE.match(raw.decode("utf-8", "replace"))
            if not m:
                continue
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")            # hora local del log
            if t.minute % 15 >= window_min:
                continue
            bar = t.replace(minute=t.minute - t.minute % 15, second=0)
            if bar in bars:
                continue
            bars.add(bar)
            out.append({"id": f"VETO-{bar:%Y%m%d%H%M}", "action": m.group(4), "score": float(m.group(2)),
                        "atr": float(m.group(3)), "ts": t.astimezone(timezone.utc).isoformat(),
                        "veto": "⛔ " + m.group(5).strip()})
        pos = f.tell()
    return out, pos


def tag(b, name, track=""):
    return f"{'[VETO]' if track else ''}[SIM_B-{b}][BROKER-{name}]"


def process_signal(e: dict, rej: dict, auth: set, state: dict, profiles: list, sym, off: int, track: str = "") -> None:
    sid, side, atr = e["id"], e["action"], float(e["atr"])
    t_real = datetime.fromisoformat(e["ts"]).timestamp()
    reason = e.get("veto") or rej.get(sid, "")
    bot_block = not track and sid not in auth and reason[:1] in BOT_GATES
    m1 = mt5.copy_rates_range(config.SYMBOL, mt5.TIMEFRAME_M1, int(t_real + off) - 60 * 52, int(t_real + off))
    anom = bool(m1 is not None and len(m1) > 21 and anomalous_bars(m1["high"], m1["low"], config.ANOMALY_RANGE_MULT,
                                                                    config.ANOMALY_LOOKBACK)[-30:].any())
    logger.info(f"📡 Señal {sid} {side} score {e.get('score')} ATR {atr:.2f}"
                + (f" | bot: {reason}" if reason else "") + (" | ⚡ vela M1 anómala en 30 min" if anom else ""))
    for p in profiles:
        t_srv = t_real + off + p.get("execution_delay_ms", 0) / 1000
        ticks = mt5.copy_ticks_range(config.SYMBOL, int(t_srv), int(t_srv) + 5, mt5.COPY_TICKS_ALL)
        ticks = [x for x in (ticks if ticks is not None else []) if x["time_msc"] >= t_srv * 1000]
        for b in BALANCES:
            c = state["combos"][f"{track}{b}|{p['name']}"]
            if bot_block:
                d = {"estado": "BLOQUEADA_BOT", "motivo": reason, "entry": None, "lot": 0.0}
            elif c["open"] and not track:                 # pista VETO: sin límite de posiciones a la vez
                d = {"estado": "OCUPADA", "motivo": "ya hay una posición simulada (1 a la vez)", "entry": None, "lot": 0.0}
            elif not ticks:
                logger.warning(f"{tag(b, p['name'], track)} | sin tick tras {p.get('execution_delay_ms', 0)} ms: señal omitida")
                continue
            else:
                d = decide(c["balance"], p, side, float(ticks[0]["bid"]), float(ticks[0]["ask"]), atr, sym, bool(track))
            c["counts"][d["estado"]] += 1
            ent = f"{d['entry']:.2f}" if d["entry"] else "-"
            extra = f" | SL {d['sl']:.2f} TP {d['tp']:.2f}" if d["estado"] == "EJECUTADA" else f" | {d['motivo']}"
            logger.info(f"{tag(b, p['name'], track)} | ENTRADA: {ent} | LOTE: {d['lot']:.2f} | ESTADO: {d['estado']}{extra}")
            if d["estado"] == "EJECUTADA":
                c["open"].append({"id": sid, "side": side, "entry": d["entry"], "sl": d["sl"], "tp": d["tp"],
                                  "lot": d["lot"], "t0": float(ticks[0]["time_msc"]) / 1000})


def update_open(state: dict, profiles: list, sym, vpu: float, now_srv: float) -> bool:
    hold_s = getattr(config, "MAX_HOLD_MINUTES", 120) * 60
    closed = False
    for track, p, b in ((t, p, b) for t in TRACKS for p in profiles for b in BALANCES):
        c = state["combos"][f"{track}{b}|{p['name']}"]
        for pos in list(c["open"]):
            t0, m0 = pos["t0"], int(pos["t0"]) - int(pos["t0"]) % 60 + 60
            tk = mt5.copy_ticks_range(config.SYMBOL, int(t0), m0, mt5.COPY_TICKS_ALL)
            bars = [(t0, float(tk["bid"].max()), float(tk["bid"].min()), float(tk["bid"][-1]),
                     (tk["ask"][-1] - tk["bid"][-1]) / sym.point)] if tk is not None and len(tk) else []
            r = mt5.copy_rates_range(config.SYMBOL, mt5.TIMEFRAME_M1, m0, int(now_srv))
            bars += [(int(x["time"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x["spread"]))
                     for x in (r if r is not None else []) if int(x["time"]) + 60 <= now_srv]   # solo velas cerradas
            out = walk(pos, bars, sym.point, p, hold_s)
            if not out:
                continue
            px, why, _ = out
            comm = p.get("commission_per_lot", 0.0) * pos["lot"]
            pnl = ((px - pos["entry"]) if pos["side"] == "BUY" else (pos["entry"] - px)) * vpu * pos["lot"] - comm
            c["balance"] += pnl
            c["trades"] += 1
            c["wins"] += pnl > 0
            c["gross_win" if pnl > 0 else "gross_loss"] += abs(pnl)
            c["commission"] += comm
            c["open"].remove(pos)
            closed = True
            logger.info(f"{tag(b, p['name'], track)} | CIERRE {why}: {px:.2f} | LOTE: {pos['lot']:.2f} | P&L {pnl:+.2f} USD "
                        f"(comisión {comm:.2f}) | balance simulado {c['balance']:.2f}")
    return closed


def main():
    ap = argparse.ArgumentParser(description="Sombra Balance × Bróker (sin órdenes reales)")
    ap.add_argument("--since", default=None, help="ISO UTC: procesar señales del diario desde aquí (repetición)")
    ap.add_argument("--once", action="store_true", help="procesar lo pendiente y salir")
    a = ap.parse_args()
    from bot_engine.symbols import resolve_symbol
    if not mt5.initialize():
        sys.exit(f"MT5 no disponible: {mt5.last_error()}")
    config.SYMBOL = resolve_symbol(config.SYMBOL, getattr(config, "SYMBOL_ALIASES", ()))
    info = mt5.symbol_info(config.SYMBOL)
    sym = NS(point=info.point, digits=info.digits, trade_stops_level=info.trade_stops_level, name=info.name,
             trade_tick_size=info.trade_tick_size, trade_tick_value=info.trade_tick_value, volume_step=info.volume_step,
             volume_min=info.volume_min, volume_max=info.volume_max, bid=info.bid, ask=info.ask)
    ref = info.bid or 4000.0
    vpu = abs(mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, config.SYMBOL, 1.0, ref, ref + 1.0) or 0) or 100.0
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
    state_path = OUT / ("state_replay.json" if a.since else "state.json")
    journal_path = BOT / "journal.jsonl"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() and not a.since else \
        {"pos": 0 if a.since else journal_path.stat().st_size, "seen": [], "combos": {}}
    log_path = BOT_LOG
    state.setdefault("vpos", 0 if a.since else log_path.stat().st_size)
    for t in TRACKS:
        for b in BALANCES:
            for p in profiles:
                c = state["combos"].setdefault(f"{t}{b}|{p['name']}", new_combo(b))
                c["open"] = [c["open"]] if isinstance(c["open"], dict) else c["open"] or []   # estado viejo: 1 posición
    logger.info(f"🧪 sim_parallel {'REPETICIÓN desde ' + a.since if a.since else 'EN VIVO'} | {config.SYMBOL} | "
                f"balances {BALANCES} | brókers {[p['name'] for p in profiles]} | órdenes ANULADAS")
    wait_all = max(p.get("execution_delay_ms", 0) for p in profiles) / 1000 + 6
    while True:
        off = server_offset()
        sigs, rej, auth, new_pos = read_journal(journal_path, state["pos"])
        ready = []
        for e in sigs:
            t = datetime.fromisoformat(e["ts"])
            if a.since and t < datetime.fromisoformat(a.since):
                continue
            wait = max(p.get("execution_delay_ms", 0) for p in profiles) / 1000 + 6
            if time.time() < t.timestamp() + wait:                 # esperar el retraso y los rechazos del bot
                new_pos = None
                break
            if e["id"] not in state["seen"]:
                ready.append(e)
        for e in ready:                                            # cerrar lo que ya tocó SL/TP antes de esta señal
            update_open(state, profiles, sym, vpu, datetime.fromisoformat(e["ts"]).timestamp() + off)
            process_signal(e, rej, auth, state, profiles, sym, off)
            state["seen"].append(e["id"])
        if new_pos is not None:
            state["pos"] = new_pos
        vetoes, vpos = read_vetoes(log_path, state["vpos"], getattr(config, "ENTRY_WINDOW_MIN", 5))
        vready = []
        for e in vetoes:
            if time.time() < datetime.fromisoformat(e["ts"]).timestamp() + wait_all:
                vpos = None                                        # releer: el retraso del bróker aún no pasó
                break
            if e["id"] not in state["seen"]:
                vready.append(e)
        for e in vready:
            update_open(state, profiles, sym, vpu, datetime.fromisoformat(e["ts"]).timestamp() + off)
            process_signal(e, {}, set(), state, profiles, sym, off, "VETO|")
            state["seen"].append(e["id"])
        if vpos is not None:
            state["vpos"] = vpos
        ready += vready
        if update_open(state, profiles, sym, vpu, time.time() + off) or ready:
            live_report(state, profiles, a.since)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        if a.once:
            break
        time.sleep(5)
    live_report(state, profiles, a.since)
    mt5.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
