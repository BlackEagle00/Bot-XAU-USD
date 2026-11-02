"""Solo lectura: backtest del módulo de rango (ADX M15 < 18) — ruptura falsa de un número redondo (múltiplo de 10)
o del extremo de las 2 h previas que cierra de vuelta dentro. Entrada a la apertura siguiente (BUY +spread, SELL sale
por ask), SL más allá del extremo de la ruptura, SL primero si una vela toca ambos, cierre por tiempo a los 120 min,
1 posición a la vez, comisión 0.06 por 0.01 lote. Filtros reales: ATR ≤ 7.5 y riesgo ≤ 15 % del balance.
Elige la variante en muestra (2/3 iniciales) y reporta fuera de muestra (1/3 final). Uso: python tools/range_bt.py [M15|M5]"""
import sys
import numpy as np, pandas as pd
R = r"C:\Users\Andrés Bonilla\Documents\ProyectosClaude\Proyecto Bot XAUUSD Git\Bot-XAU-USD"
sys.path[:0] = [R + r"\xauusd_scalping_bot", R]
from bot_engine.indicators import calc_adx, calc_atr   # noqa: E402
D = R + r"\backtesting\data\\"
TF = sys.argv[1] if len(sys.argv) > 1 else "M15"
FILES = {"M15": "XAUUSD-ECN_M15_20231004_20261029.csv.gz", "M5": "XAUUSD-ECN_M5_20231024_20261027.csv.gz"}
MIN = {"M15": 15, "M5": 5}[TF]
K, N, HOLD = {"M15": 2, "M5": 3}[TF], 120 // MIN, 120 // MIN   # velas de la ruptura, rango previo 2 h, tope 120 min
BAL, COMM, ADX_MAX, ATR_MAX = 79.55, 0.06, 18, 7.5

m15 = pd.read_csv(D + FILES["M15"])
m15["adx"], m15["atr"], m15["ct15"] = calc_adx(m15.high, m15.low, m15.close), calc_atr(m15.high, m15.low, m15.close), m15.time + 900
p = pd.read_csv(D + FILES[TF])
p["ct"] = p.time + MIN * 60
# solo la última vela M15 ya cerrada al cierre de esta vela: sin mirar el futuro
p = pd.merge_asof(p.sort_values("ct"), m15[["ct15", "adx", "atr"]], left_on="ct", right_on="ct15", direction="backward")
o, h, l, c = (p[k].to_numpy(float) for k in ("open", "high", "low", "close"))
sp, adx, atr, t = p.spread.to_numpy(float) * 0.01, p.adx.to_numpy(float), p.atr.to_numpy(float), p.time.to_numpy()


def signals(kind):
    out = []
    for i in range(N + K + 1, len(c) - 1):
        a = atr[i]
        if not (adx[i] < ADX_MAX and a == a):
            continue
        lo, hi = l[i - K + 1:i + 1].min(), h[i - K + 1:i + 1].max()
        for buy in (True, False):
            if kind == "redondo":
                L = np.floor(c[i] / 10) * 10 if buy else np.ceil(c[i] / 10) * 10
            else:
                L = l[i - K - N:i - K].min() if buy else h[i - K - N:i - K].max()
            pierce = 0.05 * a
            ok = (lo < L - pierce and c[i] > L and c[i - K] > L and (c[i - 1] <= L or l[i] < L)) if buy else \
                 (hi > L + pierce and c[i] < L and c[i - K] < L and (c[i - 1] >= L or h[i] > L))
            if ok:
                out.append((i, buy, (lo if buy else hi), a))
    return out


def walk(i, buy, ext, a, rr):
    k = i + 1
    e = o[k] + (sp[k] if buy else 0)
    buf = 0.1 * a + sp[k]
    sl = ext - buf if buy else ext + buf
    risk = (e - sl) if buy else (sl - e)
    if not (0.25 * a <= risk <= 1.5 * a) or a > ATR_MAX or risk + COMM > 0.15 * BAL:
        return None
    tp = e + rr * risk if buy else e - rr * risk
    for j in range(k, min(k + HOLD, len(o))):
        ah, al = h[j] + sp[j], l[j] + sp[j]
        if (l[j] <= sl) if buy else (ah >= sl):
            return j, -risk - COMM, risk
        if (h[j] >= tp) if buy else (al <= tp):
            return j, rr * risk - COMM, risk
    x = c[j] if buy else c[j] + sp[j]
    return j, ((x - e) if buy else (e - x)) - COMM, risk


def run(sig, rr):
    rows, busy = [], -1
    for i, buy, ext, a in sig:
        if i <= busy:
            continue
        r = walk(i, buy, ext, a, rr)
        if r:
            busy = r[0]
            rows.append((t[i], buy, r[1], r[2]))
    return pd.DataFrame(rows, columns=["t", "buy", "pnl", "risk"])


def stats(d):
    if len(d) == 0:
        return "n=0"
    g, b = d.pnl[d.pnl > 0].sum(), -d.pnl[d.pnl < 0].sum()
    eq = d.pnl.cumsum()
    mo = d.groupby(pd.to_datetime(d.t, unit="s").dt.to_period("M")).pnl.sum()
    return (f"n={len(d):>4} acierto {100*(d.pnl>0).mean():3.0f}% PF {g/b if b else np.inf:4.2f} neto {d.pnl.sum():+8.2f} USD "
            f"exp {(d.pnl/d.risk).mean():+.2f}R DDmax {(eq.cummax()-eq).max():6.2f} meses+ {100*(mo>0).mean():3.0f}%")


cut = t[0] + (t[-1] - t[0]) * 2 / 3
print(f"{TF}: {pd.to_datetime(t[0], unit='s').date()} → {pd.to_datetime(t[-1], unit='s').date()} | corte muestra/fuera "
      f"{pd.to_datetime(cut, unit='s').date()} | 0.01 lote, balance {BAL}")
best = None
for kind in ("redondo", "rango2h"):
    sig = signals(kind)
    for rr in (1.0, 1.5, 2.0):
        d = run(sig, rr)
        assert d.risk.gt(0).all()
        ins, oos = d[d.t < cut], d[d.t >= cut]
        print(f"{kind:<8} TP {rr}R | EN MUESTRA {stats(ins)}\n{'':<17}| FUERA      {stats(oos)}")
        g, b = ins.pnl[ins.pnl > 0].sum(), -ins.pnl[ins.pnl < 0].sum()
        if len(ins) >= 30 and b and (best is None or g / b > best[0]):
            best = (g / b, kind, rr, oos)
if best:
    print(f"\nELEGIDA en muestra: {best[1]} TP {best[2]}R (PF muestra {best[0]:.2f}) → FUERA DE MUESTRA: {stats(best[3])}")
    print("Referencia: módulo actual de tendencia, PF fuera de muestra 1.12 (auditoría 2026-10-26).")
