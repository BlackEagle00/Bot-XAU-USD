"""
Perfil de spread REAL por hora del servidor (ticks de los últimos N días) → data/spread_profile_<SYM>.json.

Las velas de MT5 guardan el spread MÍNIMO de cada vela (XAUUSD M15: mediana ~10 pts) y los ticks
muestran el que paga una orden (mediana ~36 pts). Con BT_REAL_SPREAD=True el backtest usa este perfil.

Uso (desde la raíz, con el terminal MT5 abierto):  python backtesting/spread_profile.py [XAUUSD] [30]
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

QUANTILES = np.linspace(2.5, 97.5, 20)


def main(sym: str = "XAUUSD", days: int = 30):
    if not mt5.initialize():
        sys.exit(f"mt5.initialize() falló: {mt5.last_error()}")
    try:
        point = mt5.symbol_info(sym).point
        end = datetime.now(timezone.utc) + timedelta(days=1)          # la hora del servidor va por delante de UTC
        t = mt5.copy_ticks_range(sym, end - timedelta(days=days + 1), end, mt5.COPY_TICKS_INFO)
    finally:
        mt5.shutdown()
    if t is None or not len(t):
        sys.exit(f"Sin ticks de {sym}")
    spread = np.round((t["ask"] - t["bid"]) / point)
    hour = (t["time"] // 3600) % 24
    prof = {int(h): np.percentile(spread[hour == h], QUANTILES).round(1).tolist() for h in np.unique(hour)}
    out = Path(__file__).resolve().parent / "data" / f"spread_profile_{sym}.json"
    out.write_text(json.dumps({"symbol": sym, "days": days, "ticks": int(len(t)), "hours": prof}), encoding="utf-8")
    print(f"{out.name}: {len(t):,} ticks · mediana {np.median(spread):.0f} pts · horas {sorted(prof)}")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or ["XAUUSD"]), *map(int, sys.argv[2:3]))
