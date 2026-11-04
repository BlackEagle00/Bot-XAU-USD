"""Solo lectura: (1) operación hipotética de CADA señal bloqueada del log ("BUY/SELL bloqueado") desde 2026-10-28 11:00;
(2) foto M1/M5/M15/M30/H1/H4. No abre órdenes. SL/TP = 1.5/3.0×ATR de la 📊 de ese ciclo, comisión 0.06 (lote 0.01)."""
import math
import re
import sys
import time
from datetime import datetime

import MetaTrader5 as m
import pandas as pd

from pathlib import Path
_R = str(Path(__file__).resolve().parents[1])   # raíz del repo (PC o VPS)
sys.path[:0] = [_R + r"\xauusd_scalping_bot", _R]          # indicators importa el config del bot
from bot_engine.indicators import calc_atr, calc_ema, calc_rsi  # noqa: E402

SYM, SINCE, PT = "XAUUSD-ECN", "2026-11-02 00:00", 0.01
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
off = math.ceil((tick.time - time.time()) / 3600 - 0.05) * 3600
for ts, side, a, why in sig:
    t0 = int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()) + off
    buy = side == "BUY"
    tk = m.copy_ticks_range(SYM, t0 - 5, t0 + 1, m.COPY_TICKS_ALL)
    e = float(tk["ask"][-1] if buy else tk["bid"][-1])
    sl = e - 1.5 * a if buy else e + 1.5 * a
    bars = m.copy_rates_range(SYM, m.TIMEFRAME_M1, t0 - t0 % 60, tick.time + 60)
    best = 0.0
    for x in bars:                                   # MFE hasta la vela que toca el SL (aprox. con velas M1)
        fav = (x["high"] - e) if buy else (e - x["low"] - x["spread"] * PT)
        adv = (x["low"] <= sl) if buy else (x["high"] + x["spread"] * PT >= sl)
        if adv:
            break
        best = max(best, fav)
    print(f"{ts[11:16]} {side:<4} {why} ATR {a:.2f}: máximo a favor {best:+.2f} = {best/a:.2f}×ATR = {100*best/(3*a):.0f} % del camino al TP")
m.shutdown()
