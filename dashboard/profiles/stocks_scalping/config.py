"""Perfil del panel: ACCIONES y ETF cripto · SCALPING. Independiente de las demás clases (ver _base.py)."""
import runpy
from pathlib import Path

globals().update(runpy.run_path(str(Path(__file__).resolve().parents[1] / "_base.py"))["profile"](
    "stocks_scalping", base="xauusd_scalping_bot", tf="M15",
    sections={"Acciones": ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "GOOG", "META"],
                "Cripto (ETF)": ["IBIT", "ETH"]},
    # ── Parámetros calibrados para esta clase (backtesting/calibrate.py) ──
    # 2026-10-16 · fuera de muestra: PF 0.9, acierto 61.6%, 36943 op, -1820.8R (antes: PF 0.85, -2442.5R)
    MIN_SIGNAL_SCORE=3.0,
    REQUIRE_MACRO_FOR_SELL=True,
    SL_ATR_MULT=2.0,
    TP_ATR_MULT=1.0,
    MIN_RR=0.45,
))
