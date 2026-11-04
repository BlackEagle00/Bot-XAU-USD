"""Solo lectura: resultado real de las LECTURAS DISCRECIONALES (punto 10 de los reportes) ya activadas.
Lee logs/discrecional.jsonl (una línea por disparador activado, hora LOCAL) y recorre velas M1 del bróker:
entrada al cierre de la vela de activación, SL/TP fijos (si una vela toca ambos cuenta SL), P&L por 0.01 lote
con comisión 0.06. No abre órdenes.
Formato: {"rep": 112, "act": "2026-11-02 19:45", "side": "BUY", "entry": 3951.89, "sl": 3947.0, "tp": 3958.0, "nota": "..."}"""
import json
import math
import time
from datetime import datetime

import MetaTrader5 as m

SYM, PT = "XAUUSD-ECN", 0.01
_R = r"C:\Users\Andrés Bonilla\Documents\ProyectosClaude\Proyecto Bot XAUUSD Git\Bot-XAU-USD"


def walk(buy, e, sl, tp, bars):
    """bars = [(t, high, low)] ya en el lado de salida (BID para BUY, ASK para SELL). → (res, t, pnl) o None."""
    d = 1 if buy else -1
    for t, h, lo in bars:
        if (lo <= sl) if buy else (h >= sl):
            return "SL", t, (sl - e) * d - 0.06
        if (h >= tp) if buy else (lo <= tp):
            return "TP", t, (tp - e) * d - 0.06
    return None


assert walk(False, 100.0, 103.0, 95.0, [(0, 102.0, 99.0), (60, 101.0, 94.9)])[0] == "TP"
assert walk(True, 100.0, 97.0, 106.0, [(0, 107.0, 96.0)])[0] == "SL"        # toca ambos → SL

rows = []
with open(_R + r"\logs\discrecional.jsonl", encoding="utf-8") as f:
    for ln in f:
        try:
            r = json.loads(ln)
            assert r["side"] in ("BUY", "SELL") and all(isinstance(r[k], (int, float)) for k in ("entry", "sl", "tp"))
            rows.append(r)
        except (ValueError, KeyError, AssertionError):
            print(f"línea inválida ignorada: {ln[:60]!r}")

m.initialize()
tick = m.symbol_info_tick(SYM)
off = math.ceil((tick.time - time.time()) / 3600 - 0.05) * 3600   # shortcut: mismo cálculo que report_extra (falla en fin de semana)
loc = lambda t: datetime.fromtimestamp(int(t) - off).strftime("%m-%d %H:%M")
tot, n, wins = 0.0, 0, 0
for r in rows:
    buy = r["side"] == "BUY"
    t0 = int(datetime.strptime(r["act"], "%Y-%m-%d %H:%M").timestamp()) + off + 60   # entra al cierre de la vela de activación
    x = m.copy_rates_range(SYM, m.TIMEFRAME_M1, t0, tick.time + 60)
    sp = (lambda b: 0.0) if buy else (lambda b: b["spread"] * PT)
    res = walk(buy, r["entry"], r["sl"], r["tp"], [(int(b["time"]), b["high"] + sp(b), b["low"] + sp(b)) for b in x])
    head = f"R{r['rep']} {r['act'][5:]} {r['side']:<4} entrada {r['entry']:.2f} SL {r['sl']:.2f} TP {r['tp']:.2f}"
    if res:
        tot, n, wins = tot + res[2], n + 1, wins + (res[2] > 0)
        print(f"{head} → {res[0]} {loc(res[1])}: {res[2]:+.2f} USD/0.01")
    else:
        flo = ((tick.bid - r["entry"]) if buy else (r["entry"] - tick.ask)) - 0.06
        print(f"{head} → ABIERTA {flo:+.2f} USD/0.01")
print(f"DISCRECIONAL: {n} cerradas, {wins} ganadoras, total {tot:+.2f} USD por 0.01 lote "
      f"({tot * 5:+.2f} con 0.05) | {len(rows) - n} abiertas")
m.shutdown()
