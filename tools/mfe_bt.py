"""Solo lectura: avance máximo a favor (MFE) de las señales del backtest (caché 3 años), por grupo de filtro.
Barrera pura como las hipotéticas en vivo (sin BE/trailing): entrada a la apertura siguiente (BUY +spread),
SL 1.5×ATR / TP 3×ATR, SL primero si una vela toca ambos, cierre por tiempo a los 120 min (8 velas M15)."""
import sys
import numpy as np, pandas as pd
R = r"C:\Users\Andrés Bonilla\Documents\ProyectosClaude\Proyecto Bot XAUUSD Git\Bot-XAU-USD"
sys.path[:0] = [R + r"\xauusd_scalping_bot", R]
from bot_engine.indicators import regime_labels   # noqa: E402
D = R + r"\backtesting\data\\"
sig = pd.read_pickle(D + "signals_v3_xauusd_scalping_bot_XAUUSD-ECN_M15_MAX_OPEN_TRADES-1_MIN_SIGNAL_SCORE-6.5_20231029_20261029_faa5212418.pkl.gz")
p = pd.read_csv(D + "XAUUSD-ECN_M15_20231004_20261029.csv.gz")
o, h, l, c = (p[k].to_numpy(float) for k in ("open", "high", "low", "close"))
sp = p["spread"].to_numpy(float) * 0.01          # shortcut: spread mínimo de la vela, no el real por hora
reg = regime_labels(p, 18)
HOLD, BAL = 8, 67.77
thr = (0.15 * BAL - 0.06) / 1.5

def walk(i, buy, a):
    k = i + 1
    e = o[k] + (sp[k] if buy else 0)
    sl, tp = (e - 1.5 * a, e + 3 * a) if buy else (e + 1.5 * a, e - 3 * a)
    best, early = 0.0, 0.0
    for j in range(k, min(k + HOLD, len(o))):
        ah, al = h[j] + sp[j], l[j] + sp[j]                          # ask de la vela (SELL sale por ask)
        fav = (h[j] - e) if buy else (e - al)
        if (l[j] <= sl) if buy else (ah >= sl):
            return best / (3 * a), early / (3 * a), "SL"
        best = max(best, fav)
        if j < k + 2:
            early = best
        if (h[j] >= tp) if buy else (al <= tp):
            return 1.0, early / (3 * a), "TP"
    return best / (3 * a), early / (3 * a), "TIEMPO"

ev = sig[sig.action.isin(["BUY", "SELL"])]
rows = []
for i, act, a in zip(ev.i, ev.action, pd.to_numeric(ev.atr)):
    if i + 1 >= len(o) or not a == a:
        continue
    m, m2, res = walk(int(i), act == "BUY", float(a))
    r = str(reg[int(i) + 1])
    g = ("🌡 régimen tendencia/baja" if r == "tendencia/baja" else "🌪 ATR > 7.5" if a > 7.5
         else f"ATR {thr:.1f}–7.5 (TRADE_REJECTED)" if a > thr else f"PASA todo (ATR ≤ {thr:.1f})")
    rows.append((g, m, m2, res))
df = pd.DataFrame(rows, columns=["g", "mfe", "mfe2", "res"])
assert df.mfe.between(0, 1).all()
def line(name, x):
    print(f"{name:<34} n={len(x):>5} | mediana MFE {100*x.mfe.median():3.0f} % | <10 %: {100*(x.mfe<.10).mean():3.0f} % | "
          f"≥55 % (BE): {100*(x.mfe>=.55).mean():3.0f} % | TP {100*(x.res=='TP').mean():3.0f} % SL {100*(x.res=='SL').mean():3.0f} % "
          f"tiempo {100*(x.res=='TIEMPO').mean():3.0f} % | MFE 1as 2 velas mediana {100*x.mfe2.median():3.0f} %")
line("TODAS", df)
for g, x in df.groupby("g"):
    line(g, x)
