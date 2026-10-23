"""Perfil del panel: METALES · SCALPING. Independiente de las demás clases (ver _base.py)."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(str(Path(__file__).resolve().parents[1] / "_base.py"))["profile"](
    "metals_scalping", base="xauusd_scalping_bot", tf="M15",
    sections={"Metales": ["XAUUSD", "XAGUSD"]},
    # ── Parámetros calibrados para esta clase (backtesting/calibrate.py) ──
))
