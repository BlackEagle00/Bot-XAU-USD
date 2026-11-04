"""Solo lectura: reproduce las operaciones de la sombra (log de sim_parallel) con otros capitales iniciales.
Lote = risk_manager.lot_plan del capital simulado en cada entrada (como decide()); P&L lineal en el lote.
Autocomprobación: los capitales que la sombra ya simula deben salir igual que su state.json."""
import json, re, sys
from types import SimpleNamespace as NS
from pathlib import Path
R = str(Path(__file__).resolve().parents[1])   # raíz del repo (PC o VPS)
sys.path[:0] = [R + r"\xauusd_scalping_bot", R]
import config; config.LOG_FILE = R + r"\logs\sim_parallel\shadow_replay.log"   # nunca el log del bot
import MetaTrader5 as mt5
from bot_engine import risk_manager as rm
mt5.initialize(); sym = mt5.symbol_info("XAUUSD-ECN")
PRO = "VT_ACTUAL"; REF = 1000                      # pista de referencia (lote 0.01 casi siempre) para leer las operaciones
ENT = re.compile(r"^\[(.{19})\].*?(\[VETO\])?\[SIM_B-([\d.]+)\]\[BROKER-(\w+)\] \| ENTRADA: ([\d.]+) \| LOTE: ([\d.]+) \| ESTADO: EJECUTADA \| SL ([\d.]+) TP ([\d.]+)")
CIE = re.compile(r"^\[(.{19})\].*?(\[VETO\])?\[SIM_B-([\d.]+)\]\[BROKER-(\w+)\] \| CIERRE (\S+): ([\d.]+) \| LOTE: ([\d.]+) \| P&L ([-+\d.]+) USD \(comisión ([\d.]+)\)")

def events(track, b):
    """Operaciones (t_entrada, t_cierre, entrada, sl, dir, px_cierre, comisión/lote, motivo) de una pista del log."""
    ops, opn = [], []
    for line in open(R + r"\logs\sim_parallel\sim_parallel.log", encoding="utf-8", errors="replace"):
        m = ENT.match(line) or CIE.match(line)
        if not m or bool(m.group(2)) != (track == "VETO") or m.group(3) != b or m.group(4) != PRO:
            continue
        if m.re is ENT:
            e, sl = float(m.group(5)), float(m.group(7))
            opn.append({"t0": m.group(1), "e": e, "sl": sl, "d": -1 if sl > e else 1, "lot": float(m.group(6))})
        else:
            px, lot, pnl, com = float(m.group(6)), float(m.group(7)), float(m.group(8)), float(m.group(9))
            k = min(range(len(opn)), key=lambda i: abs((px - opn[i]["e"]) * opn[i]["d"] * 100 * lot - com - pnl)
                    + (0 if abs(opn[i]["lot"] - lot) < 1e-9 else 1e6))
            o = opn.pop(k); ops.append({**o, "t1": m.group(1), "px": px, "cpl": com / lot, "why": m.group(5)})
    return ops, opn

def replay(ops, opn, start, track):
    ev = sorted([(o["t0"], 0, i) for i, o in enumerate(ops)] + [(o["t1"], 1, i) for i, o in enumerate(ops)]
                + [(o["t0"], 0, len(ops) + i) for i, o in enumerate(opn)], key=lambda x: (x[0], -x[1]))
    allo = ops + opn; bal, lots, n, w = start, {}, 0, 0
    for _, kind, i in ev:
        o = allo[i]
        if kind == 0:
            lot = rm.lot_plan(NS(balance=bal, equity=bal), sym, abs(o["e"] - o["sl"]))[0]
            lots[i] = lot if lot > 0 or track != "VETO" else sym.volume_min
        elif lots.get(i):
            p = (o["px"] - o["e"]) * o["d"] * 100 * lots[i] - o["cpl"] * lots[i]
            bal += p; n += 1; w += p > 0
    return bal, n, w, [(allo[i]["e"], lots[i]) for i in range(len(ops), len(allo)) if lots.get(i)]

st = json.load(open(R + r"\logs\sim_parallel\state.json", encoding="utf-8"))["combos"]
for track in ("BOT", "VETO"):
    ops, opn = events(track, str(REF))
    print(f"== Pista {track}: {len(ops)} cerradas, {len(opn)} abiertas (leídas de la pista {REF})")
    for b in (67.77, 100, 144.68, 500, 750, 1000, 2000, 5000):
        bal, n, w, op = replay(ops, opn, b, track)
        key = f"{'VETO|' if track == 'VETO' else ''}{b}|{PRO}"
        ok = key not in st or b == 67.77 or abs(st[key]["balance"] - bal) < 0.01   # 67.77 tiene operaciones propias (tope 15 %)
        chk = (f" | state {st[key]['balance']:.2f}" if key in st else " | (nuevo)") + ("" if ok else " ⚠ NO COINCIDE")
        print(f"{b:>8}: {bal:9.2f} ({bal - b:+8.2f} USD, {100 * (bal - b) / b:+6.1f} %) {n} op., {w} gan.{chk} abiertas {op}")
