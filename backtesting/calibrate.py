"""
Calibración por CLASE de activo con walk-forward (sin mirar el futuro).

Uso (desde la raíz del repo, con MT5 abierto), un proceso por perfil:
    python backtesting/calibrate.py forex_swing            # muestra la calibración
    python backtesting/calibrate.py forex_swing --write    # y la escribe en su config.py

Antes hay que tener el caché de señales con umbral ≈ 0 de cada activo y TF del perfil:
    python backtesting/engine_backtest.py forex_swing H1 --symbol EURUSD --set MIN_SIGNAL_SCORE=0.01 --signals-only

Por qué funciona con un solo cálculo del motor: con umbral ≈ 0 el caché guarda la dirección y el
score de cada vela, y los filtros del motor (tendencia, RSI, ADX, macro) no dependen del umbral, así
que la acción con umbral U es la misma acción si |score| ≥ U (probado en tests/test_engine.py).
"Ventas solo con macro bajista" también se aplica después, con la tendencia superior guardada.

Rejilla: umbral de score × ventas solo con macro bajista × SL/TP (COMBOS) × TF (swing: H1/H4).
Walk-forward trimestral con purga: en cada ventana se elige, con el pasado y SUMANDO todos los
activos de la clase, la combinación de mayor R total (≥ MIN_TRADES operaciones) y se mide el
trimestre siguiente. Se compara contra los parámetros actuales en las mismas ventanas.
"""
import argparse
import itertools
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_backtest as bt   # noqa: E402

THRESHOLDS = (3.0, 4.0, 5.0, 6.0, 7.0)
MIN_TRADES = 30                   # en la ventana de entrenamiento, sumando la clase
TFS_BY_MODE = {"scalping": ("M15",), "swing": ("H1", "H4")}
MARK = "    # ── Parámetros calibrados para esta clase (backtesting/calibrate.py) ──\n"


def selected(score_abs, side, macro, R, thr: float, macro_sell: bool):
    """Señales que el motor tomaría con ese umbral y regla de ventas (y cuyo resultado existe)."""
    keep = (score_abs >= thr) & ~np.isnan(R)
    if macro_sell:
        keep &= ~((side == bt.SELL) & (macro != "down"))
    return keep


def summarize(rs) -> dict:
    rs = np.asarray(rs, float)
    if not len(rs):
        return {"trades": 0, "win_pct": 0.0, "pf": None, "exp_r": 0.0, "total_r": 0.0}
    gp, gl = rs[rs > 0].sum(), -rs[rs < 0].sum()
    return {"trades": int(len(rs)), "win_pct": round(float((rs > 0).mean()) * 100, 1),
            "pf": round(float(gp / gl), 2) if gl > 0 else None, "exp_r": round(float(rs.mean()), 3),
            "total_r": round(float(rs.sum()), 1)}


def apply_params(text: str, params: dict, comment: str) -> str:
    """Escribe los parámetros calibrados en el config de un perfil (reemplaza los anteriores)."""
    params = dict(params)
    tf = params.pop("tf")
    text = re.sub(r'tf="[A-Z0-9]+"', f'tf="{tf}"', text, count=1)
    head, sep, tail = text.partition(MARK)
    if not sep:
        raise ValueError("el config no tiene la marca de parámetros calibrados")
    tail = tail[tail.index("))"):]                       # descarta la calibración anterior
    lines = [f"    # {comment}\n"] + [f"    {k}={v!r},\n" for k, v in params.items()]
    return head + MARK + "".join(lines) + tail


def load_class(profile: str, config, rm, tm, symbols, tfs, years: float):
    """Por (símbolo, TF): arrays de las señales con su resultado para cada combinación SL/TP."""
    out = {}
    prof = bt.profile_dir(profile).name
    for sym_name, tf in itertools.product(symbols, tfs):
        pattern = f"signals_v{bt.SIG_VERSION}_{prof}_{sym_name}_{tf}_MIN_SIGNAL_SCORE-0.01_*.pkl.gz"
        files = sorted(bt.DATA.glob(pattern), key=lambda f: f.stat().st_mtime)
        if not files:
            print(f"  ! falta el caché de {sym_name} {tf}: corre engine_backtest.py --signals-only", flush=True)
            continue
        config.SYMBOL = sym_name
        d = bt.prepare_data(config, tf, years)
        sig = pd.read_pickle(files[-1])
        atr_at = np.full(len(d.p), np.nan)
        atr_at[sig["i"].to_numpy()] = pd.to_numeric(sig["atr"], errors="coerce").to_numpy(float)
        ev = sig[sig["action"].isin(["BUY", "SELL"])].reset_index(drop=True)
        arr = tuple(d.p[k].to_numpy(float) for k in ("open", "high", "low", "close")) + \
            (d.p["spread"].to_numpy(float) * d.info.point,)
        outcome = bt.make_outcome(arr, atr_at, d.sym, rm, tm)
        sides = np.where(ev["action"] == "BUY", bt.BUY, bt.SELL)
        tt = d.p["time"].to_numpy(np.int64)
        R, T_exit = {}, {}
        for c in bt.COMBOS:
            res = [outcome(int(i), int(s), *c) for i, s in zip(ev["i"], sides)]
            R[c] = np.array([o[0] if isinstance(o, tuple) else np.nan for o in res])
            T_exit[c] = np.array([tt[o[1]] if isinstance(o, tuple) else np.iinfo(np.int64).max for o in res])
        out[(sym_name, tf)] = dict(score=ev["score"].abs().to_numpy(float), side=sides,
                                   macro=ev["macro"].to_numpy(), t=bt.close_times(tt, tf)[ev["i"].to_numpy()],
                                   R=R, T_exit=T_exit, start=int(d.start.timestamp()), end=int(d.end.timestamp()))
        print(f"  {sym_name} {tf}: {len(ev)} señales", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description="Calibra un perfil de clase con walk-forward.")
    ap.add_argument("profile", help="forex_swing | forex_scalping | metals_swing | … (dashboard/profiles)")
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--write", action="store_true", help="escribir los parámetros elegidos en el config del perfil")
    a = ap.parse_args()

    import MetaTrader5 as mt5
    cfg_path = bt.profile_dir(a.profile) / "config.py"
    config, _ = bt.load_engine(a.profile, "H1" if "swing" in a.profile else "M15")
    from bot_engine import risk_manager as rm, trade_manager as tm
    symbols = [s for group in config.SECTIONS.values() for s in group]
    current_tf = next(k for k in bt.TF_MIN if getattr(mt5, f"TIMEFRAME_{k}", None) == config.PRIMARY_TF)
    base = {"tf": current_tf, "thr": float(config.MIN_SIGNAL_SCORE),
            "macro_sell": bool(getattr(config, "REQUIRE_MACRO_FOR_SELL", False)), "combo": bt.COMBOS[0]}
    print(f"Calibrando {a.profile}: {symbols} | actual: {base}", flush=True)

    data = load_class(a.profile, config, rm, tm, symbols, TFS_BY_MODE[config.MODE], a.years)
    if not data:
        sys.exit("Sin datos para calibrar.")
    grid = [{"tf": tf, "thr": thr, "macro_sell": ms, "combo": c}
            for tf in TFS_BY_MODE[config.MODE] for thr in THRESHOLDS for ms in (False, True) for c in bt.COMBOS]

    def trades(params, lo, hi, train: bool):
        """R de las operaciones de la clase con esos parámetros, decididas en [lo, hi)."""
        rs = []
        for (_, tf), dd in data.items():
            if tf != params["tf"]:
                continue
            c = params["combo"]
            keep = selected(dd["score"], dd["side"], dd["macro"], dd["R"][c], params["thr"], params["macro_sell"])
            keep &= (dd["t"] >= lo) & (dd["t"] < hi)
            if train:
                keep &= dd["T_exit"][c] < hi                # purga: solo operaciones ya terminadas
            rs.extend(dd["R"][c][keep].tolist())
        return rs

    start = min(dd["start"] for dd in data.values())
    end = max(dd["end"] for dd in data.values())
    folds, oos, oos_base = [], [], []
    for a_, b_ in bt.wf_folds(start, end):
        best, best_r = None, -np.inf
        for params in grid:
            rs = trades(params, start, a_, train=True)
            if len(rs) >= MIN_TRADES and sum(rs) > best_r:
                best, best_r = params, sum(rs)
        test_base = trades(base, a_, b_, train=False)
        oos_base.extend(test_base)
        if best is None:
            folds.append({"test_from": bt._d(a_), "test_to": bt._d(b_), "params": None})
            continue
        test = trades(best, a_, b_, train=False)
        oos.extend(test)
        folds.append({"test_from": bt._d(a_), "test_to": bt._d(b_),
                      "params": {**best, "combo": list(best["combo"])}, "oos": summarize(test),
                      "oos_base": summarize(test_base)})
        print(f"    {bt._d(a_)}→{bt._d(b_)}: {best['tf']} umbral {best['thr']} macro-venta {best['macro_sell']} "
              f"SL/TP {best['combo']} → {summarize(test)}", flush=True)

    # Elección final: la mejor con TODO el histórico (lo que se usará desde hoy)
    final = max((p for p in grid if len(trades(p, start, end + 1, True)) >= MIN_TRADES),
                key=lambda p: sum(trades(p, start, end + 1, True)), default=None)
    res = {"profile": a.profile, "symbols": symbols, "current": {**base, "combo": list(base["combo"])},
           "chosen": {**final, "combo": list(final["combo"])} if final else None,
           "oos": summarize(oos), "baseline_oos": summarize(oos_base), "folds": folds,
           "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    print(f"Fuera de muestra → calibrado {res['oos']} | actual {res['baseline_oos']}", flush=True)
    # mejor = más ganancia por operación Y mejor PF: si todo pierde, "menos R total" solo premiaría operar menos
    o, b = res["oos"], res["baseline_oos"]
    better = bool(final) and o["trades"] >= MIN_TRADES and o["exp_r"] > b["exp_r"] and (o["pf"] or 0) > (b["pf"] or 0)
    res["written"] = bool(a.write and better)       # el panel muestra el resultado de lo que quedó vigente
    bt.REPORTS.mkdir(parents=True, exist_ok=True)
    (bt.REPORTS / f"calibration_{a.profile}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")

    if a.write and better:
        slm, tpm = final["combo"]
        params = {"tf": final["tf"], "MIN_SIGNAL_SCORE": final["thr"], "REQUIRE_MACRO_FOR_SELL": final["macro_sell"]}
        if slm:
            params.update(SL_ATR_MULT=slm, TP_ATR_MULT=tpm, MIN_RR=round(min(config.MIN_RR, tpm / slm * 0.9), 2))
        comment = (f"{res['date']} · fuera de muestra: PF {o['pf']}, acierto {o['win_pct']}%, {o['trades']} op, "
                   f"{o['total_r']}R (antes: PF {b['pf']}, {b['total_r']}R)")
        cfg_path.write_text(apply_params(cfg_path.read_text(encoding="utf-8"), params, comment), encoding="utf-8")
        print(f"  escrito en {cfg_path.relative_to(bt.ROOT)}: {params}", flush=True)
    elif a.write:
        print("  no mejora a los parámetros actuales fuera de muestra: config sin cambios", flush=True)


if __name__ == "__main__":
    main()
