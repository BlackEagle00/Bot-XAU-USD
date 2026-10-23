"""Perfil del panel: DIVISAS · SWING. Independiente de las demás clases (ver _base.py)."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(str(Path(__file__).resolve().parents[1] / "_base.py"))["profile"](
    "forex_swing", base="eurusd_bot", tf="H4",
    sections={"Divisas": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]},
    # ── Parámetros calibrados para esta clase (backtesting/calibrate.py) ──
    # 2026-10-16 · fuera de muestra: PF 0.9, acierto 44.2%, 2560 op, -138.2R (antes: PF 0.84, -732.9R)
    MIN_SIGNAL_SCORE=5.0,
    REQUIRE_MACRO_FOR_SELL=False,
))
