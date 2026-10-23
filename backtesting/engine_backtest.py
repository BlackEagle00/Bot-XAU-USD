"""
Backtest del MOTOR REAL (bot_engine) + filtro predictivo, sobre el histórico de MT5.

Uso (desde la raíz del repo, con el terminal MT5 abierto):
    python backtesting/engine_backtest.py xauusd_bot H4                    # oro, config del bot
    python backtesting/engine_backtest.py swing H1 --symbol EURUSD --ml    # perfil del panel
    opciones: --years 3  --balances 100,1000,10000  --ml  --mc 2000  --workers N  --refresh

Perfil = carpeta de un bot (usa su config.py) o "scalping" / "swing" (dashboard/profiles: el
config del oro con las claves en dólares neutralizadas, válido para cualquier activo).

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
TF_MAP = {"M5": ("M15", "H1"), "M10": ("M30", "H1"), "M15": ("H1", "H4"),
          "H1": ("H4", "D1"), "H4": ("D1", "W1"), "D1": ("W1", "MN1"), "W1": ("MN1", None)}
TF_MIN = {"M5": 5, "M10": 10, "M15": 15, "M30": 30, "H1": 60, "H4": 240,
          "D1": 1440, "W1": 10080, "MN1": 44640}
BUY, SELL = 0, 1   # = mt5.ORDER_TYPE_BUY / SELL
SIG_VERSION = 2    # formato del caché de señales (2: + tendencia del TF superior)

# (SL, TP) en múltiplos de ATR. (None, None) = los del config. TP < SL sube el acierto y baja la ganancia por operación.
COMBOS = [(None, None), (1.5, 0.5), (1.5, 0.75), (1.5, 1.0), (2.0, 0.5), (2.0, 0.75), (2.0, 1.0), (2.0, 1.5)]
TARGET_WIN    = 0.75                      # acierto mínimo FUERA de muestra para activar un modelo
VAL_WIN       = 0.80                      # en la validación interna se exige más: la precisión cae al pasar a datos nuevos
MIN_SELECTED  = 30                        # operaciones mínimas en la validación para fiarse de τ
TAU_GRID      = np.round(np.arange(0.50, 0.951, 0.025), 3)
MAX_HOLD_BARS = 500                       # tope de la triple barrera
TEST_DAYS     = 91                        # walk-forward: ventanas de prueba trimestrales
FIRST_TEST    = 0.40                      # la primera prueba empieza tras el 40% del periodo


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
    files = sorted((ROOT / "bot_engine").glob("*.py")) + [profile_dir(profile) / "config.py",
             ROOT / "dashboard" / "profiles" / "_base.py"] + [ROOT / b / "config.py" for b in
             ("xauusd_bot", "xauusd_scalping_bot", "eurusd_bot", "eurusd_scalping_bot")]
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()[:10]


# ═══════════════════════════════════════════════════════════════════════════════
# HISTÓRICO
# ═══════════════════════════════════════════════════════════════════════════════

def fetch(mt5, symbol: str, tf: str, start: datetime, end: datetime, refresh: bool) -> pd.DataFrame:
    """Velas [start, end) por tramos de 90 días (el terminal limita las velas por pedido). Con caché."""
    path = DATA / f"{symbol}_{tf}_{start:%Y%m%d}_{end:%Y%m%d}.csv.gz"
    if path.exists() and not refresh:
        return pd.read_csv(path)
    parts, t = [], start
    while t < end:
        r = mt5.copy_rates_range(symbol, getattr(mt5, f"TIMEFRAME_{tf}"), t, min(t + timedelta(days=90), end))
        if r is not None and len(r):
            parts.append(pd.DataFrame(r))
        t += timedelta(days=90)
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
    return i, s["action"], float(s["score"]), float(atr), feats, macro


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RESULTADO DE CADA SEÑAL (triple barrera con BE+/trailing)
# ═══════════════════════════════════════════════════════════════════════════════

def make_outcome(arr, atr_at, sym, rm, tm):
    """Devuelve outcome(i, side, sl_mult, tp_mult) → (R, exit_idx, entry, sl0, motivo) | 'rr' | 'spread'."""
    o, h, l, c, sp = arr
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
        if not rm.spread_ok(sp[k], risk):
            return "spread"
        pos = cur.pos = NS(ticket=0, type=side, price_open=px, sl=sl, tp=tp, price_current=px)
        last = min(len(o), k + MAX_HOLD_BARS) - 1
        for j in range(k, last + 1):
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
    return outcome


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CUENTA (niveles por capital, lote dinámico, límites)
# ═══════════════════════════════════════════════════════════════════════════════

def simulate(cands: dict, p: pd.DataFrame, sym, vpu: float, cfg, rm, balance0: float, start_idx: int):
    """
    cands = {vela de entrada k: (side, R, exit_idx, entry, sl0, motivo, atr)}.
    Devuelve (trades, curva [(time, equity)], bloqueos).
    """
    o, c = p["open"].to_numpy(float), p["close"].to_numpy(float)
    sp, tt = p["spread"].to_numpy(float) * sym.point, p["time"].to_numpy(np.int64)
    balance, open_pos, trades, curve = balance0, [], [], []
    blocked = dict(max_open=0, anti_dup=0, lot0=0, daily_halt=0)
    halt_day = day = None
    day_realized = 0.0

    def unrealized(bid, spr):
        return sum(((bid - q["entry"]) if q["side"] == BUY else (q["entry"] - bid - spr)) * q["lot"] * vpu
                   for q in open_pos)

    for k in range(start_idx, len(p)):
        d = datetime.fromtimestamp(int(tt[k]), tz=timezone.utc).date()
        if d != day:
            day, day_realized = d, 0.0
        cand = cands.get(k)
        if cand:
            side, R, exit_idx, entry, sl0, reason, atr = cand
            eq = balance + unrealized(o[k], sp[k])
            tier = rm.capital_tier(min(balance, eq))
            if halt_day != day and day_realized + eq - balance <= -tier["daily_loss"] * balance:
                halt_day = day
            mid = o[k] + sp[k] / 2
            if halt_day == day:
                blocked["daily_halt"] += 1
            elif len(open_pos) >= tier["max_open"]:
                blocked["max_open"] += 1
            elif cfg.USE_ANTI_DUPLICATE and any(q["side"] == side and abs(q["entry"] - mid) < atr * cfg.ANTI_DUP_ATR_MULT
                                                for q in open_pos):
                blocked["anti_dup"] += 1
            else:
                lot = rm.lot_plan(NS(balance=balance, equity=eq), sym, abs(entry - sl0))[0]
                if lot <= 0:
                    blocked["lot0"] += 1
                else:
                    open_pos.append(dict(side=side, R=R, exit_idx=exit_idx, entry=entry, lot=lot, open_idx=k,
                                         reason=reason, risk=abs(entry - sl0) * lot * vpu, tier=tier["name"]))
        for q in [q for q in open_pos if q["exit_idx"] == k]:
            pnl = q["R"] * q["risk"]
            balance += pnl
            day_realized += pnl
            trades.append(dict(side="BUY" if q["side"] == BUY else "SELL", open_time=int(tt[q["open_idx"]]),
                               close_time=int(tt[k]), lot=q["lot"], pnl=round(pnl, 2), r=round(q["R"], 3),
                               reason=q["reason"], bars=k - q["open_idx"] + 1, tier=q["tier"]))
            open_pos.remove(q)
        curve.append((int(tt[k]), balance + unrealized(c[k], sp[k])))
    return trades, curve, blocked


# ═══════════════════════════════════════════════════════════════════════════════
# 4. WALK-FORWARD DEL FILTRO PREDICTIVO
# ═══════════════════════════════════════════════════════════════════════════════

def _classifier():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=150, learning_rate=0.05, max_leaf_nodes=15,
                                          min_samples_leaf=40, l2_regularization=1.0, random_state=0)


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
        for j in sel:
            plan[int(ev_i[j])] = c
        folds.append({"test_from": _d(a), "test_to": _d(b), "combo": list(c), "tau": tau,
                      "selected": len(sel), "signals": int(len(test))})
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
        "max_drawdown_pct": round(max_dd * 100, 2), "sharpe": round(sharpe, 2),
        "trades": len(trades), "win_rate_pct": round(float((pnl > 0).mean() * 100), 1) if len(pnl) else 0.0,
        "profit_factor": round(gp / gl, 2) if gl > 0 else None,
        "expectancy_r": round(float(np.mean([t["r"] for t in trades])), 3) if trades else 0.0,
        "avg_bars": round(float(np.mean([t["bars"] for t in trades])), 1) if trades else 0.0,
        "worst_losing_streak": worst,
        "trades_per_month": round(len(trades) / (years * 12), 1) if years > 0 else 0.0,
        "exits": {r: sum(t["reason"] == r for t in trades) for r in ("TP", "SL", "HUECO", "TIEMPO")},
        "by_year": dict(sorted(by_year.items())), "sides": sides,
    }
    m["verdict"] = verdict(m)
    if with_daily:
        m["equity_daily"] = [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in days.items()]
    return m


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

def prepare_data(config, primary: str, years: float, refresh: bool = False):
    """Velas de las 3 temporalidades (con calentamiento), datos del símbolo y valor real por lote."""
    import MetaTrader5 as mt5
    if not mt5.initialize():
        sys.exit(f"No se pudo conectar a MT5: {mt5.last_error()}")
    sym_name = config.SYMBOL
    if not mt5.symbol_select(sym_name, True) or mt5.symbol_info(sym_name) is None:
        sys.exit(f"{sym_name} no existe en este broker")
    info = mt5.symbol_info(sym_name)
    trend_tf, higher_tf = TF_MAP[primary]
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=round(365.25 * years))

    def warm(tf, n):                       # calentamiento para los indicadores (1.6 → fines de semana)
        return start - timedelta(minutes=TF_MIN[tf] * n * 1.6)

    frames, coverage = {}, {}
    for key, tf, n in (("p", primary, config.CANDLES_PRIMARY), ("t", trend_tf, config.CANDLES_TREND),
                       ("h", higher_tf, config.CANDLES_HIGHER)):
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
    ap.add_argument("--signals-only", action="store_true", help="solo calcular y guardar el caché de señales")
    ap.add_argument("--set", action="append", default=[], metavar="CLAVE=VALOR",
                    help="sobrescribe una clave del config solo para esta prueba (p.ej. REQUIRE_MACRO_FOR_SELL=True)")
    a = ap.parse_args()
    import ast
    overrides = {k: ast.literal_eval(v) for k, v in (kv.split("=", 1) for kv in a.set)}
    balances = [float(x) for x in a.balances.split(",")]
    top_bal = f"{max(balances):.0f}"

    config, base = load_engine(a.profile, a.primary, a.symbol, overrides)
    from bot_engine import risk_manager as rm, trade_manager as tm, ml_filter
    d = prepare_data(config, a.primary, a.years, a.refresh)
    p, frames, coverage, sym, vpu, info = d.p, d.frames, d.coverage, d.sym, d.vpu, d.info
    sym_name, start, end, first_idx = d.symbol, d.start, d.end, d.first_idx
    trend_tf, higher_tf = TF_MAP[a.primary]
    idx = list(range(first_idx, len(p) - 1))
    prof = profile_dir(a.profile).name
    tag = f"{prof}_{sym_name}_{a.primary}" + "".join(f"_{k}-{v}" for k, v in overrides.items())
    print(f"{tag} | {a.primary}/{trend_tf}/{higher_tf or '-'} | velas: {len(idx)} | cobertura: {coverage}", flush=True)

    # ── 1. Señales (caché por huella de código + config) ────────────────────────
    cache = DATA / f"signals_v{SIG_VERSION}_{tag}_{start:%Y%m%d}_{end:%Y%m%d}_{engine_hash(a.profile, overrides)}.pkl.gz"
    t0 = time.time()
    if cache.exists() and not a.refresh:
        sig = pd.read_pickle(cache)
    else:
        rows = []
        with Pool(a.workers, initializer=_init_worker, initargs=(a.profile, a.primary, a.symbol, overrides, frames, info.point)) as pool:
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
    atr_at = np.full(len(p), np.nan)
    atr_at[sig["i"].to_numpy()] = pd.to_numeric(sig["atr"], errors="coerce").to_numpy(float)
    ev = sig[sig["action"].isin(["BUY", "SELL"])].reset_index(drop=True)
    print(f"  señales listas ({time.time() - t0:.0f}s) → BUY {int((ev.action == 'BUY').sum())} | "
          f"SELL {int((ev.action == 'SELL').sum())}", flush=True)

    # ── 2. Resultado de cada señal por combinación SL/TP ────────────────────────
    arr = tuple(p[k].to_numpy(float) for k in ("open", "high", "low", "close")) + (p["spread"].to_numpy(float) * info.point,)
    outcome = make_outcome(arr, atr_at, sym, rm, tm)
    sides = np.where(ev["action"] == "BUY", BUY, SELL)
    combos = COMBOS if a.ml else COMBOS[:1]
    outs = {c: [outcome(int(i), int(s), *c) for i, s in zip(ev["i"], sides)] for c in combos}
    filtered = {"rr": sum(o == "rr" for o in outs[COMBOS[0]]), "spread": sum(o == "spread" for o in outs[COMBOS[0]])}

    def cands_for(plan):
        """Velas de entrada → resultado. plan None = todas las señales con el SL/TP base."""
        out = {}
        for j, (i, s) in enumerate(zip(ev["i"], sides)):
            c = COMBOS[0] if plan is None else plan.get(int(i))
            o = outs[c][j] if c in outs else None
            if isinstance(o, tuple):
                out[int(i) + 1] = (int(s), o[0], o[1], o[2], o[3], o[4], float(atr_at[int(i)]))
        return out

    tt = p["time"].to_numpy(np.int64)
    report = {"profile": prof, "symbol": sym_name, "mode": "scalping" if TF_MIN[a.primary] < 60 else "swing",
              "tfs": [a.primary, trend_tf, higher_tf], "is_current_config": prof.startswith("xauusd") and a.primary == base,
              "period": [str(start.date()), str(end.date())], "coverage": coverage, "overrides": overrides,
              "signals": {"evaluated": len(idx), "BUY": int((ev.action == "BUY").sum()),
                          "SELL": int((ev.action == "SELL").sum()), "filtered": filtered},
              "value_per_price_unit_per_lot": vpu,
              "not_simulated": ["filtro de noticias", "order-flow", "DXY", "swaps", "comisiones", "margen"]}

    def run_balances(key, cands, start_k):
        report[key] = {}
        for bal in balances:
            trades, curve, blocked = simulate(cands, p, sym, vpu, config, rm, bal, start_k)
            m = report[key][f"{bal:.0f}"] = {**metrics(trades, curve, bal, with_daily=f"{bal:.0f}" == top_bal),
                                             "blocked": blocked}
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
