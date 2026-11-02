"""Solo lectura: (1) operación hipotética de CADA señal bloqueada del log ("BUY/SELL bloqueado") desde 2026-10-28 11:00;
(2) foto M1/M5/M15/M30/H1/H4. No abre órdenes. SL/TP = 1.5/3.0×ATR de la 📊 de ese ciclo, comisión 0.06 (lote 0.01)."""
import math
import re
import sys
import time
from datetime import datetime

import MetaTrader5 as m
import pandas as pd

_R = r"C:\Users\Andrés Bonilla\Documents\ProyectosClaude\Proyecto Bot XAUUSD Git\Bot-XAU-USD"
sys.path[:0] = [_R + r"\xauusd_scalping_bot", _R]          # indicators importa el config del bot
from bot_engine.indicators import calc_atr, calc_ema, calc_rsi  # noqa: E402

SYM, SINCE, PT = "XAUUSD-ECN", "2026-11-01 00:00", 0.01
sig, atr = [], None
with open(_R + r"\xauusd_scalping_bot\xauusd_scalping_bot.log", encoding="utf-8", errors="replace") as f:
    for line in f:
        if line[1:17] < SINCE:
            continue
        if (a := re.search(r"📊.*ATR: ([\d.]+)", line)):
            atr = float(a.group(1))                     # la 📊 del ciclo se escribe antes del rechazo
        elif (b := re.search(r"(\S+) (BUY|SELL) bloqueado", line)) and atr:
            sig.append((line[1:20], b.group(2), atr, b.group(1)))

m.initialize()
tick = m.symbol_info_tick(SYM)
off = math.ceil((tick.time - time.time()) / 3600 - 0.05) * 3600   # shortcut: tick viejo (pausa) < 57 min; fines de semana falla
loc = lambda t: datetime.fromtimestamp(int(t) - off).strftime("%H:%M")
total = 0.0
for ts, side, a, why in sig:
    t0 = int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()) + off
    tk = m.copy_ticks_range(SYM, t0 - 5, t0 + 1, m.COPY_TICKS_ALL)
    buy = side == "BUY"
    e = float(tk["ask"][-1] if buy else tk["bid"][-1])
    sl, tp = (e - 1.5 * a, e + 3 * a) if buy else (e + 1.5 * a, e - 3 * a)
    be_lvl = e + 0.55 * (tp - e)
    rest = m.copy_ticks_range(SYM, t0, t0 - t0 % 60 + 60, m.COPY_TICKS_ALL)
    px = rest["bid"] if buy else rest["ask"]          # BUY sale por BID; SELL por ASK
    path = [(t0, float(px.max()), float(px.min()))] if len(rest) else []
    bars = m.copy_rates_range(SYM, m.TIMEFRAME_M1, t0 - t0 % 60 + 60, tick.time + 60)
    sp = lambda x: 0 if buy else x["spread"] * PT
    path += [(int(x["time"]), float(x["high"] + sp(x)), float(x["low"] + sp(x))) for x in bars]
    be, res = False, None
    for t, h, lo in path:
        hit_sl, hit_tp = (lo <= sl, h >= tp) if buy else (h >= sl, lo <= tp)
        if hit_sl:                                      # si una vela toca ambos, cuenta SL
            res = ("SL", t, -1.5 * a - 0.06)
            break
        if hit_tp:
            res = ("TP", t, 3 * a - 0.06)
            break
        be = be or (h >= be_lvl if buy else lo <= be_lvl)
    head = f"{ts[11:16]} {side:<4} {why} entrada {e:.2f} SL {sl:.2f} TP {tp:.2f} (ATR {a:.2f})"
    if res:
        total += res[2]
        print(f"{head} → {res[0]} a las {loc(res[1])}: {res[2]:+.2f} USD | zona BE antes: {be}")
    else:
        flo = ((tick.bid - e) if buy else (e - tick.ask)) - 0.06
        total += flo
        print(f"{head} → ABIERTA {flo:+.2f} USD | zona BE ({be_lvl:.2f}) tocada: {be}")
print(f"TOTAL hipotético ({len(sig)} señales, cerradas + flotantes): {total:+.2f} USD")

# ── 2. Foto multi-temporalidad (velas cerradas) ──
for name in ("M1", "M5", "M15", "M30", "H1", "H4"):
    d = pd.DataFrame(m.copy_rates_from_pos(SYM, getattr(m, f"TIMEFRAME_{name}"), 1, 300))
    e9, e21 = calc_ema(d.close, 9).iloc[-1], calc_ema(d.close, 21).iloc[-1]
    last = d.iloc[-1]
    print(f"{name:>3}: vela {loc(last.time)} {'▲' if last.close >= last.open else '▼'} {last.close - last.open:+.2f} | "
          f"EMA9/21 {'alcista' if e9 > e21 else 'bajista'} ({e9 - e21:+.2f}) | RSI {calc_rsi(d.close).iloc[-1]:.0f} | "
          f"ATR {calc_atr(d.high, d.low, d.close).iloc[-1]:.2f}")
m.shutdown()
