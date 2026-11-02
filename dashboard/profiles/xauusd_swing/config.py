"""Perfil del panel: XAUUSD · SWING. Misma señal y TF que el bot xauusd_bot (ver _base.py)."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(str(Path(__file__).resolve().parents[1] / "_base.py"))["profile"](
    "xauusd_swing", base="xauusd_bot/config.py", tf="H4",
    # ── Parámetros calibrados para esta clase (backtesting/calibrate.py) ──
))
