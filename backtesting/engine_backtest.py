"""
Backtest del MOTOR REAL (bot_engine) + filtro predictivo, sobre el histórico de MT5.

Uso (desde la raíz del repo, con el terminal MT5 abierto):
    python backtesting/engine_backtest.py xauusd_bot H1                    # config de un bot
    python backtesting/engine_backtest.py xauusd_swing H1 --ml             # perfil del panel
    opciones: --years 3  --balances 100,1000,10000  --ml  --mc 2000  --workers N  --refresh

Perfil = carpeta de un bot (usa su config.py) o un perfil del panel (dashboard/profiles/xauusd_<modo>,
mismo config que su bot con la identidad del panel).

Flujo (guía backtesting-frameworks: datos point-in-time, costos reales, walk-forward, Monte Carlo):
  1. Señales: al cierre de cada vela primaria, SOLO con velas ya cerradas de las 3 temporalidades,
     calculate_all → analyze_patterns → generate_signal (igual que core._run_cycle); para BUY/SELL
     también las features de ml_filter. En paralelo y con caché.
  2. Resultado de cada señal (triple barrera): entrada en la apertura siguiente con el spread real
     de la vela (BUY en ask, SELL en bid), SL/TP por ATR, R:R mínimo, spread ≤ 25% del SL, y
     BE+/trailing de trade_manager vela a vela. R = ganancia en unidades de riesgo. Se calcula para
     el SL/TP base y para cada combinación del barrido (COMBOS).
  3. Cuenta: con esos resultados simula la cuenta para cada balance: niveles por capital, lote
     dinámico, máximo de abiertas, anti-duplicado y límite diario con bloqueo hasta el día siguiente.
  4. --ml: walk-forward anclado por trimestres con purga. En cada ventana entrena un
     HistGradientBoosting con el pasado, elige SL/TP y umbral τ (acierto ≥ 75% y R total > 0) en una
     validación interna, y opera el trimestre siguiente. TODO lo reportado es fuera de muestra.
     Si el resultado fuera de muestra gana dinero, guarda el modelo final en models/.
  5. Monte Carlo: re-muestreo del orden de las operaciones → drawdown al 95% y P(pérdida).

No reproduce (no hay datos históricos): noticias, order-flow, DXY, swaps, comisiones, margen.
El BE/trailing se evalúa una vez por vela (en vivo cada 15-60 s); si una vela toca SL y TP → SL.
"""
import argparse
import re
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from multiprocessing import Pool
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd

ROOT    = Path(__file__).resolve().parent.parent
DATA    = ROOT / "backtesting" / "data"
REPORTS = ROOT / "backtesting" / "reports"

# primaria → (tendencia, superior)
TF_MAP = {"M1": ("M5", "M15"), "M5": ("M15", "H1"), "M10": ("M30", "H1"), "M15": ("H1", "H4"),
          "H1": ("H4", "D1"), "H4": ("D1", "W1"), "D1": ("W1", "MN1"), "W1": ("MN1", None)}
TF_MIN = {"M1": 1, "M5": 5, "M10": 10, "M15": 15, "M30": 30, "H1": 60, "H4": 240,
          "D1": 1440, "W1": 10080, "MN1": 44640}
BUY, SELL = 0, 1   # = mt5.ORDER_TYPE_BUY / SELL
SIG_VERSION = 3    # formato del caché de señales (2: + tendencia del TF superior; 3: score sin redondear)
# Claves de riesgo que no cambian las señales: un --set con ellas reusa el caché de señales
POST_KEYS = {"MAX_RISK_MIN_LOT", "MICRO_SL_FIT", "MICRO_MIN_SL_ATR", "GRID_EXEC_TF", "MAX_HOLD_MINUTES", "DAILY_LOSS_ALERT_ONLY",
             "MAX_SPREAD_POINTS", "BT_REAL_SPREAD", "BT_COMMISSION_PER_LOT", "BT_SLIPPAGE_POINTS",
             "BT_SWAP_LONG_POINTS", "BT_SWAP_SHORT_POINTS", "SKIP_REGIMES",
             "ENTRY_EXEC_TF", "ENTRY_MODE", "ENTRY_PULLBACK_ATR", "MIN_LOT_CAP_HARD",
             "ANOMALY_BLOCK", "ANOMALY_RANGE_MULT", "ANOMALY_LOOKBACK", "COOLING_DOWN_PERIOD",
             "BT_SPREAD_MULT", "BT_SPREAD_OFFSET_POINTS"}

# (SL, TP) en múltiplos de ATR. (None, None) = los del config. TP < SL sube el acierto y baja la ganancia por operación.
COMBOS = [(None, None), (1.5, 0.5), (1.5, 0.75), (1.5, 1.0), (2.0, 0.5), (2.0, 0.75), (2.0, 1.0), (2.0, 1.5)]
TARGET_WIN    = 0.75                      # acierto mínimo FUERA de muestra para activar un modelo
VAL_WIN       = 0.80                      # en la validación interna se exige más: la precisión cae al pasar a datos nuevos
MIN_SELECTED  = 30                        # operaciones mínimas en la validación para fiarse de τ
TAU_GRID      = np.round(np.arange(0.50, 0.951, 0.025), 3)
MAX_HOLD_BARS = 500                       # tope de la triple barrera
TEST_DAYS     = 91                        # walk-forward: ventanas de prueba trimestrales
FIRST_TEST    = 0.40                      # la primera prueba empieza tras el 40% del periodo
IS_FRACTION   = 0.60                      # análisis: 60% inicial in-sample, 40% final fuera de muestra


# ═══════════════════════════════════════════════════════════════════════════════
# AYUDAS PURAS (probadas en tests/test_engine.py)
# ═══════════════════════════════════════════════════════════════════════════════

def close_times(open_times: np.ndarray, tf: str) -> np.ndarray:
    """Hora de cierre de cada vela: apertura + duración nominal (o la apertura siguiente si llega antes)."""
    nominal = open_times + TF_MIN[tf] * 60
    nxt = np.append(open_times[1:], np.iinfo(np.int64).max)
    return np.minimum(nominal, nxt)


def closed_upto(closes: np.ndarray, t: int) -> int:
    """Número de velas ya cerradas en el instante t (cierre ≤ t). Nunca incluye una vela en formación."""
    return int(np.searchsorted(closes, t, side="right"))


def entry_price(side: int, bar_open: float, spread_price: float) -> float:
    """Las velas de MT5 son BID: BUY entra en ask = bid + spread; SELL en bid."""
    return bar_open + spread_price if side == BUY else bar_open


def trade_cost(lot: float, point: float, vpu: float, commission_per_lot: float = 0.0, slippage_points: float = 0.0) -> float:
    """Coste en USD de una operación: comisión ida y vuelta + slippage adverso en la entrada y en la salida.
    shortcut: el slippage se descuenta del P&L, no mueve el precio dentro de la triple barrera; basta para
    costes de pocos puntos, revisar si el slippage medido en vivo se acerca al tamaño del SL."""
    return lot * commission_per_lot + 2 * slippage_points * point * lot * vpu


def regime_labels(*a, **k):
    """La misma función que usa core en vivo; import diferido porque bot_engine necesita el config del perfil en sys.path."""
    from bot_engine.indicators import regime_labels as f
    return f(*a, **k)


def regime_stats(trades: list, labels: np.ndarray, times: np.ndarray) -> dict:
    """PF, acierto y expectativa en R por régimen a la apertura de cada operación."""
    out = {}
    for t in trades:
        k = min(int(np.searchsorted(times, t["open_time"])), len(labels) - 1)
        out.setdefault(str(labels[k]), []).append(t)
    res = {}
    for lab, ts in sorted(out.items()):
        pnl = np.array([t["pnl"] for t in ts])
        gl = float(-pnl[pnl < 0].sum())
        res[lab] = {"trades": len(ts), "pnl": round(float(pnl.sum()), 2),
                    "win_pct": round(float((pnl > 0).mean()) * 100, 1),
                    "pf": round(float(pnl[pnl > 0].sum()) / gl, 2) if gl > 0 else None,
                    "exp_r": round(float(np.mean([t["r"] for t in ts])), 3)}
    return res


def exit_price(side: int, o: float, h: float, l: float, spread_price: float,
               sl: float, tp: float, fresh: bool = False):
    """
    Precio de salida dentro de la vela, o None si sigue abierta.
    BUY cierra en BID; SELL cierra en ASK (= bid + spread). Si la vela toca SL y TP → SL.
    fresh=True: la posición se abrió en la apertura de esta vela (no hay hueco de apertura).
    """
    if side == BUY:
        if not fresh and o <= sl:
            return o
        if not fresh and o >= tp:
            return o
        if l <= sl:
            return sl
        if h >= tp:
            return tp
        return None
    ao, ah, al = o + spread_price, h + spread_price, l + spread_price
    if not fresh and ao >= sl:
        return ao
    if not fresh and ao <= tp:
        return ao
    if ah >= sl:
        return sl
    if al <= tp:
        return tp
    return None


def wf_folds(start_ts: int, end_ts: int):
    """Ventanas de prueba [a, b) del walk-forward anclado: se entrena con todo lo anterior a `a`."""
    a = start_ts + int((end_ts - start_ts) * FIRST_TEST)
    while a < end_ts:
        b = min(a + TEST_DAYS * 86400, end_ts)
        yield a, b
        a = b


def train_mask(t_decision: np.ndarray, t_exit: np.ndarray, test_start: int) -> np.ndarray:
    """Purga: solo entrenan señales cuya operación YA terminó antes de la prueba (sin fuga de futuro)."""
    return (t_decision < test_start) & (t_exit < test_start)


def pick_tau(p: np.ndarray, r: np.ndarray):
    """Umbral τ con acierto ≥ VAL_WIN, ≥ MIN_SELECTED operaciones y R total > 0 (el de mayor R). (τ, R) o None."""
    best = None
    for tau in TAU_GRID:
        sel = p >= tau
        if int(sel.sum()) < MIN_SELECTED:
            break
        win, total = float((r[sel] > 0).mean()), float(r[sel].sum())
        if win >= VAL_WIN and total > 0 and (best is None or total > best[1]):
            best = (float(tau), total)
    return best


def monte_carlo(rs, n: int = 2000, risk: float = 0.01, seed: int = 0):
    """Re-muestrea el orden de las operaciones (R) con riesgo fijo compuesto."""
    if len(rs) < 10:
        return None
    sims = np.random.default_rng(seed).choice(np.asarray(rs, float), size=(n, len(rs)), replace=True)
    eq = np.cumprod(1 + risk * sims, axis=1)
    peak = np.maximum.accumulate(np.maximum(eq, 1e-12), axis=1)
    dd = ((peak - eq) / peak).max(axis=1)
    final = eq[:, -1] - 1
    return {"dd_p50": round(float(np.percentile(dd, 50)) * 100, 1), "dd_p95": round(float(np.percentile(dd, 95)) * 100, 1),
            "ret_p5": round(float(np.percentile(final, 5)) * 100, 1), "ret_p50": round(float(np.percentile(final, 50)) * 100, 1),
            "p_loss": round(float((final < 0).mean()) * 100, 1)}


# ═══════════════════════════════════════════════════════════════════════════════
# CARGA DEL MOTOR
# ═══════════════════════════════════════════════════════════════════════════════

def profile_dir(profile: str) -> Path:
    for d in (ROOT / profile, ROOT / "dashboard" / "profiles" / profile):
        if (d / "config.py").exists():
            return d
    sys.exit(f"Perfil desconocido: {profile} (usa una carpeta de bot o scalping/swing)")


def load_engine(profile: str, primary: str, symbol: str = None, overrides: dict = None):
    """Importa el config del perfil y el motor. Ajusta las claves "24 h" al TF primario elegido.
    overrides = claves del config a probar sin editarlo (--set CLAVE=VALOR)."""
    sys.path[:0] = [str(profile_dir(profile)), str(ROOT)]
    os.chdir(tempfile.gettempdir())          # el logger del motor escribe su .log aquí, no en el repo
    import MetaTrader5 as mt5
    import config
    if symbol:
        config.SYMBOL = symbol               # antes de importar el motor: sus módulos copian SYMBOL
    for key, value in (overrides or {}).items():
        setattr(config, key, value)
    base = next(k for k in TF_MIN if getattr(mt5, f"TIMEFRAME_{k}", None) == config.PRIMARY_TF)
    factor = TF_MIN[base] / TF_MIN[primary]
    for key in ("SR_24H_CANDLES", "VWAP_PERIOD"):  # "24 horas" en velas del TF probado
        setattr(config, key, max(1, round(getattr(config, key) * factor)))
    import logging
    from bot_engine.logger_config import logger
    logger.setLevel(logging.WARNING)         # generate_signal escribe 1 línea INFO por llamada
    return config, base


def engine_hash(profile: str, overrides: dict = None) -> str:
    """Huella del código, la config y los --set: si cambian, la caché de señales se recalcula."""
    h = hashlib.md5(repr(sorted((overrides or {}).items())).encode())
    files = (sorted((ROOT / "bot_engine").glob("*.py")) + [profile_dir(profile) / "config.py"]
             + sorted(ROOT.glob("*/config.py")) + sorted((ROOT / "dashboard" / "profiles").rglob("*.py")))
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


# ═══════════════════════════════════════════════════════════════════════════════
# HISTÓRICO
# ═══════════════════════════════════════════════════════════════════════════════

def fetch(mt5, symbol: str, tf: str, start: datetime, end: datetime, refresh: bool) -> pd.DataFrame:
    """Velas [start, end) por tramos (el terminal limita las velas por pedido). Con caché."""
    path = DATA / f"{symbol}_{tf}_{start:%Y%m%d}_{end:%Y%m%d}.csv.gz"
    if path.exists() and not refresh:
        return pd.read_csv(path)
    parts, t = [], start
    step = timedelta(days=20 if tf == "M1" else 90)   # M1: un pedido de 90 días (≈ 90 000 velas) vuelve vacío
    while t < end:
        r = mt5.copy_rates_range(symbol, getattr(mt5, f"TIMEFRAME_{tf}"), t, min(t + step, end))
        if r is not None and len(r):
            parts.append(pd.DataFrame(r))
        t += step
    if not parts:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "spread"])
    df = (pd.concat(parts).drop_duplicates("time").sort_values("time")
          .rename(columns={"tick_volume": "volume"})
          [["time", "open", "high", "low", "close", "volume", "spread"]].reset_index(drop=True))
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SEÑALES EN PARALELO
# ═══════════════════════════════════════════════════════════════════════════════

_W = {}   # estado de cada proceso trabajador


def _init_worker(profile, primary, symbol, overrides, frames, point):
    config, _ = load_engine(profile, primary, symbol, overrides)
    from bot_engine.indicators import calculate_all
    from bot_engine.patterns import analyze_patterns
    from bot_engine.signals import generate_signal
    from bot_engine.core import _detect_trend_simple
    from bot_engine.ml_filter import features
    from bot_engine.signals import _determine_trend
    _W.update(cfg=config, calc=calculate_all, pat=analyze_patterns, sig=generate_signal,
              trend=_detect_trend_simple, feat=features, macro=_determine_trend, frames=frames, point=point,
              n={"p": config.CANDLES_PRIMARY - 1, "t": config.CANDLES_TREND - 1, "h": config.CANDLES_HIGHER - 1})


def _ohlcv(df, a, b):
    out = df.iloc[a:b][["time", "open", "high", "low", "close", "volume"]].copy()
    out.index = pd.to_datetime(out.pop("time"), unit="s")
    return out


def _signal_at(i):
    """Señal del motor al cierre de la vela primaria i (precio = apertura de i+1, mid) + features."""
    f, n, cfg = _W["frames"], _W["n"], _W["cfg"]
    p, pc = f["p"]
    t = int(pc[i])
    spread = float(p["spread"].iat[i + 1]) * _W["point"]
    price = float(p["open"].iat[i + 1]) + spread / 2
    prim = _ohlcv(p, max(0, i + 1 - n["p"]), i + 1)
    tdf, tc = f["t"]
    kt = closed_upto(tc, t)
    trend = _ohlcv(tdf, max(0, kt - n["t"]), kt)
    if len(trend) < 5:
        return i, "HOLD", 0.0, None, None, "neutral"
    ih = None
    if cfg.USE_MACRO_CONTEXT and f.get("h") is not None:
        hdf, hc = f["h"]
        kh = closed_upto(hc, t)
        if kh >= 5:
            ih = _W["calc"](_ohlcv(hdf, max(0, kh - n["h"]), kh), price)
    ip = _W["calc"](prim, price)
    it = _W["calc"](trend, price)
    atr = ip.get("atr")
    if atr is None:
        return i, "HOLD", 0.0, None, None, "neutral"
    s = _W["sig"](price, ip, it, _W["pat"](prim, _W["trend"](ip)), atr, ih)
    feats = None
    if s["action"] in ("BUY", "SELL"):
        feats = _W["feat"](1 if s["action"] == "BUY" else -1, price, ip, it, ih, s, spread, t)
    macro = _W["macro"](ih) if ih else "neutral"           # para aplicar REQUIRE_MACRO_FOR_SELL después (calibrate.py)
    return i, s["action"], float(s.get("raw_score", s["score"])), float(atr), feats, macro


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RESULTADO DE CADA SEÑAL (triple barrera con BE+/trailing)
# ═══════════════════════════════════════════════════════════════════════════════

def real_spread(bar_pts, times, close, symbol: str):
    """Spread por vela (puntos) = max(el de la vela, un cuantil del perfil REAL de su hora del servidor).
    Las velas guardan el spread MÍNIMO; el perfil sale de los ticks (backtesting/spread_profile.py) y se
    escala por precio (close / último close): con el oro a la mitad, el spread en puntos también era menor."""
    hours = json.loads((DATA / f"spread_profile_{symbol}.json").read_text(encoding="utf-8"))["hours"]
    prof = np.array([hours.get(str(h), [0.0] * 20) for h in range(24)])
    q = np.random.default_rng(0).integers(0, prof.shape[1], len(bar_pts))
    return np.maximum(bar_pts, prof[(times // 3600) % 24, q] * close / close[-1])


def make_outcome(arr, atr_at, sym, rm, tm, max_bars: int = MAX_HOLD_BARS, ex=None):
    """Devuelve outcome(i, side, sl_mult, tp_mult) → (R, exit_idx, entry, sl0, motivo) | 'rr' | 'spread' | 'noexec'.
    max_bars: velas hasta el cierre por TIEMPO (MAX_HOLD_MINUTES del config, como trade_manager en vivo).
    ex (experimento ENTRY_EXEC_TF): velas finas (o, h, l, c, sp, t, e9, e21) + t_prim (aperturas del TF primario),
    mode y f. La entrada se afina con las velas finas que caen DENTRO de la vela de entrada k:
      market   → a mercado en la 1.ª vela fina (control: mide solo el efecto de recorrer k en velas finas)
      pullback → límite a f×ATR en contra con los MISMOS niveles SL/TP; llena solo si el precio lo cruza por un spread
      confirm  → una de las 2 primeras velas finas cierra a favor con EMA9/21 finas alineadas; entra en la siguiente
    Sin entrada en la vela k → 'noexec'. Tras la vela k sigue igual que sin ex (BE/trailing al cierre de cada vela)."""
    o, h, l, c, sp = arr
    max_spread = getattr(rm._cfg, "MAX_SPREAD_POINTS", float("inf"))
    cur = NS(pos=None, bid=0.0, ask=0.0)

    def _set_sl(ticket, new_sl, tp, digits):
        cur.pos.sl = round(new_sl, digits)
        return True
    tm._modify_sl = _set_sl
    tm.get_tick = lambda *a, **k: NS(ask=cur.ask, bid=cur.bid)

    def outcome(i, side, slm, tpm):
        k = i + 1
        action = "BUY" if side == BUY else "SELL"
        px = entry_price(side, o[k], sp[k])
        sl, tp = rm.calculate_sl_tp(action, px, atr_at[i], sym, slm, tpm)
        if not rm.check_risk_reward(px, sl, tp, tpm / slm * 0.9 if slm else None)[0]:
            return "rr"
        risk = abs(px - sl)
        if not rm.spread_ok(sp[k], risk) or sp[k] / sym.point >= max_spread:   # = connection.is_market_open
            return "spread"
        last = min(len(o), k + max_bars) - 1
        j0 = k
        if ex is not None:
            fx = _fine_entry(k, i, side, action, px, sl, tp, slm, tpm)
            if not isinstance(fx, tuple):
                return fx
            px, sl, tp, x, j0 = fx
            risk = abs(px - sl)
            if x is not None:                            # salió dentro de la vela k (recorrido fino)
                return ((x - px) if side == BUY else (px - x)) / risk, k, px, sl, (
                    "TP" if abs(x - tp) < sym.point / 2 else "SL" if abs(x - sl) < sym.point / 2 else "HUECO")
            if j0 > last:
                return "noexec"
        pos = cur.pos = NS(ticket=0, type=side, price_open=px, sl=sl, tp=tp, price_current=px)
        if j0 > k:                                       # la vela k ya se recorrió en fino: BE/trailing a su cierre
            cur.bid, cur.ask = c[k], c[k] + sp[k]
            pos.price_current = c[k] if side == BUY else c[k] + sp[k]
            if atr_at[k] == atr_at[k] and not tm.update_breakeven(pos, atr_at[k], sym):
                tm.update_trailing_stop(pos, atr_at[k], sym)
        for j in range(j0, last + 1):
            x = exit_price(side, o[j], h[j], l[j], sp[j], pos.sl, pos.tp, fresh=(j == k))
            timed_out = x is None and j == last
            if timed_out:
                x = c[j] if side == BUY else c[j] + sp[j]
            if x is not None:
                r = ((x - px) if side == BUY else (px - x)) / risk
                reason = ("TIEMPO" if timed_out else "TP" if abs(x - tp) < sym.point / 2
                          else "SL" if abs(x - pos.sl) < sym.point / 2 else "HUECO")
                return r, j, px, sl, reason
            a = atr_at[j]
            if a == a:                                   # no NaN: hay ATR al cierre de esta vela
                cur.bid, cur.ask = c[j], c[j] + sp[j]
                pos.price_current = c[j] if side == BUY else c[j] + sp[j]
                if not tm.update_breakeven(pos, a, sym):
                    tm.update_trailing_stop(pos, a, sym)

    def _fine_entry(k, i, side, action, px, sl, tp, slm, tpm):
        """(entrada, sl, tp, salida_en_k | None, siguiente vela primaria) o 'noexec' / 'spread'. Ver make_outcome."""
        xo, xh, xl, xc, xs = ex.o, ex.h, ex.l, ex.c, ex.sp
        a = int(np.searchsorted(ex.t, ex.t_prim[k]))
        b = int(np.searchsorted(ex.t, ex.t_prim[k + 1] if k + 1 < len(ex.t_prim) else np.iinfo(np.int64).max))
        if b <= a:
            return "noexec"
        if ex.mode == "pullback":
            lim = px - ex.f * atr_at[i] if side == BUY else px + ex.f * atr_at[i]
            e = next((m for m in range(a, b)
                      if (xl[m] + 2 * xs[m] <= lim if side == BUY else xh[m] >= lim + xs[m])), None)
            if e is None:
                return "noexec"
            px = lim
            if not rm.spread_ok(xs[e], abs(px - sl)):
                return "spread"
            if (xl[e] <= sl) if side == BUY else (xh[e] + xs[e] >= sl):     # en la vela del llenado solo cuenta el SL
                return px, sl, tp, sl, k + 1
            first = e + 1
        else:
            if ex.mode == "confirm":
                up = side == BUY
                m = next((m for m in range(a, min(a + 2, b - 1))
                          if ((xc[m] > xo[m] and ex.e9[m] > ex.e21[m]) if up
                              else (xc[m] < xo[m] and ex.e9[m] < ex.e21[m]))), None)
                if m is None:
                    return "noexec"
                e = m + 1
            else:
                e = a
            px = entry_price(side, xo[e], xs[e])
            sl, tp = rm.calculate_sl_tp(action, px, atr_at[i], sym, slm, tpm)
            if not rm.spread_ok(xs[e], abs(px - sl)):
                return "spread"
            x = exit_price(side, xo[e], xh[e], xl[e], xs[e], sl, tp, fresh=True)
            if x is not None:
                return px, sl, tp, x, k + 1
            first = e + 1
        for m in range(first, b):
            x = exit_price(side, xo[m], xh[m], xl[m], xs[m], sl, tp)
            if x is not None:
                return px, sl, tp, x, k + 1
        return px, sl, tp, None, k + 1
    return outcome


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CUENTA (niveles por capital, lote dinámico, límites)
# ═══════════════════════════════════════════════════════════════════════════════

def simulate(cands: dict, p: pd.DataFrame, sym, vpu: float, cfg, rm, balance0: float, start_idx: int,
             outcome=None):
    """
    cands = {vela de entrada k: (side, R, exit_idx, entry, sl0, motivo, atr)}.
    outcome = make_outcome(...): con MICRO_SL_FIT, si ni el lote mínimo cabe, se vuelve a simular la
    señal con el SL/TP acercado de risk_manager.micro_sl_distance (mismo R:R), igual que en vivo.
    Devuelve (trades, curva [(time, equity)], bloqueos).
    """
    o, c = p["open"].to_numpy(float), p["close"].to_numpy(float)
    sp, tt = p["spread"].to_numpy(float) * sym.point, p["time"].to_numpy(np.int64)
    balance, open_pos, trades, curve = balance0, [], [], []
    blocked = dict(max_open=0, anti_dup=0, lot0=0, daily_halt=0)
    halt_day = day = None
    day_realized, peak, dd_stop = 0.0, 0.0, False
    comm, slip = getattr(cfg, "BT_COMMISSION_PER_LOT", 0.0), getattr(cfg, "BT_SLIPPAGE_POINTS", 0.0)
    swaps = (getattr(cfg, "BT_SWAP_LONG_POINTS", 0.0), getattr(cfg, "BT_SWAP_SHORT_POINTS", 0.0))   # puntos/lote/noche (MT5)

    def unrealized(bid, spr):
        return sum(((bid - q["entry"]) if q["side"] == BUY else (q["entry"] - bid - spr)) * q["lot"] * vpu
                   for q in open_pos)

    for k in range(start_idx, len(p)):
        d = datetime.fromtimestamp(int(tt[k]), tz=timezone.utc).date()
        if d != day:
            day, day_realized = d, 0.0
        cand = cands.get(k)
        if cand:
            side, R, exit_idx, entry, sl0, reason, atr, *rr = cand    # rr: TP/SL del combo (ML), si viene
            eq = balance + unrealized(o[k], sp[k])
            tier = rm.capital_tier(min(balance, eq))
            peak = max(peak, eq)                                # corte total MAX_DD_PCT, igual que can_open_trade
            if not dd_stop and rm.dd_halted(eq, peak, getattr(cfg, "MAX_DD_PCT", None)):
                dd_stop = True
                blocked["dd_halt_at"] = _d(int(tt[k]))
            if (not getattr(cfg, "DAILY_LOSS_ALERT_ONLY", False) and halt_day != day      # modo alerta: avisa, no corta
                    and day_realized + eq - balance <= -tier["daily_loss"] * balance):
                halt_day = day
            mid = o[k] + sp[k] / 2
            if dd_stop:
                blocked["dd_halt"] = blocked.get("dd_halt", 0) + 1
            elif halt_day == day:
                blocked["daily_halt"] += 1
            elif len(open_pos) >= tier["max_open"]:
                blocked["max_open"] += 1
            elif cfg.USE_ANTI_DUPLICATE and any(q["side"] == side and abs(q["entry"] - mid) < atr * cfg.ANTI_DUP_ATR_MULT
                                                for q in open_pos):
                blocked["anti_dup"] += 1
            else:
                lot = rm.lot_plan(NS(balance=balance, equity=eq), sym, abs(entry - sl0))[0]
                dist = (rm.micro_sl_distance(min(balance, eq), sym, atr)
                        if outcome and rm.over_min_lot_cap(NS(balance=balance, equity=eq), sym, abs(entry - sl0)) else None)
                if dist and dist < abs(entry - sl0):            # cuenta pequeña: SL/TP acercados, mismo R:R
                    slm = dist / atr
                    res = outcome(k - 1, side, slm, slm * (rr[0] if rr else cfg.TP_ATR_MULT / cfg.SL_ATR_MULT))
                    if isinstance(res, tuple):
                        R, exit_idx, entry, sl0, reason = res
                        lot = rm.lot_plan(NS(balance=balance, equity=eq), sym, abs(entry - sl0))[0]
                        blocked["micro_sl"] = blocked.get("micro_sl", 0) + 1
                if lot <= 0:
                    blocked["lot0"] += 1
                else:
                    open_pos.append(dict(side=side, R=R, exit_idx=exit_idx, entry=entry, lot=lot, open_idx=k,
                                         reason=reason, risk=abs(entry - sl0) * lot * vpu, tier=tier["name"]))
        for q in [q for q in open_pos if q["exit_idx"] == k]:
            nights = (datetime.fromtimestamp(int(tt[k]), tz=timezone.utc).date()
                      - datetime.fromtimestamp(int(tt[q["open_idx"]]), tz=timezone.utc).date()).days
            # shortcut: sin el swap triple del miércoles; subestima ~1/7 del swap en posiciones de varios días
            cost = trade_cost(q["lot"], sym.point, vpu, comm, slip) - swaps[q["side"]] * sym.point * q["lot"] * vpu * nights
            pnl = q["R"] * q["risk"] - cost
            balance += pnl
            day_realized += pnl
            trades.append(dict(side="BUY" if q["side"] == BUY else "SELL", open_time=int(tt[q["open_idx"]]),
                               close_time=int(tt[k]), lot=q["lot"], pnl=round(pnl, 2),
                               r=round(pnl / q["risk"], 3) if q["risk"] else 0.0, r_gross=round(q["R"], 3),
                               cost=round(cost, 4), reason=q["reason"], bars=k - q["open_idx"] + 1, tier=q["tier"]))
            open_pos.remove(q)
        curve.append((int(tt[k]), balance + unrealized(c[k], sp[k])))
    return trades, curve, blocked


def simulate_grid(sig: pd.DataFrame, p: pd.DataFrame, sym, vpu: float, cfg, rm, balance0: float,
                  start_idx: int, tf_min: int, thr: float = None):
    """
    Grid + cesta (bot_engine/grid.py) vela por vela. Una cesta se abre en la apertura siguiente a una
    señal BUY/SELL con |score| ≥ thr (None → cfg.MIN_SIGNAL_SCORE), dimensionada por riesgo
    (grid.build_basket) y solo en horario permitido (grid.entry_allowed). Dentro de cada vela, orden
    CONSERVADOR: hueco de apertura → extremo ADVERSO (límites y SL común, en el orden en que el precio los
    cruza) → extremo FAVORABLE (TP cortos, TP de cesta) → al cierre, tiempo máximo y corte por drawdown.
    Un límite llenado en el mínimo de una vela no puede salir en su máximo (eso supondría que el mínimo
    llegó primero). El viernes a GRID_FRIDAY_CLOSE_HOUR la cesta se cierra en la apertura de la vela.
    Devuelve (trades, curva, bloqueos, cestas).
    """
    from bot_engine import grid
    thr = cfg.MIN_SIGNAL_SCORE if thr is None else thr
    ev = sig[sig["action"].isin(["BUY", "SELL"]) & (sig["score"].abs() >= thr)
             & (sig["score"].abs() <= getattr(cfg, "GRID_MAX_SCORE", float("inf")))]   # igual que grid.extra_basket_block
    cands = {int(i) + 1: (a, float(x)) for i, a, x in zip(ev["i"], ev["action"], ev["atr"])}
    o, h, l, c = (p[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    sp, tt = p["spread"].to_numpy(float) * sym.point, p["time"].to_numpy(np.int64)
    balance, trades, curve, baskets = balance0, [], [], []
    blocked = dict(daily_halt=0, spread=0, busy=0, hours=0, capital=0, halted=0)
    acct_cut = getattr(cfg, "ACCOUNT_MAX_DAILY_LOSS_PCT", rm.ACCOUNT_MAX_DAILY_LOSS_PCT)
    halt_day = day = None
    day_realized, peak, halted_at = 0.0, balance0, None
    B = None                                              # cesta abierta

    def ex(x, s):                                         # precio de cierre: BUY al bid, SELL al ask
        return x if B["d"] == 1 else x + s

    def en(x, s):                                         # precio de entrada: BUY al ask, SELL al bid
        return x + s if B["d"] == 1 else x

    def live():
        return [lv for lv in B["levels"] if lv["entry"] is not None]

    def ready():
        """Posiciones que ya existían al empezar la vela (ver docstring)."""
        return [lv for lv in live() if not lv.get("intrabar")]

    def floating(x, s, pos=None):
        return sum(lv["lot"] * B["d"] * (ex(x, s) - lv["entry"]) * vpu for lv in (live() if pos is None else pos))

    def close(lv, price, k, reason):
        nonlocal balance, day_realized
        pnl = lv["lot"] * B["d"] * (price - lv["entry"]) * vpu
        balance += pnl
        day_realized += pnl
        B["realized"] += pnl
        B["trades"] += 1
        trades.append(dict(side=B["side"], open_time=int(tt[lv["open_k"]]), close_time=int(tt[k]), lot=lv["lot"],
                           pnl=round(pnl, 2), r=round(pnl / B["risk"], 3), reason=reason,
                           bars=k - lv["open_k"] + 1, tier="Grid", level=lv["k"]))
        lv["entry"] = None

    def end_basket(k, reason, price):
        nonlocal B
        for lv in live():
            close(lv, price, k, reason)
        baskets.append(dict(side=B["side"], open_time=int(tt[B["open_k"]]), close_time=int(tt[k]), reason=reason,
                            pnl=round(B["realized"], 2), ret=B["realized"] / B["eq0"], risk_pct=B["risk"] / B["eq0"],
                            trades=B["trades"], max_levels=B["max_live"], n_levels=len(B["levels"]),
                            minutes=(int(tt[k]) - int(tt[B["open_k"]])) / 60 + tf_min))
        B = None

    def exit_at(target, x_from, x, s, gap, pos):
        """Precio de salida al que el P&L de la cesta = target, dentro del tramo recorrido x_from → x."""
        lots = sum(lv["lot"] for lv in pos)
        if gap or lots == 0:
            return ex(x, s)
        px = (target - B["realized"]) / (B["d"] * lots * vpu) + sum(lv["lot"] * lv["entry"] for lv in pos) / lots
        lo, hi = sorted((ex(x_from, s), ex(x, s)))
        return min(max(px, lo), hi)

    def touch(k, x, s, x_from, gap):
        """El precio (bid) va de x_from a x. gap=True: salto de apertura. Devuelve True si cerró la cesta."""
        d = B["d"]
        adverse = gap or d * (x - x_from) <= 0
        if adverse:
            # límites (BUY se llena con ask ≤ nivel → bid ≤ nivel − spread) y SL común, en orden de cruce
            evs = [((lv["price"] - s) if d == 1 else lv["price"], lv) for lv in B["levels"]
                   if lv["armed"] and lv["entry"] is None]
            evs.append((B["sl"] if d == 1 else B["sl"] - s, None))
            evs = sorted((e for e in evs if d * (x - e[0]) <= 0 and (gap or d * (e[0] - x_from) <= 0)),
                         key=lambda e: -d * e[0])
            for _, lv in evs:
                if lv is None:                             # stop de cesta: el SL común cierra todo
                    end_basket(k, "CESTA_STOP", ex(x, s) if gap else B["sl"])
                    return True
                lv.update(entry=en(x, s) if gap else lv["price"], open_k=k, armed=False, intrabar=not gap)
                B["max_live"] = max(B["max_live"], len(live()))
            if balance + floating(x, s) <= 0:              # cuenta quebrada (hueco): stop-out
                end_basket(k, "QUIEBRA", ex(x, s))
                return True
        if gap or not adverse:
            for lv in ready():                             # TP corto de cada operación → re-armar el nivel
                if d * (ex(x, s) - lv["tp"]) >= 0:
                    close(lv, ex(x, s) if gap else lv["tp"], k, "TP")
                    lv["armed"] = True
            if B["realized"] + floating(x, s, ready()) >= B["tp_usd"]:
                px = exit_at(B["tp_usd"], x_from, x, s, gap, ready())
                for lv in live():                          # en el peor orden, sus límites aún no se habían llenado
                    if lv.get("intrabar"):
                        lv["entry"] = None
                end_basket(k, "CESTA_TP", px)
                return True
        return False

    for k in range(start_idx, len(p)):
        now = datetime.fromtimestamp(int(tt[k]), tz=timezone.utc)   # hora del servidor de MT5
        if now.date() != day:
            day, day_realized = now.date(), 0.0
        s, fresh = sp[k], False
        if B is not None and grid.must_flatten(now, cfg):
            end_basket(k, "FINDE", ex(o[k], s))
        cand = cands.get(k)
        if cand and halted_at is not None:
            blocked["halted"] += 1
        elif cand and B is not None:
            blocked["busy"] += 1
        elif cand:
            side, atr = cand
            tier = rm.capital_tier(balance)
            if halt_day != day and day_realized <= -min(tier["daily_loss"], acct_cut) * balance:
                halt_day = day
            if halt_day == day:
                blocked["daily_halt"] += 1
            elif not grid.entry_allowed(now, cfg):
                blocked["hours"] += 1
            elif not rm.spread_ok(s, atr * min(grid.p("GRID_SPACING_ATR", cfg), grid.p("GRID_TRADE_TP_ATR", cfg))):
                blocked["spread"] += 1
            else:
                dd = 1 if side == "BUY" else -1
                entry = o[k] + s if dd == 1 else o[k]
                b = grid.build_basket(side, entry, atr, balance, sym, vpu, cfg)
                if b is None:
                    blocked["capital"] += 1
                else:
                    for lv in b["levels"]:
                        lv.update(entry=None, open_k=k, armed=lv["k"] > 0)
                    b["levels"][0]["entry"] = entry
                    B = dict(side=side, d=dd, levels=b["levels"], sl=b["sl"], open_k=k, eq0=balance, realized=0.0,
                             trades=0, max_live=1, risk=b["risk_usd"], tp_usd=b["tp_usd"])
                    fresh = True
        if B is not None:
            adv, fav = (l[k], h[k]) if B["d"] == 1 else (h[k], l[k])
            done = ((not fresh and touch(k, o[k], s, o[k], True)) or touch(k, adv, s, o[k], False)
                    or touch(k, fav, s, adv, False))
            if not done and (int(tt[k]) - int(tt[B["open_k"]])) / 60 + tf_min >= grid.p("GRID_MAX_MINUTES", cfg):
                end_basket(k, "TIEMPO", ex(c[k], s))
            if B is not None:
                for lv in B["levels"]:
                    lv["intrabar"] = False
        eq = balance + (floating(c[k], s) if B else 0.0)
        peak = max(peak, eq)
        if halted_at is None and grid.dd_halt(eq, peak, cfg):     # corte por drawdown: cerrar y no abrir más
            if B is not None:
                end_basket(k, "DD", ex(c[k], s))
            halted_at, eq = int(tt[k]), balance
        curve.append((int(tt[k]), eq))
    if B is not None:                                      # fin de los datos: cerrar al último cierre
        end_basket(len(p) - 1, "TIEMPO", ex(c[-1], sp[-1]))
    blocked["halted_at"] = _d(halted_at) if halted_at else None
    return trades, curve, blocked, baskets


def grid_stats(baskets: list) -> dict:
    """Resumen por CESTA (la unidad de riesgo del grid)."""
    if not baskets:
        return {"baskets": 0}
    pnl = np.array([b["pnl"] for b in baskets])
    ret = np.array([b["ret"] for b in baskets])
    return {"baskets": len(baskets), "basket_win_pct": round(float((pnl > 0).mean()) * 100, 1),
            "avg_basket_pnl": round(float(pnl.mean()), 2), "worst_basket": round(float(pnl.min()), 2),
            "best_basket": round(float(pnl.max()), 2), "worst_basket_ret_pct": round(float(ret.min()) * 100, 2),
            "avg_basket_minutes": round(float(np.mean([b["minutes"] for b in baskets])), 1),
            "avg_trades_per_basket": round(float(np.mean([b["trades"] for b in baskets])), 1),
            "max_levels": int(max(b["max_levels"] for b in baskets)),
            "avg_risk_pct": round(float(np.mean([b["risk_pct"] for b in baskets])) * 100, 2),
            "avg_levels": round(float(np.mean([b["n_levels"] for b in baskets])), 1),
            "exits": {r: sum(b["reason"] == r for b in baskets)
                      for r in ("CESTA_TP", "CESTA_STOP", "TIEMPO", "FINDE", "DD", "QUIEBRA")},
            "ruined": any(b["reason"] == "QUIEBRA" for b in baskets)}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. WALK-FORWARD DEL FILTRO PREDICTIVO
# ═══════════════════════════════════════════════════════════════════════════════

CLF = "hgb"        # --clf: "hgb" (gradient boosting) | "mlp" (red neuronal; mismo walk-forward purgado)


def _classifier():
    if CLF == "mlp":
        from sklearn.impute import SimpleImputer
        from sklearn.neural_network import MLPClassifier
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(SimpleImputer(), StandardScaler(),
                             MLPClassifier(hidden_layer_sizes=(32, 16), alpha=1e-3, early_stopping=True,
                                           max_iter=400, random_state=0))
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15,
                                          min_samples_leaf=40, l2_regularization=1.0, random_state=0)


def calibration(p: np.ndarray, y: np.ndarray) -> dict:
    """Calidad probabilística fuera de muestra: Brier y log-loss del modelo frente a la tasa base
    (predecir siempre la frecuencia de aciertos). Un modelo útil tiene brier < brier_base."""
    p, y = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6), np.asarray(y, float)
    base = np.full_like(p, y.mean())
    ll = lambda q: float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))
    return {"brier": round(float(np.mean((p - y) ** 2)), 4), "brier_base": round(float(np.mean((base - y) ** 2)), 4),
            "logloss": round(ll(p), 4), "logloss_base": round(ll(np.clip(base, 1e-6, 1 - 1e-6)), 4), "n": int(len(y))}


def walk_forward(ev_i, X, t_dec, outs, tt, start_ts, end_ts, log=print):
    """
    ev_i: índices de las señales; X: features; t_dec: hora de decisión; outs[c]: outcomes por combo.
    Devuelve (plan {i: combo}, ventanas, modelo final (combo, τ, clf) o None, inicio de la prueba).
    """
    R, T_exit = {}, {}
    for c, lst in outs.items():
        R[c] = np.array([o[0] if isinstance(o, tuple) else np.nan for o in lst])
        T_exit[c] = np.array([tt[o[1]] if isinstance(o, tuple) else np.iinfo(np.int64).max for o in lst])
    plan, folds, last = {}, [], None
    for a, b in wf_folds(start_ts, end_ts):
        best = None
        for c in outs:
            idx = np.flatnonzero(train_mask(t_dec, T_exit[c], a) & ~np.isnan(R[c]))
            if len(idx) < 200:
                continue
            cut = idx[int(len(idx) * 0.75)]
            tr, va = idx[idx < cut], idx[idx >= cut]
            y = R[c][tr] > 0
            if y.all() or not y.any():
                continue
            clf = _classifier().fit(X[tr], y)
            pick = pick_tau(clf.predict_proba(X[va])[:, 1], R[c][va])
            if pick and (best is None or pick[1] > best[2]):
                best = (c, pick[0], pick[1], idx)
        test = np.flatnonzero((t_dec >= a) & (t_dec < b))
        if best is None:
            folds.append({"test_from": _d(a), "test_to": _d(b), "combo": None, "tau": None,
                          "selected": 0, "signals": int(len(test))})
            continue
        c, tau, _, idx = best
        clf = _classifier().fit(X[idx], R[c][idx] > 0)
        probs = clf.predict_proba(X[test])[:, 1] if len(test) else []
        sel = [j for j, pr in zip(test, probs) if pr >= tau and not np.isnan(R[c][j])]
        ok = [k for k, j in enumerate(test) if not np.isnan(R[c][j])]
        cal = calibration(np.asarray(probs)[ok], R[c][test[ok]] > 0) if ok else {}
        for j in sel:
            plan[int(ev_i[j])] = c
        folds.append({"test_from": _d(a), "test_to": _d(b), "combo": list(c), "tau": tau,
                      "selected": len(sel), "signals": int(len(test)), **cal})
        last = (c, tau)
        log(f"    ventana {_d(a)}→{_d(b)}: SL/TP {c} τ={tau} → {len(sel)}/{len(test)} señales")
    final = None
    if last:
        c, tau = last
        m = ~np.isnan(R[c])
        final = (c, tau, _classifier().fit(X[m], R[c][m] > 0))
    first_test = next(wf_folds(start_ts, end_ts), (end_ts, end_ts))[0]
    return plan, folds, final, first_test


def _d(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════════════════════
# MÉTRICAS Y VEREDICTO
# ═══════════════════════════════════════════════════════════════════════════════

def metrics(trades: list, curve: list, start_balance: float, with_daily: bool = False) -> dict:
    eq = np.array([e for _, e in curve]) if curve else np.array([start_balance])
    peak = np.maximum.accumulate(np.maximum(eq, 1e-9))
    max_dd = float(((peak - eq) / peak).max()) if len(eq) else 0.0
    if curve:
        days = pd.Series(eq, index=pd.to_datetime([t for t, _ in curve], unit="s")).resample("D").last().dropna()
    else:
        days = pd.Series([start_balance], index=pd.to_datetime([0], unit="s"))
    rets = days.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * math.sqrt(252)) if len(rets) > 2 and rets.std() > 0 else 0.0
    down = float(np.sqrt((np.minimum(rets, 0) ** 2).mean())) if len(rets) > 2 else 0.0     # desviación a la baja
    sortino = float(rets.mean() / down * math.sqrt(252)) if down > 0 else 0.0
    r_all = np.array([t["r"] for t in trades]) if trades else np.array([0.0])
    costs = np.array([t.get("cost", 0.0) for t in trades]) if trades else np.array([0.0])
    years = (curve[-1][0] - curve[0][0]) / (365.25 * 86400) if len(curve) > 1 else 0.0
    final = float(eq[-1])
    pnl = np.array([t["pnl"] for t in trades]) if trades else np.array([])
    gp, gl = float(pnl[pnl > 0].sum()), float(-pnl[pnl < 0].sum())
    streak = worst = 0
    for x in pnl:
        streak = streak + 1 if x < 0 else 0
        worst = max(worst, streak)
    by_year = {}
    for t in trades:
        y = str(datetime.fromtimestamp(t["close_time"], tz=timezone.utc).year)
        b = by_year.setdefault(y, {"trades": 0, "pnl": 0.0, "wins": 0})
        b["trades"] += 1
        b["pnl"] = round(b["pnl"] + t["pnl"], 2)
        b["wins"] += int(t["pnl"] > 0)
    sides = {}
    for s in ("BUY", "SELL"):
        rs = [t["r"] for t in trades if t["side"] == s]
        if rs:
            sides[s] = {"trades": len(rs), "exp_r": round(float(np.mean(rs)), 3),
                        "win_pct": round(float(np.mean(np.array(rs) > 0)) * 100, 1)}
    m = {
        "start_balance": start_balance, "final_equity": round(final, 2),
        "net_return_pct": round((final / start_balance - 1) * 100, 2),
        "cagr_pct": round(((final / start_balance) ** (1 / years) - 1) * 100, 2) if final > 0 and years > 0.2 else None,
        "max_drawdown_pct": round(max_dd * 100, 2), "sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
        "net_expectancy_usd": round(float(pnl.mean()), 3) if len(pnl) else 0.0,
        "cost_total": round(float(costs.sum()), 2), "cost_per_trade": round(float(costs.mean()), 4),
        "r_dist": {"p5": round(float(np.percentile(r_all, 5)), 3), "p25": round(float(np.percentile(r_all, 25)), 3),
                   "median": round(float(np.median(r_all)), 3), "p75": round(float(np.percentile(r_all, 75)), 3),
                   "p95": round(float(np.percentile(r_all, 95)), 3),
                   "hist": {f"{lo:+.1f}..{lo + 0.5:+.1f}": int(((r_all >= lo) & (r_all < lo + 0.5)).sum())
                            for lo in np.arange(-3.0, 3.0, 0.5)}},       # huecos: R < −1 existe
        "trades": len(trades), "win_rate_pct": round(float((pnl > 0).mean() * 100), 1) if len(pnl) else 0.0,
        "profit_factor": round(gp / gl, 2) if gl > 0 else None,
        "expectancy_r": round(float(np.mean([t["r"] for t in trades])), 3) if trades else 0.0,
        "avg_bars": round(float(np.mean([t["bars"] for t in trades])), 1) if trades else 0.0,
        "worst_losing_streak": worst,
        "trades_per_month": round(len(trades) / (years * 12), 1) if years > 0 else 0.0,
        "exits": {r: sum(t["reason"] == r for t in trades)
                  for r in sorted({"TP", "SL", "HUECO", "TIEMPO"} | {t["reason"] for t in trades})},
        "by_year": dict(sorted(by_year.items())), "sides": sides,
        **trade_timing(trades, curve, start_balance),
    }
    m["verdict"] = verdict(m)
    if with_daily:
        m["equity_daily"] = [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in days.items()]
    return m


# Horas del SERVIDOR de MT5: las velas vienen en hora del servidor (MetaQuotes-Demo ≈ UTC+2/+3)
SESSIONS = (("Asia", 1, 10), ("Londres", 10, 15), ("Nueva York", 15, 23), ("Cierre", 23, 25))


def trade_timing(trades: list, curve: list, start_balance: float) -> dict:
    """Análisis para operaciones cortas: duración, sesión de apertura, tiempo hasta duplicar la cuenta."""
    mins = np.array([(t["close_time"] - t["open_time"]) / 60 for t in trades]) if trades else np.array([0.0])
    by_session = {}
    for name, a, b in SESSIONS:
        sel = [t for t in trades if a <= (datetime.fromtimestamp(t["open_time"], tz=timezone.utc).hour or 24) < b]
        if sel:
            by_session[name] = {"trades": len(sel), "pnl": round(sum(t["pnl"] for t in sel), 2),
                                "win_pct": round(100 * sum(t["pnl"] > 0 for t in sel) / len(sel), 1)}
    eq = [(t, e) for t, e in curve]
    x2 = next((t for t, e in eq if e >= 2 * start_balance), None)
    return {"avg_minutes": round(float(mins.mean()), 1), "median_minutes": round(float(np.median(mins)), 1),
            "by_session": by_session, "max_equity": round(max([e for _, e in eq] or [start_balance]), 2),
            "days_to_double": round((x2 - eq[0][0]) / 86400, 1) if x2 is not None and eq else None}


def split_stats(trades: list, t_split: int) -> dict:
    """In-sample (antes de t_split) vs fuera de muestra (después): los parámetros se eligen solo con IS."""
    out = {}
    for name, part in (("is", [t for t in trades if t["open_time"] < t_split]),
                       ("oos", [t for t in trades if t["open_time"] >= t_split])):
        pnl = np.array([t["pnl"] for t in part]) if part else np.array([])
        gl = float(-pnl[pnl < 0].sum())
        out[name] = {"trades": len(part), "pnl": round(float(pnl.sum()), 2),
                     "win_pct": round(float((pnl > 0).mean()) * 100, 1) if len(pnl) else 0.0,
                     "pf": round(float(pnl[pnl > 0].sum()) / gl, 2) if gl > 0 else None}
    return out


def verdict(m: dict) -> str:
    if m["trades"] == 0:
        return "Sin operaciones"
    pf = m["profit_factor"] if m["profit_factor"] is not None else float("inf")
    years = [b for b in m["by_year"].values() if b["trades"] > 0]
    positive = sum(b["pnl"] > 0 for b in years)
    if pf >= 1.2 and m["expectancy_r"] > 0 and positive >= math.ceil(len(years) * 2 / 3):
        return "Rentable"
    if pf >= 1.0 and m["expectancy_r"] > 0:
        return "Marginal"
    return "No rentable"


# ═══════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════════════

def prepare_data(config, primary: str, years: float, refresh: bool = False, end: str = None, exec_tf: str = None):
    """Velas de las 3 temporalidades (+ la de ejecución del grid, "x"), datos del símbolo y valor real por lote."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        sys.exit(f"No se pudo conectar a MT5: {mt5.last_error()}")
    sym_name = config.SYMBOL
    if not mt5.symbol_select(sym_name, True) or mt5.symbol_info(sym_name) is None:
        sys.exit(f"{sym_name} no existe en este broker")
    info = mt5.symbol_info(sym_name)
    trend_tf, higher_tf = TF_MAP[primary]
    end = (datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end else   # --end: repetir un periodo
           datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))
    start = end - timedelta(days=round(365.25 * years))

    def warm(tf, n):                       # calentamiento para los indicadores (1.6 → fines de semana)
        return start - timedelta(minutes=TF_MIN[tf] * n * 1.6)

    frames, coverage = {}, {}
    for key, tf, n in (("p", primary, config.CANDLES_PRIMARY), ("t", trend_tf, config.CANDLES_TREND),
                       ("h", higher_tf, config.CANDLES_HIGHER), ("x", exec_tf if exec_tf != primary else None, 200)):
        if tf is None:
            frames[key] = None
            continue
        df = fetch(mt5, sym_name, tf, warm(tf, n), end, refresh)
        if df.empty:
            sys.exit(f"Sin histórico para {sym_name} {tf}")
        frames[key] = (df, close_times(df["time"].to_numpy(np.int64), tf))
        in_range = df[df["time"] >= int(start.timestamp())]
        coverage[tf] = {"bars": int(len(in_range)),
                        "from": str(pd.to_datetime(in_range["time"].iloc[0], unit="s").date()) if len(in_range) else None,
                        "to": str(pd.to_datetime(df["time"].iloc[-1], unit="s").date())}
    p = frames["p"][0]
    ref = float(p["close"].iloc[-1])
    # USD por 1.0 de precio y por lote, con el cálculo REAL de MT5 (trade_tick_value puede mentir)
    vpu = abs(mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym_name, 1.0, ref, ref + 1.0) or 0)         or info.trade_tick_value / info.trade_tick_size
    mt5.shutdown()
    sym = NS(point=info.point, digits=info.digits, trade_stops_level=info.trade_stops_level,
             trade_tick_size=info.trade_tick_size, trade_tick_value=vpu * info.trade_tick_size,
             volume_step=info.volume_step, volume_min=info.volume_min, volume_max=info.volume_max)
    need = min(config.CANDLES_PRIMARY - 1, 220)            # EMA200 + margen
    first_idx = max(int(np.searchsorted(p["time"].to_numpy(np.int64), int(start.timestamp()))), need)
    return NS(p=p, frames=frames, coverage=coverage, sym=sym, vpu=vpu, info=info, symbol=sym_name,
              start=start, end=end, first_idx=first_idx)


def exec_signals(sig: pd.DataFrame, t_close: np.ndarray, x: pd.DataFrame) -> pd.DataFrame:
    """
    Grid "analiza en el TF mayor, opera corto": la señal de la vela de análisis i se ejecuta en la primera
    vela de ejecución que abre ≥ el cierre de i, con el ATR de ejecución de la vela anterior (ya cerrada).
    Devuelve el formato de `sig` con i = índice de ejecución − 1 (simulate_grid entra en i + 1).
    """
    from bot_engine.indicators import calc_atr
    ev = sig[sig["action"].isin(["BUY", "SELL"])]
    xt = x["time"].to_numpy(np.int64)
    atr = calc_atr(x["high"], x["low"], x["close"]).to_numpy(float)
    k = np.searchsorted(xt, t_close[ev["i"].to_numpy(int)], side="left")
    ok = (k >= 1) & (k < len(xt))
    return pd.DataFrame({"i": k[ok] - 1, "action": ev["action"].to_numpy()[ok],
                         "score": ev["score"].to_numpy(float)[ok], "atr": atr[k[ok] - 1]})


def run_grid(a, config, rm, d, sig, tag, prof, overrides, balances, top_bal, t_split, t0):
    """Bot grid: simulate_grid por variante (--sweep) y balance; reporte en la clave "grid"."""
    variants = json.loads(Path(a.sweep).read_text(encoding="utf-8")) if a.sweep else [{}]
    base_cfg = {k: getattr(config, k) for k in dir(config) if k.isupper()}
    first_k = d.first_idx + 1
    sig = sig.assign(atr=pd.to_numeric(sig["atr"], errors="coerce"))
    bars, tf_min, ex_tf = d.p, TF_MIN[a.primary], a.primary
    if d.frames.get("x") is not None:                      # ejecución en un TF más corto que el análisis
        bars, ex_tf = d.frames["x"][0], getattr(config, "GRID_EXEC_TF")
        tf_min = TF_MIN[ex_tf]
        sig = exec_signals(sig, close_times(d.p["time"].to_numpy(np.int64), a.primary), bars)
        first_k = int(np.searchsorted(bars["time"].to_numpy(np.int64), int(d.start.timestamp()))) + 1
    report = {"profile": prof, "symbol": d.symbol, "mode": "grid", "tfs": [a.primary, *TF_MAP[a.primary]], "exec_tf": ex_tf,
              "period": [str(d.start.date()), str(d.end.date())], "coverage": d.coverage, "overrides": overrides,
              "is_until": _d(t_split), "value_per_price_unit_per_lot": d.vpu,
              "not_simulated": ["filtro de noticias", "order-flow", "DXY", "swaps", "comisiones", "margen",
                                "slippage (cierres de cesta al precio exacto del umbral)"],
              "grid": {}}
    for n, var in enumerate(variants):
        cfg = NS(**{**base_cfg, **{k: v for k, v in var.items() if k != "label"}})
        label = var.get("label", f"v{n}")
        res = report["grid"][label] = {"params": var}
        for bal in balances:
            trades, curve, blocked, baskets = simulate_grid(sig, bars, d.sym, d.vpu, cfg, rm, bal, first_k,
                                                            tf_min, cfg.MIN_SIGNAL_SCORE)
            m = res[f"{bal:.0f}"] = {**metrics(trades, curve, bal, with_daily=f"{bal:.0f}" == top_bal),
                                     "blocked": blocked, "split": split_stats(trades, t_split),
                                     "basket": grid_stats(baskets),
                                     "basket_split": {k: grid_stats([b for b in baskets if (b["open_time"] < t_split) == (k == "is")])
                                                      for k in ("is", "oos")}}
            if f"{bal:.0f}" == top_bal and a.mc:
                m["mc"] = monte_carlo([b["ret"] for b in baskets], a.mc, risk=1.0)
            g = m["basket"]
            print(f"  {label:<22} {bal:>7,.0f} → {m['verdict']:<15} cestas {g['baskets']:>5} "
                  f"({g.get('basket_win_pct', 0)}% ganadoras) | op {m['trades']:>5} | PF {m['profit_factor']} | "
                  f"neto {m['net_return_pct']:+.1f}% | DD {m['max_drawdown_pct']:.1f}%", flush=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{tag}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Reporte: {out} ({time.time() - t0:.0f}s)", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Backtest del motor real (+ filtro predictivo) sobre histórico de MT5.")
    ap.add_argument("profile", help="carpeta de un bot (xauusd_bot…) o perfil del panel (scalping | swing)")
    ap.add_argument("primary", choices=list(TF_MAP), help="temporalidad primaria")
    ap.add_argument("--symbol", default=None, help="activo (por defecto el SYMBOL del config)")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--balances", default="100,1000,10000")
    ap.add_argument("--ml", action="store_true", help="walk-forward del filtro predictivo")
    ap.add_argument("--mc", type=int, default=2000, help="simulaciones Monte Carlo (0 = no)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--end", default=None, metavar="AAAA-MM-DD", help="fin del periodo (por defecto hoy)")
    ap.add_argument("--signals-only", action="store_true", help="solo calcular y guardar el caché de señales")
    ap.add_argument("--sweep", default=None, metavar="JSON",
                    help="grid: archivo con una lista de variantes {label, MIN_SIGNAL_SCORE, GRID_*: …}")
    ap.add_argument("--set", action="append", default=[], metavar="CLAVE=VALOR",
                    help="sobrescribe una clave del config solo para esta prueba (p.ej. REQUIRE_MACRO_FOR_SELL=True)")
    ap.add_argument("--clf", choices=("hgb", "mlp"), default="hgb", help="clasificador del filtro predictivo (--ml)")
    ap.add_argument("--suffix", default="", help="sufijo del nombre del reporte (p.ej. _final: no pisa el barrido)")
    a = ap.parse_args()
    global CLF
    CLF = a.clf
    import ast
    overrides = {k: ast.literal_eval(v) for k, v in (kv.split("=", 1) for kv in a.set)}
    balances = [float(x) for x in a.balances.split(",")]
    top_bal = f"{max(balances):.0f}"

    config, base = load_engine(a.profile, a.primary, a.symbol, overrides)
    from bot_engine import risk_manager as rm, trade_manager as tm, ml_filter
    d = prepare_data(config, a.primary, a.years, a.refresh, a.end,
                     getattr(config, "GRID_EXEC_TF", None) if getattr(config, "USE_GRID", False)
                     else getattr(config, "ENTRY_EXEC_TF", None) or ("M1" if getattr(config, "ANOMALY_BLOCK", False) else None))
    p, frames, coverage, sym, vpu, info = d.p, d.frames, d.coverage, d.sym, d.vpu, d.info
    sym_name, start, end, first_idx = d.symbol, d.start, d.end, d.first_idx
    trend_tf, higher_tf = TF_MAP[a.primary]
    idx = list(range(first_idx, len(p) - 1))
    prof = profile_dir(a.profile).name
    tag = f"{prof}_{sym_name}_{a.primary}" + "".join(f"_{k}-{v}" for k, v in overrides.items()) + a.suffix
    tag = re.sub(r"[^\w.+-]+", "", tag.replace("/", "-"))          # listas/regímenes: nombre de archivo válido
    if len(tag) > 150:                                              # Windows: la ruta del reporte no pasa de 260
        tag = f"{tag[:110]}_{hashlib.sha1(tag.encode()).hexdigest()[:8]}{a.suffix}"
    print(f"{tag} | {a.primary}/{trend_tf}/{higher_tf or '-'} | velas: {len(idx)} | cobertura: {coverage}", flush=True)

    # ── 1. Señales (caché por huella de código + config) ────────────────────────
    sig_over = {k: v for k, v in overrides.items() if k not in POST_KEYS}
    sig_tag = f"{prof}_{sym_name}_{a.primary}" + "".join(f"_{k}-{v}" for k, v in sig_over.items())
    cache = DATA / f"signals_v{SIG_VERSION}_{sig_tag}_{start:%Y%m%d}_{end:%Y%m%d}_{engine_hash(a.profile, sig_over)}.pkl.gz"
    t0 = time.time()
    if cache.exists() and not a.refresh:
        sig = pd.read_pickle(cache)
    else:
        rows = []
        with Pool(a.workers, initializer=_init_worker, initargs=(a.profile, a.primary, a.symbol, sig_over, {k: v for k, v in frames.items() if k != "x"}, info.point)) as pool:
            for n_done, row in enumerate(pool.imap_unordered(_signal_at, idx, chunksize=64), 1):
                rows.append(row)
                if n_done % 20000 == 0:
                    print(f"  {n_done}/{len(idx)} señales ({time.time() - t0:.0f}s)", flush=True)
        sig = pd.DataFrame(rows, columns=["i", "action", "score", "atr", "feats", "macro"]).sort_values("i").reset_index(drop=True)
        DATA.mkdir(parents=True, exist_ok=True)
        sig.to_pickle(cache)
    if a.signals_only:
        print(f"  caché de señales: {cache.name} ({time.time() - t0:.0f}s)", flush=True)
        return
    t_split = int(start.timestamp() + (end - start).total_seconds() * IS_FRACTION)
    if getattr(config, "USE_GRID", False):
        return run_grid(a, config, rm, d, sig, tag, prof, overrides, balances, top_bal, t_split, t0)
    atr_at = np.full(len(p), np.nan)
    atr_at[sig["i"].to_numpy()] = pd.to_numeric(sig["atr"], errors="coerce").to_numpy(float)
    ev = sig[sig["action"].isin(["BUY", "SELL"])].reset_index(drop=True)
    print(f"  señales listas ({time.time() - t0:.0f}s) → BUY {int((ev.action == 'BUY').sum())} | "
          f"SELL {int((ev.action == 'SELL').sum())}", flush=True)

    # ── 2. Resultado de cada señal por combinación SL/TP ────────────────────────
    sp_pts = p["spread"].to_numpy(float)
    if getattr(config, "BT_REAL_SPREAD", False):
        sp_pts = real_spread(sp_pts, p["time"].to_numpy(np.int64), p["close"].to_numpy(float), sym_name)
    broker_sp = lambda pts: pts * float(getattr(config, "BT_SPREAD_MULT", 1.0)) + float(getattr(config, "BT_SPREAD_OFFSET_POINTS", 0.0))
    sp_pts = broker_sp(sp_pts)                                         # perfil de otro bróker (sim_matrix)
    arr = tuple(p[k].to_numpy(float) for k in ("open", "high", "low", "close")) + (sp_pts * info.point,)
    hold = getattr(config, "MAX_HOLD_MINUTES", None)
    ex = None
    if getattr(config, "ENTRY_EXEC_TF", None):                     # experimento: entrada afinada en un TF menor
        from bot_engine.indicators import calc_ema
        xdf = frames["x"][0]
        x_pts = xdf["spread"].to_numpy(float)
        if getattr(config, "BT_REAL_SPREAD", False):
            x_pts = real_spread(x_pts, xdf["time"].to_numpy(np.int64), xdf["close"].to_numpy(float), sym_name)
        x_pts = broker_sp(x_pts)
        ex = NS(**{k: xdf[col].to_numpy(float) for k, col in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))},
                sp=x_pts * info.point, t=xdf["time"].to_numpy(np.int64), t_prim=p["time"].to_numpy(np.int64),
                e9=calc_ema(xdf["close"], 9).to_numpy(float), e21=calc_ema(xdf["close"], 21).to_numpy(float),
                mode=getattr(config, "ENTRY_MODE", "market"), f=float(getattr(config, "ENTRY_PULLBACK_ATR", 0.25)))
    outcome = make_outcome(arr, atr_at, sym, rm, tm,
                           max(1, int(hold // TF_MIN[a.primary])) if hold else MAX_HOLD_BARS, ex)
    sides = np.where(ev["action"] == "BUY", BUY, SELL)
    combos = COMBOS if a.ml else COMBOS[:1]
    outs = {c: [outcome(int(i), int(s), *c) for i, s in zip(ev["i"], sides)] for c in combos}
    filtered = {k: sum(o == k for o in outs[COMBOS[0]]) for k in ("rr", "spread", "noexec")}

    regimes = regime_labels(p, getattr(config, "ADX_MIN_TREND", 20))
    skip_reg = set(getattr(config, "SKIP_REGIMES", ()) or ())         # mismo filtro que core en vivo
    anom_t = None
    if getattr(config, "ANOMALY_BLOCK", False):                       # mismo filtro M1 que core._anomaly_now
        from bot_engine.indicators import anomalous_bars
        mdf = frames["x"][0]
        f = anomalous_bars(mdf["high"], mdf["low"], float(getattr(config, "ANOMALY_RANGE_MULT", 3.0)),
                           int(getattr(config, "ANOMALY_LOOKBACK", 20)))
        anom_t = mdf["time"].to_numpy(np.int64)[f]                    # apertura de las velas M1 anómalas
        cool_s = int(getattr(config, "COOLING_DOWN_PERIOD", 30)) * 60
        t_open = p["time"].to_numpy(np.int64)

    def anomalous(k):
        """En vivo se miran las COOLING_DOWN_PERIOD velas M1 cerradas al abrir la vela de entrada k."""
        if anom_t is None:
            return False
        t = t_open[k]
        j = int(np.searchsorted(anom_t, t - 60, "right"))
        return j > 0 and anom_t[j - 1] >= t - cool_s

    def cands_for(plan):
        """Velas de entrada → resultado. plan None = todas las señales con el SL/TP base."""
        out = {}
        for j, (i, s) in enumerate(zip(ev["i"], sides)):
            c = COMBOS[0] if plan is None else plan.get(int(i))
            o = outs[c][j] if c in outs else None
            if isinstance(o, tuple) and str(regimes[int(i) + 1]) not in skip_reg and not anomalous(int(i) + 1):
                out[int(i) + 1] = (int(s), o[0], o[1], o[2], o[3], o[4], float(atr_at[int(i)]),
                                   (c[1] or config.TP_ATR_MULT) / (c[0] or config.SL_ATR_MULT))
        return out

    tt = p["time"].to_numpy(np.int64)
    comm, slip = getattr(config, "BT_COMMISSION_PER_LOT", 0.0), getattr(config, "BT_SLIPPAGE_POINTS", 0.0)
    report = {"profile": prof, "symbol": sym_name, "mode": "scalping" if TF_MIN[a.primary] < 60 else "swing",
              "tfs": [a.primary, trend_tf, higher_tf], "is_current_config": prof.startswith("xauusd") and a.primary == base,
              "period": [str(start.date()), str(end.date())], "coverage": coverage, "overrides": overrides,
              "signals": {"evaluated": len(idx), "BUY": int((ev.action == "BUY").sum()),
                          "SELL": int((ev.action == "SELL").sum()), "filtered": filtered},
              "value_per_price_unit_per_lot": vpu, "engine_hash": engine_hash(a.profile, overrides),
              "costs": {"spread": "real por hora" if getattr(config, "BT_REAL_SPREAD", False) else "mínimo de la vela",
                        "commission_per_lot": comm, "slippage_points_per_side": slip,
                        "swap_points_long_short": [getattr(config, "BT_SWAP_LONG_POINTS", 0.0), getattr(config, "BT_SWAP_SHORT_POINTS", 0.0)],
                        "skip_regimes": sorted(skip_reg)},
              "not_simulated": ["filtro de noticias", "order-flow", "DXY", "margen"]
                               + ([] if getattr(config, "BT_SWAP_LONG_POINTS", 0.0) else ["swaps"])
                               + ([] if comm else ["comisiones"]) + ([] if slip else ["slippage"])}

    def run_balances(key, cands, start_k):
        report[key] = {}
        for bal in balances:
            trades, curve, blocked = simulate(cands, p, sym, vpu, config, rm, bal, start_k, outcome)
            m = report[key][f"{bal:.0f}"] = {**metrics(trades, curve, bal, with_daily=f"{bal:.0f}" == top_bal),
                                             "blocked": blocked, "split": split_stats(trades, t_split),
                                             "by_regime": regime_stats(trades, regimes, tt)}
            print(f"  {key:<8} {bal:>8,.0f} → {m['verdict']:<15} op {m['trades']:>5} | acierto {m['win_rate_pct']:>5}% | "
                  f"PF {m['profit_factor']} | neto {m['net_return_pct']:+.1f}% | DD {m['max_drawdown_pct']:.1f}%", flush=True)
            if f"{bal:.0f}" == top_bal and a.mc:
                report.setdefault("mc", {})[key] = monte_carlo([t["r"] for t in trades], a.mc)

    # ── 3. Cuenta completa con el SL/TP del config, por balance ─────────────────
    base_c = cands_for(None)
    run_balances("base", base_c, first_idx + 1)

    # ── 4. Filtro predictivo walk-forward (todo fuera de muestra) ────────────────
    if a.ml and len(ev) >= 300:
        X = np.array(ev["feats"].tolist(), dtype=float)
        t_dec = close_times(tt, a.primary)[ev["i"].to_numpy()]
        plan, folds, final, test0 = walk_forward(ev["i"].to_numpy(), X, t_dec, outs, tt,
                                                 int(start.timestamp()), int(end.timestamp()))
        k0 = max(int(np.searchsorted(tt, test0)), first_idx + 1)
        report["oos_from"], report["folds"] = _d(test0), folds
        run_balances("base_oos", base_c, k0)                # misma ventana, sin filtro: comparación justa
        run_balances("ml", cands_for(plan), k0)
        top = report["ml"][top_bal]
        path = ml_filter.model_path(prof, a.primary, sym_name)
        report["model"] = None
        report["meets_target"] = bool(top["trades"] >= 20 and top["win_rate_pct"] >= TARGET_WIN * 100
                                      and (top["profit_factor"] or 0) > 1.0 and top["expectancy_r"] > 0)
        if overrides:
            pass                                           # un experimento (--set) no toca el modelo del bot
        elif final and report["meets_target"]:
            import joblib
            c, tau, clf = final
            slm, tpm = c[0] or config.SL_ATR_MULT, c[1] or config.TP_ATR_MULT
            path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump({"model": clf, "tau": tau, "sl_mult": slm, "tp_mult": tpm,
                         "features": ml_filter.FEATURE_NAMES, "trained_until": str(end.date()),
                         "symbol": sym_name, "profile": prof, "tf": a.primary,
                         "oos": {k: top[k] for k in ("trades", "win_rate_pct", "profit_factor", "expectancy_r",
                                                     "net_return_pct", "max_drawdown_pct", "verdict")}}, path)
            ml_filter.register(path)                       # sin su hash en el manifiesto, el motor no lo abre
            report["model"] = {"path": str(path.relative_to(ROOT)), "tau": tau, "sl_mult": slm, "tp_mult": tpm}
            print(f"  modelo guardado: {path.name} (τ={tau}, SL {slm} / TP {tpm} ×ATR)", flush=True)
        elif path.exists():
            path.unlink()                                  # un modelo viejo que ya no gana no debe quedar activo
            ml_filter.unregister(path)

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{tag}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Reporte: {out} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
