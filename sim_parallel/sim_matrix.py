"""
Matriz histórica Balance × Bróker: corre el backtest del motor real (M15, por defecto 1.41 años = 17 meses, mismos ajustes que el control
`_ctl` con el tope duro del 15 % activo) una vez por perfil de brokers_profile.json y escribe la sección "Histórico"
de docs/SIM_COMP_2026-10.md. No toca MT5 más allá de leer historia (lo hace engine_backtest).

    python sim_parallel/sim_matrix.py          # 1.41 años (= control)
    python sim_parallel/sim_matrix.py 3        # 3 años de M15
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from sim_parallel import BALANCES, PROFILES, write_section  # noqa: E402

YEARS = sys.argv[1] if len(sys.argv) > 1 else "1.41"     # 1.41 = mismo periodo que el control _ctl (desde 2025-06)
BASE = ["--years", YEARS, "--symbol", "XAUUSD-ECN", "--set", "BT_REAL_SPREAD=True", "--set", "MAX_SPREAD_POINTS=40",
        "--set", "MAX_OPEN_TRADES=1", "--set", "DAILY_LOSS_ALERT_ONLY=False", "--set", "MIN_SIGNAL_SCORE=6.5",
        "--set", "MIN_LOT_CAP_HARD=True", "--balances", ",".join(map(str, BALANCES)), "--mc", "0"]


def run(p: dict) -> dict:
    sets = [f"BT_SPREAD_MULT={p['spread_multiplier']}", f"BT_SPREAD_OFFSET_POINTS={p['fixed_spread_offset_points']}",
            f"BT_COMMISSION_PER_LOT={p['commission_per_lot']}", f"BT_SLIPPAGE_POINTS={p['slippage_points']}"]
    cmd = [sys.executable, str(ROOT / "backtesting" / "engine_backtest.py"), "xauusd_scalping_bot", "M15", *BASE,
           *[x for s in sets for x in ("--set", s)], "--suffix", f"_sim{YEARS}_{p['name']}"]
    out = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    rep = [ln.split("Reporte: ", 1)[1].rsplit(" (", 1)[0] for ln in out.stdout.splitlines() if ln.startswith("Reporte: ")]
    if out.returncode or not rep:
        sys.exit(f"backtest {p['name']} falló:\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}")
    print(f"  {p['name']}: {rep[0]}")
    return json.loads(Path(rep[0]).read_text(encoding="utf-8"))


def main():
    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))["profiles"]
    rows = [f"## Histórico (backtest {YEARS} años)", "",
            "Motor real sobre M15 XAUUSD-ECN con spread real × perfil, comisión y deslizamiento del perfil, umbral 6.5, "
            "1 operación a la vez, regla de lote del bot (1 % + tope duro 15 %). **No simula** el filtro de noticias, el "
            "bloqueo temporal ATR 7.5 ni la latencia (solo `slippage_points`). TRADE_REJECTED = `lot0`; SIGNAL_BLOCKED = "
            "señales descartadas por spread (≥ 40 pts o > 25 % del SL; igual para todo balance).", "",
            "| Balance | Bróker | Ops | Acierto | Neto % | PF | PF IS / OOS | DD máx | Costo USD | TRADE_REJECTED | SIGNAL_BLOCKED |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in profiles:
        d = run(p)
        for b in BALANCES:
            r = d["base"][str(b)]
            s = r.get("split") or {}
            blk = r.get("blocked") or {}
            rows.append(f"| {b:,} | {p['name']} | {r['trades']} | {r['win_rate_pct']:.1f} % | {r['net_return_pct']:+.1f} % "
                        f"| {r['profit_factor']:.2f} | {s.get('is', {}).get('pf', '-')} / {s.get('oos', {}).get('pf', '-')} "
                        f"| {r['max_drawdown_pct']:.1f} % | {r['cost_total']:.2f} | {blk.get('lot0', 0)} "
                        f"| {d['signals']['filtered']['spread']} |")
    write_section(f"HIST_{YEARS}", "\n".join(rows))
    print("Escrito docs/SIM_COMP_2026-10.md")


if __name__ == "__main__":
    main()
