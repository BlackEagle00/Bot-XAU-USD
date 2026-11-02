"""Perfil del panel: XAUUSD · SCALPING. Misma señal y TF que el bot xauusd_scalping_bot (ver _base.py)."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(str(Path(__file__).resolve().parents[1] / "_base.py"))["profile"](
    "xauusd_scalping", base="xauusd_scalping_bot/config.py", tf="M15",
    # ── Parámetros calibrados para esta clase (backtesting/calibrate.py) ──
))
