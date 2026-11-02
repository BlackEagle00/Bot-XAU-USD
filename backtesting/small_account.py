"""
Cuentas chicas (50–300 USD) con la volatilidad ACTUAL del oro: ¿con qué tope de riesgo por operación
sobrevive cada bot?

Uso (desde la raíz, con el terminal MT5 abierto):
    python backtesting/small_account.py              # los 3 bots → reports/small_account.md + .json
    python backtesting/small_account.py --summary    # solo rehace el resumen

Con 0.01 lote, el stop del oro cuesta hoy 10–25 USD. Con poco capital el bot solo opera si se le permite
arriesgar más del 1 % (MAX_RISK_MIN_LOT; en el grid, GRID_MAX_RISK_MIN_LOT). Aquí se mide cuánto:
  · Último año (la volatilidad de hoy, no la de 2023). Una cuenta arranca cada STEP_DAYS días y corre
    HORIZON_DAYS días → P(quema) = % de arranques que terminan con ≤ 25 % del capital inicial.
  · Topes CAPS × corte total MAX_DD_PCT (CUTS; el grid ya trae su corte del −30 %) × balances.
Regla de elección (fijada antes de ver los números): el tope/corte con mejor equity mediana a 100 USD
entre los que operan en ≥ 50 % de los arranques con 50 USD y tienen P(quema) ≤ 20 % con 50 y con 100 USD.
Si ninguno cumple: el de menor P(quema) que opere con 50 USD, marcado ⚠.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_backtest as bt   # noqa: E402

BOTS = {"swing": ("xauusd_bot", "H1", "MAX_RISK_MIN_LOT"),
        "scalping": ("xauusd_scalping_bot", "M15", "MAX_RISK_MIN_LOT")}   # grid retirado el 2026-10-26
CAPS = (0.10, 0.15, 0.25, 0.35, 0.50)
CUTS = (None, 0.50, 0.30)
BALANCES = (50, 100, 200, 300)
YEARS, STEP_DAYS, HORIZON_DAYS = 1.0, 14, 90
BURN = 0.25                       # terminar con ≤ 25 % del capital inicial = cuenta quemada
MAX_BURN, MIN_TRADED = 0.20, 0.50


def stats(runs: list, start: float) -> dict:
    """runs = [(equity final, DD máx %, operaciones)] de cada arranque."""
    fin = np.array([r[0] for r in runs], float) / start
    return {"starts": len(runs), "p_burn": round(float((fin <= BURN).mean()), 3),
            "p_loss": round(float((fin < 1).mean()), 3), "ret_p50": round(float(np.median(fin) - 1) * 100, 1),
            "dd_p50": round(float(np.median([r[1] for r in runs])), 1),
            "traded": round(float(np.mean([r[2] > 0 for r in runs])), 3)}


def choose(rows: dict):
    """rows = {"cap|cut": {"50": stats, "100": stats, …}} → (clave elegida, cumple la regla)."""
    ok = [k for k, r in rows.items() if r["50"]["traded"] >= MIN_TRADED
          and r["50"]["p_burn"] <= MAX_BURN and r["100"]["p_burn"] <= MAX_BURN]
    if ok:
        return max(ok, key=lambda k: rows[k]["100"]["ret_p50"]), True
    live = [k for k in rows if rows[k]["50"]["traded"] > 0] or list(rows)
    return min(live, key=lambda k: (rows[k]["50"]["p_burn"] + rows[k]["100"]["p_burn"], -rows[k]["100"]["ret_p50"])), False


def run_bot(name: str) -> dict:
    prof, tf, cap_key = BOTS[name]
    config, _ = bt.load_engine(prof, tf)
    from bot_engine import risk_manager as rm, trade_manager as tm
    d = bt.prepare_data(config, tf, YEARS)
    cache = bt.DATA / (f"signals_v{bt.SIG_VERSION}_{prof}_{d.symbol}_{tf}_{d.start:%Y%m%d}_{d.end:%Y%m%d}_"
                       f"{bt.engine_hash(prof, {})}.pkl.gz")
    if not cache.exists():
        subprocess.run([sys.executable, str(Path(__file__).with_name("engine_backtest.py")), prof, tf,
                        "--years", str(YEARS), "--signals-only"], check=True, cwd=bt.ROOT)
    sig = pd.read_pickle(cache).assign(atr=lambda s: pd.to_numeric(s["atr"], errors="coerce"))
    p, sym, vpu = d.p, d.sym, d.vpu
    tt = p["time"].to_numpy(np.int64)
    grid = getattr(config, "USE_GRID", False)
    if not grid:                                          # resultado de cada señal con el SL/TP del config
        atr_at = np.full(len(p), np.nan)
        atr_at[sig["i"].to_numpy()] = sig["atr"].to_numpy(float)
        ev = sig[sig["action"].isin(["BUY", "SELL"])]
        arr = tuple(p[k].to_numpy(float) for k in ("open", "high", "low", "close")) + (p["spread"].to_numpy(float) * sym.point,)
        outcome = bt.make_outcome(arr, atr_at, sym, rm, tm)
        cands = {}
        for i, a in zip(ev["i"], ev["action"]):
            s = bt.BUY if a == "BUY" else bt.SELL
            o = outcome(int(i), s, *bt.COMBOS[0])
            if isinstance(o, tuple):
                cands[int(i) + 1] = (s, o[0], o[1], o[2], o[3], o[4], float(atr_at[int(i)]))
    t_first, t_end = int(d.start.timestamp()), int(d.end.timestamp())
    starts = range(t_first, t_end - HORIZON_DAYS * 86400 + 1, STEP_DAYS * 86400)
    windows = [(max(int(np.searchsorted(tt, s)), d.first_idx + 1), int(np.searchsorted(tt, s + HORIZON_DAYS * 86400)))
               for s in starts]
    cuts = (None,) if grid else CUTS
    out = {"bot": name, "profile": prof, "tf": tf, "period": [str(d.start.date()), str(d.end.date())],
           "starts": len(windows), "horizon_days": HORIZON_DAYS, "rows": {}}
    for cap in CAPS:
        setattr(config, cap_key, cap)                      # risk_manager y grid leen el config en vivo
        for cut in cuts:
            config.MAX_DD_PCT = cut
            row = out["rows"][f"{cap}|{cut}"] = {}
            for bal in BALANCES:
                runs = []
                for k0, k1 in windows:
                    pw = p.iloc[:k1]
                    if grid:
                        trades, curve, _, _ = bt.simulate_grid(sig[sig["i"] < k1 - 1], pw, sym, vpu, config, rm,
                                                                float(bal), k0, bt.TF_MIN[tf])
                    else:
                        trades, curve, _ = bt.simulate(cands, pw, sym, vpu, config, rm, float(bal), k0, outcome)
                    eq = np.array([e for _, e in curve] or [bal], float)
                    dd = float(((np.maximum.accumulate(eq) - eq) / np.maximum.accumulate(eq)).max() * 100)
                    runs.append((float(eq[-1]), dd, len(trades)))
                row[str(bal)] = stats(runs, bal)
            print(f"  {name} tope {cap:.0%} corte {cut}: " + " | ".join(
                f"{b}: quema {row[str(b)]['p_burn']:.0%} med {row[str(b)]['ret_p50']:+.0f}% opera {row[str(b)]['traded']:.0%}"
                for b in BALANCES), flush=True)
    key, ok = choose(out["rows"])
    out["chosen"], out["meets_rule"] = key, ok
    return out


def markdown(res: dict) -> str:
    L = ["# Cuentas chicas — volatilidad actual (último año)", "",
         f"Arranques cada {STEP_DAYS} días, {HORIZON_DAYS} días cada uno. **Quema** = termina con ≤ {BURN:.0%} del "
         "capital. Celdas: P(quema) · retorno mediano · % de arranques que operaron.", ""]
    for name, r in res.items():
        cap, cut = r["chosen"].split("|")
        L += [f"## {name} ({r['profile']} {r['tf']}, {r['period'][0]} → {r['period'][1]}, {r['starts']} arranques)", "",
              f"**Elegido:** tope {float(cap):.0%}, corte total {cut}" + ("" if r["meets_rule"] else
              " — ⚠ ninguno cumple P(quema) ≤ 20 % con 50 y 100 USD: es el menos malo"), "",
              "| Tope | Corte | " + " | ".join(f"{b} USD" for b in BALANCES) + " |", "|---|---|" + "---|" * len(BALANCES)]
        for k, row in r["rows"].items():
            c, u = k.split("|")
            mark = " **←**" if k == r["chosen"] else ""
            L.append(f"| {float(c):.0%}{mark} | {u} | " + " | ".join(
                f"{row[str(b)]['p_burn']:.0%} · {row[str(b)]['ret_p50']:+.0f}% · {row[str(b)]['traded']:.0%}" for b in BALANCES) + " |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Riesgo de quemar cuentas chicas por bot y tope.")
    ap.add_argument("--bot", choices=list(BOTS), help="(interno) corre un solo bot en este proceso")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    if a.bot:                                              # un config por proceso (el motor importa `config`)
        (bt.REPORTS / f"_small_{a.bot}.json").write_text(json.dumps(run_bot(a.bot), ensure_ascii=False), encoding="utf-8")
        return
    if not a.summary:
        for name in BOTS:
            print(f"=== {name} ===", flush=True)
            subprocess.run([sys.executable, __file__, "--bot", name], check=True, cwd=bt.ROOT)
    res = {n: json.loads((bt.REPORTS / f"_small_{n}.json").read_text(encoding="utf-8")) for n in BOTS
           if (bt.REPORTS / f"_small_{n}.json").exists()}
    (bt.REPORTS / "small_account.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (bt.REPORTS / "small_account.md").write_text(markdown(res), encoding="utf-8")
    print(f"Resumen: {bt.REPORTS / 'small_account.md'}")


if __name__ == "__main__":
    main()
