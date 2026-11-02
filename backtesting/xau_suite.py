"""
Suite XAUUSD: los 3 bots en las temporalidades de scalping + un resumen comparable, con foco en
que la cuenta NO se queme (drawdown, cortes por drawdown, cestas perdidas) desde 50 USD.

Uso (desde la raíz, con el terminal MT5 abierto):
    python backtesting/xau_suite.py                 # corre todo y escribe reports/xau_suite.md + .json
    python backtesting/xau_suite.py --only grid     # solo un bot (scalping | swing | grid)
    python backtesting/xau_suite.py --tfs M15,H1    # solo esas temporalidades
    python backtesting/xau_suite.py --summary       # no corre nada: solo rehace el resumen

Qué corre (engine_backtest.py, balances 50 / 100 / 1 000 / 10 000):
  • Scalping  (xauusd_scalping_bot) en M1, M5, M15 — con su config (sin ajuste de cuenta pequeña) y, para
    comparar, con él (--set MICRO_SL_FIT=True; reusa el caché de señales).
  • Swing     (xauusd_bot) en H1 — igual.
  • Grid      (xauusd_grid_bot): cada trabajo es "ANÁLISIS[>EJECUCIÓN][:range]" — p.ej. "H1>M1" analiza en
    H1/H4/D1 y opera con el ATR de M1 (GRID_EXEC_TF); ":range" usa GRID_REGIME="range". Señales a
    MIN_SIGNAL_SCORE=0.01 una sola vez y un barrido (sweep) de umbral × espaciado × TP de cesta (en R) ×
    lote fijo/martingala × riesgo por cesta (+ vida máxima de la cesta si se opera corto).
M1: MT5 guarda pocas velas de 1 minuto (~100 000 → unos 3 meses), por eso M1 usa --years 0.27.
Elección honesta: la variante del grid se elige SOLO con la parte in-sample (60% inicial) en 1 000 USD,
descartando las que activaron el corte por drawdown antes de terminar el in-sample. Lo que se reporta
como resultado es su parte fuera de muestra (40% final), que no participó en la elección.
"""
import argparse
import itertools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "backtesting" / "reports"
TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}
YEARS = {"M1": 0.27}                       # el resto: 3 años (un trabajo con M1 en cualquier lado usa 0.27)
BAL = "1000"                               # balance de referencia para elegir
BALANCES = ("50", "100", "1000", "10000")
JOBS = {"scalping": ("xauusd_scalping_bot", ["M5", "M15"]),
        "swing":    ("xauusd_bot", ["H4"]),
        "grid":     ("xauusd_grid_bot", ["M5", "M5>M1", "M1", "M5:range", "M1:range", "H1>M5", "H1>M1", "H1"])}
JOBS = {k: v for k, v in JOBS.items() if (ROOT / v[0]).exists()}   # grid retirado el 2026-10-26 (en ../_archivo_otros_activos)
MICRO = "_MICRO_SL_FIT-True"


def parse(spec: str):
    """"H1>M1:range" → ("H1", "M1", "range"); "M5" → ("M5", None, None)."""
    tf, _, regime = spec.partition(":")
    primary, _, ex = tf.partition(">")
    return primary, ex or None, regime or None


def sweep(spec: str) -> list:
    """Variantes del grid. Corto (ejecución < H1): vida de cesta 30/120 min y martingala ×1.5/×2 (escalado
    exponencial). H1: 48 velas, como en 2026-10-23. Stop 1×ATR tras el último nivel."""
    primary, ex, _ = parse(spec)
    if TF_MIN[ex or primary] < 60:
        return [{"label": f"{mode[:5]}{mult if mode != 'fixed' else ''} s{thr} e{sp} tp{tp_r}R r{risk * 100:g}% {mins}m",
                 "MIN_SIGNAL_SCORE": thr, "GRID_SPACING_ATR": sp, "GRID_TRADE_TP_ATR": sp, "GRID_BASKET_TP_R": tp_r,
                 "GRID_LOT_MODE": mode, "GRID_LOT_MULT": mult, "GRID_RISK_PCT": risk, "GRID_MAX_MINUTES": mins}
                for thr, sp, tp_r, (mode, mult), risk, mins in itertools.product(
                    (2.0, 4.0), (1.0, 2.0), (0.25, 0.5), (("fixed", 1.0), ("martingale", 1.5), ("martingale", 2.0)),
                    (0.02, 0.05), (30, 120))]
    tf = primary
    return [{"label": f"{mode[:5]} s{thr} e{spacing} tp{tp_r}R r{risk * 100:g}%", "MIN_SIGNAL_SCORE": thr,
             "GRID_SPACING_ATR": spacing, "GRID_TRADE_TP_ATR": spacing, "GRID_BASKET_TP_R": tp_r,
             "GRID_LOT_MODE": mode, "GRID_RISK_PCT": risk, "GRID_MAX_MINUTES": 48 * TF_MIN[tf]}
            for thr, spacing, tp_r, mode, risk in itertools.product((2.0, 4.0), (0.5, 1.0), (0.25, 0.5, 1.0),
                                                                    ("fixed", "martingale"), (0.02, 0.04))]


def grid_sets(spec: str) -> list:
    """--set del trabajo de grid, en el orden que forma el nombre del reporte en engine_backtest."""
    _, ex, regime = parse(spec)
    return (["MIN_SIGNAL_SCORE=0.01"] + ([f"GRID_EXEC_TF='{ex}'"] if ex else [])
            + ([f"GRID_REGIME='{regime}'"] if regime else []))


def report_path(bot: str, tf: str, suffix: str = "") -> Path:
    if bot == "grid":
        suffix = "".join("_" + kv.replace("=", "-").replace("'", "") for kv in grid_sets(tf))
        tf = parse(tf)[0]
    return REPORTS / f"{JOBS[bot][0]}_XAUUSD_{tf}{suffix}.json"


def run(bot: str, tf: str) -> None:
    primary = parse(tf)[0]
    base = [sys.executable, str(ROOT / "backtesting" / "engine_backtest.py"), JOBS[bot][0], primary,
            "--years", str(0.27 if "M1" in re.split("[>:]", tf) else 3.0), "--balances", ",".join(BALANCES)]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if bot == "grid":
        sw = REPORTS / f"_sweep_{tf.replace('>', '-').replace(':', '-')}.json"
        REPORTS.mkdir(parents=True, exist_ok=True)
        sw.write_text(json.dumps(sweep(tf)), encoding="utf-8")
        # el barrido se elige en 1 000 USD (pick): solo ese balance; la elegida se repite con todos (--suffix _final)
        runs = [base[:-1] + [BAL, "--mc", "0"] + sum((["--set", kv] for kv in grid_sets(tf)), []) + ["--sweep", str(sw)]]
    else:
        runs = [base, base + ["--set", "MICRO_SL_FIT=True"]]
    for cmd in runs:
        print(f"\n=== {bot} {tf} {' '.join(cmd[7:])} ===", flush=True)
        subprocess.run(cmd, check=True, cwd=ROOT, env=env)


# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN
# ═══════════════════════════════════════════════════════════════════════════════

def _row(m: dict) -> dict:
    sp = m.get("split", {})
    return {"verdict": m["verdict"], "trades": m["trades"], "win_pct": m["win_rate_pct"], "pf": m["profit_factor"],
            "net_pct": m["net_return_pct"], "dd_pct": m["max_drawdown_pct"], "avg_min": m.get("avg_minutes"),
            "trades_month": m["trades_per_month"], "pf_is": sp.get("is", {}).get("pf"),
            "pf_oos": sp.get("oos", {}).get("pf"), "oos_pnl": sp.get("oos", {}).get("pnl"),
            "halted_at": m.get("blocked", {}).get("halted_at"), "micro_sl": m.get("blocked", {}).get("micro_sl", 0),
            "lot0": m.get("blocked", {}).get("lot0", 0)}


def pick(variants: dict, mode: str, is_until: str):
    """Mejor variante del modo por PF in-sample (≥ 30 cestas IS, sin corte por drawdown dentro del IS)."""
    best = None
    for label, v in variants.items():
        if v["params"].get("GRID_LOT_MODE") != mode:
            continue
        m = v[BAL]
        halted = m["blocked"].get("halted_at")
        pf = m["split"]["is"]["pf"] or 0
        if m["basket_split"]["is"].get("baskets", 0) >= 30 and not (halted and halted <= is_until) \
                and (best is None or pf > best[1]):
            best = (label, pf)
    return best and best[0]


def summarize() -> dict:
    out = {"balance": BAL, "scalping": {}, "swing": {}, "grid": {}}
    for bot in ("scalping", "swing"):
        for tf in JOBS[bot][1]:
            for key, suffix in (("sin_ajuste", ""), ("micro", MICRO)):
                f = report_path(bot, tf, suffix)
                if f.exists():
                    r = json.loads(f.read_text(encoding="utf-8"))
                    out[bot].setdefault(tf, {"period": r["period"]})[key] = {b: _row(m) for b, m in r["base"].items()}
    for tf in JOBS.get("grid", ("", []))[1]:
        f = report_path("grid", tf)
        if not f.exists():
            continue
        r = json.loads(f.read_text(encoding="utf-8"))
        g, entry = r["grid"], {"period": r["period"], "is_until": r.get("is_until"), "variants": {}}
        for label, v in g.items():
            m = v[BAL]
            entry["variants"][label] = {**_row(m), "baskets": m["basket"].get("baskets", 0),
                                        "basket_win_pct": m["basket"].get("basket_win_pct")}
        for mode in ("fixed", "martingale"):
            label = pick(g, mode, entry["is_until"])
            if label:
                v = g[label]
                entry[f"best_{mode}"] = {"label": label, "params": v["params"],
                                         **{b: {**_row(v[b]), "basket": v[b]["basket"],
                                                "oos_baskets": v[b]["basket_split"]["oos"],
                                                "mc": v[b].get("mc") or v.get("10000", {}).get("mc"),
                                                "by_session": v[b].get("by_session"),
                                                "days_to_double": v[b].get("days_to_double")}
                                            for b in BALANCES if b in v}}
        out["grid"][tf] = entry
    return out


def _f(x, nd=2):
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _cell(m: dict) -> str:
    """Neto / DD de un balance, marcando la cuenta quemada o detenida por el corte."""
    if not m:
        return "—"
    if m["trades"] == 0:
        return "no opera"
    burned = " **quemada**" if m["net_pct"] <= -90 else (" (corte DD)" if m.get("halted_at") else "")
    return f"{m['net_pct']:+.0f}% / DD {m['dd_pct']:.0f}%{burned}"


def markdown(s: dict) -> str:
    L = ["# Suite XAUUSD — que la cuenta no se queme", "",
         "Celdas: **neto / drawdown máximo** por balance inicial. PF IS/OOS = profit factor en el 60% inicial / "
         "40% final (1 000 USD). Costos: spread real por vela; sin comisiones, swaps, slippage ni margen.", ""]
    for bot, title in (("scalping", "Scalping"), ("swing", "Swing")):
        L += [f"## {title}", "",
              "| TF | Variante | 50 USD | 100 USD | 1 000 USD | 10 000 USD | PF IS→OOS | Op. (1 000) | SL cuenta pequeña (50) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for tf, e in s[bot].items():
            for key, name in (("sin_ajuste", "sin ajuste"), ("micro", "con ajuste")):
                rows = e.get(key)
                if rows:
                    ref = rows.get(s["balance"], {})
                    L.append(f"| {tf} | {name} | {_cell(rows.get('50'))} | {_cell(rows.get('100'))} | {_cell(ref)} | "
                             f"{_cell(rows.get('10000'))} | {_f(ref.get('pf_is'))}→{_f(ref.get('pf_oos'))} | "
                             f"{ref.get('trades', '—')} | {rows.get('50', {}).get('micro_sl', 0)} |")
        L.append("")
    L += ["## Scalping + Grid + Cesta (riesgo por cesta, stop real, cierre de viernes, corte −30%)", "",
          "Mejor variante por modo de lote, elegida SOLO con el in-sample. PF OOS es lo que cuenta.", "",
          "| TF | Modo | Variante | 50 USD | 100 USD | 1 000 USD | 10 000 USD | PF IS→OOS | Cestas (ganadoras) | "
          "Riesgo medio/cesta | MC P(pérdida) | MC DD p95 |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for tf, e in s["grid"].items():
        for mode in ("fixed", "martingale"):
            b = e.get(f"best_{mode}")
            if not b:
                L.append(f"| {tf} | {mode} | ninguna pasa el filtro IS | | | | | | | | | |")
                continue
            m = b[s["balance"]]
            g, mc = m["basket"], m.get("mc") or {}
            L.append(f"| {tf} | {mode} | {b['label']} | {_cell(b.get('50'))} | {_cell(b.get('100'))} | {_cell(m)} | "
                     f"{_cell(b.get('10000'))} | {_f(m['pf_is'])}→{_f(m['pf_oos'])} | {g.get('baskets')} "
                     f"({g.get('basket_win_pct')}%) | {g.get('avg_risk_pct')}% | {mc.get('p_loss', '—')}% | "
                     f"{mc.get('dd_p95', '—')}% |")
    L += ["", "### Todas las variantes del grid (1 000 USD)", ""]
    for tf, e in s["grid"].items():
        L += [f"**{tf}** ({e['period'][0]} → {e['period'][1]}, IS hasta {e['is_until']})", "",
              "| Variante | Cestas | Ganadoras | PF IS | PF OOS | Neto | DD | Corte DD |", "|---|---|---|---|---|---|---|---|"]
        for label, v in sorted(e["variants"].items(), key=lambda kv: -(kv[1]["pf_is"] or 0)):
            L.append(f"| {label} | {v['baskets']} | {v['basket_win_pct']}% | {_f(v['pf_is'])} | {_f(v['pf_oos'])} | "
                     f"{v['net_pct']:+.1f}% | {v['dd_pct']:.1f}% | {v['halted_at'] or '—'} |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Suite de backtests XAUUSD (scalping, swing, grid) + resumen.")
    ap.add_argument("--only", choices=list(JOBS), default=None)
    ap.add_argument("--tfs", default=None, help="lista separada por comas (p.ej. M5,M15)")
    ap.add_argument("--summary", action="store_true", help="solo rehacer el resumen con los reportes existentes")
    a = ap.parse_args()
    if not a.summary:
        for bot in ([a.only] if a.only else list(JOBS)):
            for tf in JOBS[bot][1]:
                if not a.tfs or tf in a.tfs.split(","):
                    run(bot, tf)
    s = summarize()
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "xau_suite.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    (REPORTS / "xau_suite.md").write_text(markdown(s), encoding="utf-8")
    print(f"\nResumen: {REPORTS / 'xau_suite.md'}")


if __name__ == "__main__":
    main()
