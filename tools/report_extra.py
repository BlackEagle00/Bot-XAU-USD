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
from bot_engine.trade_manager import _progressive_lock_sl  # noqa: E402
import config as C  # noqa: E402
from types import SimpleNamespace as NS


def managed(buy, e, a, sl, tp, path, t0):
    """Escenario con la gestión del bot: BE+, trailing ATR + lock progresivo y cierre a MAX_HOLD_MINUTES.
    shortcut: gestiona al cierre de cada vela M1 con el ATR de la entrada (el bot usa ciclos de 15 s y ATR vivo)."""
    s, prev, d = sl, e, 1 if buy else -1
    pnl = lambda x: (x - e) * d - 0.06
    for t, h, lo, c, spr in path:
        if t - t0 >= C.MAX_HOLD_MINUTES * 60:
            return f"cierre {C.MAX_HOLD_MINUTES} min", t, pnl(prev)
        if (lo <= s) if buy else (h >= s):              # SL (o SL ya movido) primero
            return ("SL" if pnl(s) < 0 else "SL protegido"), t, pnl(s)
        if (h >= tp) if buy else (lo <= tp):
            return "TP", t, pnl(tp)
        if (s - e) * d < 0 and (c - e) * d >= C.BE_TRIGGER_PCT * abs(tp - e):
            s = e + d * (spr + C.BE_PLUS_POINTS * PT)   # BE+; ese ciclo no hay trailing (como manage_open_trades)
        elif C.USE_TRAILING_STOP:                       # sin trailing en el config: solo BE+ y tiempo, como el bot
            cand = c - d * a * C.TRAILING_ATR_MULT
            lk = _progressive_lock_sl(NS(price_open=e, price_current=c), a, buy)
            if lk and (lk[0] - cand) * d > 0:
                cand = lk[0]
            if (cand - s) * d > 0 and (cand - e) * d >= 0 and (c - cand) * d > 0:
                s = cand
        prev = c
    return None, s, None


# autocomprobación: BUY sube 1×ATR (lock asegura 40 %) y vuelve a la entrada → sale en positivo
if C.USE_TRAILING_STOP and C.USE_PROGRESSIVE_TRAIL:
    _r = managed(True, 100.0, 1.0, 98.5, 103.0, [(0, 101.0, 100.5, 101.0, 0.1), (60, 100.6, 100.0, 100.1, 0.1)], 0)
    assert _r[0] == "SL protegido" and abs(_r[2] - 0.34) < 1e-9, _r

SYM, SINCE, PT = "XAUUSD-ECN", "2026-11-03 00:00", 0.01
sig, atr, seen = [], None, set()
with open(_R + r"\xauusd_scalping_bot\xauusd_scalping_bot.log", encoding="utf-8", errors="replace") as f:
    for line in f:
        if line[1:17] < SINCE:
            continue
        if (a := re.search(r"📊.*ATR: ([\d.]+)", line)):
            atr = float(a.group(1))                     # la 📊 del ciclo se escribe antes del rechazo
        if (b := re.search(r"(\S+) (?:Trade )?(BUY|SELL) bloqueado", line)) and atr:   # if, no elif: los ⛔ RSI/ADX van en la misma línea 📊
            key = (line[1:15] + str(int(line[15:17]) // 15), b.group(2))   # un rechazo por vela M15 y lado (se repite cada ciclo)
            if key not in seen:
                seen.add(key)
                sig.append((line[1:20], b.group(2), atr, b.group(1)))

m.initialize()
tick = m.symbol_info_tick(SYM)
off = math.ceil((tick.time - time.time()) / 3600 - 0.05) * 3600   # shortcut: tick viejo (pausa) < 57 min; fines de semana falla
loc = lambda t: datetime.fromtimestamp(int(t) - off).strftime("%H:%M")
total = total2 = 0.0
for ts, side, a, why in sig:
    t0 = int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()) + off
    tk = m.copy_ticks_range(SYM, t0 - 5, t0 + 1, m.COPY_TICKS_ALL)
    buy = side == "BUY"
    e = float(tk["ask"][-1] if buy else tk["bid"][-1])
    sl, tp = (e - 1.5 * a, e + 3 * a) if buy else (e + 1.5 * a, e - 3 * a)
    be_lvl = e + C.BE_TRIGGER_PCT * (tp - e)
    rest = m.copy_ticks_range(SYM, t0, t0 - t0 % 60 + 60, m.COPY_TICKS_ALL)
    px = rest["bid"] if buy else rest["ask"]          # BUY sale por BID; SELL por ASK
    path = [(t0, float(px.max()), float(px.min()), float(px[-1]), float(rest["ask"][-1] - rest["bid"][-1]))] if len(rest) else []
    bars = m.copy_rates_range(SYM, m.TIMEFRAME_M1, t0 - t0 % 60 + 60, tick.time + 60)
    sp = lambda x: 0 if buy else x["spread"] * PT
    path += [(int(x["time"]), float(x["high"] + sp(x)), float(x["low"] + sp(x)), float(x["close"] + sp(x)), x["spread"] * PT)
             for x in bars]
    be, res = False, None
    for t, h, lo, *_ in path:
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
    g = managed(buy, e, a, sl, tp, path, t0)
    if g[0]:
        total2 += g[2]
        print(f"      ↳ con BE/trailing/{C.MAX_HOLD_MINUTES} min: {g[0]} a las {loc(g[1])}: {g[2]:+.2f} USD")
    else:
        flo = ((tick.bid - e) if buy else (e - tick.ask)) - 0.06
        total2 += flo
        print(f"      ↳ con BE/trailing/{C.MAX_HOLD_MINUTES} min: ABIERTA {flo:+.2f} USD, SL movido a {g[1]:.2f}")
print(f"TOTAL hipotético ({len(sig)} señales, cerradas + flotantes): {total:+.2f} USD")
bal = m.account_info().balance
print(f"BALANCE real {bal:.2f} USD | si se hubieran abierto: {bal + total:.2f} USD ({total / bal * 100:+.1f} %)  [solo SL/TP]")
print(f"TOTAL con BE/trailing/{C.MAX_HOLD_MINUTES} min: {total2:+.2f} USD | BALANCE si se hubieran abierto: {bal + total2:.2f} USD "
      f"({total2 / bal * 100:+.1f} %)")

# ── 2. Foto multi-temporalidad (velas cerradas) ──
for name in ("M1", "M5", "M15", "M30", "H1", "H4"):
    d = pd.DataFrame(m.copy_rates_from_pos(SYM, getattr(m, f"TIMEFRAME_{name}"), 1, 300))
    e9, e21 = calc_ema(d.close, 9).iloc[-1], calc_ema(d.close, 21).iloc[-1]
    last = d.iloc[-1]
    print(f"{name:>3}: vela {loc(last.time)} {'▲' if last.close >= last.open else '▼'} {last.close - last.open:+.2f} | "
          f"EMA9/21 {'alcista' if e9 > e21 else 'bajista'} ({e9 - e21:+.2f}) | RSI {calc_rsi(d.close).iloc[-1]:.0f} | "
          f"ATR {calc_atr(d.high, d.low, d.close).iloc[-1]:.2f}")
m.shutdown()
