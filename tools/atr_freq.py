"""Solo lectura: % de velas M15 cerradas con ATR(14) <= umbral (tope 15 % con lote 0.01), por periodo, hora y día."""
import math, sys, time
import MetaTrader5 as m, pandas as pd
R = r"C:\Users\Andrés Bonilla\Documents\ProyectosClaude\Proyecto Bot XAUUSD Git\Bot-XAU-USD"
sys.path[:0] = [R + r"\xauusd_scalping_bot", R]
from bot_engine.indicators import calc_atr
m.initialize(); S = "XAUUSD-ECN"
tick = m.symbol_info_tick(S); off = math.ceil((tick.time - time.time()) / 3600 - 0.05) * 3600
bal = m.account_info().balance
d = pd.DataFrame(m.copy_rates_from_pos(S, m.TIMEFRAME_M15, 1, 99000)); m.shutdown()
d["atr"] = calc_atr(d.high, d.low, d.close)
d = d.dropna(); d["t"] = pd.to_datetime(d.time - off - time.timezone, unit="s")   # epoch real → hora local (sin DST)
thr = (0.15 * bal - 0.06) / 1.5
assert abs(1.5 * thr + 0.06 - 0.15 * bal) < 1e-9
print(f"balance {bal:.2f} → umbral ATR {thr:.2f} | datos {d.t.iloc[0]:%Y-%m-%d} → {d.t.iloc[-1]:%Y-%m-%d %H:%M} ({len(d)} velas)")
end = d.t.iloc[-1]
for name, days in (("todo", None), ("12 meses", 365), ("3 meses", 91), ("1 mes", 30), ("7 días", 7)):
    x = d if days is None else d[d.t >= end - pd.Timedelta(days=days)]
    print(f"{name:>9}: ATR≤{thr:.1f} {100*(x.atr<=thr).mean():5.1f} % | ≤7.5 {100*(x.atr<=7.5).mean():5.1f} % | mediana {x.atr.median():5.2f} | p25 {x.atr.quantile(.25):5.2f}")
y = d[d.t >= end - pd.Timedelta(days=91)]
h = y.groupby(y.t.dt.hour).atr.apply(lambda s: 100 * (s <= thr).mean())
print("3 meses, % por hora local:", " ".join(f"{k:02d}:{v:.0f}" for k, v in h.items()))
dd = d[d.t >= end - pd.Timedelta(days=14)]
g = dd.groupby(dd.t.dt.date).atr.agg(lambda s: 100 * (s <= thr).mean())
print("últimos 14 días, % por día:", " ".join(f"{k:%m-%d}:{v:.0f}" for k, v in g.items()))
for b in (60, 80, 104, 150):
    t2 = (0.15 * b - 0.06) / 1.5
    print(f"  balance {b:>3} USD → ATR≤{t2:.1f}: 3 meses {100*(y.atr<=t2).mean():.0f} %, 12 meses {100*(d[d.t>=end-pd.Timedelta(days=365)].atr<=t2).mean():.0f} %")
