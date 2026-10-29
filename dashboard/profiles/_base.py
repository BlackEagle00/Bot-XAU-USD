"""
Base común de los perfiles del panel (solo XAUUSD): uno por modelo — swing, scalping y grid.

Cada `dashboard/profiles/xauusd_<modo>/config.py` llama a `profile(...)`: carga el config del bot de
ese modo tal cual (misma señal) y solo cambia la identidad del panel (magic, prefijo, log) y el TF.
"""
import runpy
from pathlib import Path

import MetaTrader5 as mt5

ROOT = Path(__file__).resolve().parents[2]
# TF primario → (tendencia, superior, velas en 24 h)
_TF = {"M1": ("M5", "M15", 1440), "M5": ("M15", "H1", 288), "M15": ("H1", "H4", 96),
       "H1": ("H4", "D1", 24), "H4": ("D1", "W1", 6)}
_MODE_LABELS = {"scalping": "Scalping", "swing": "Swing", "grid": "Grid"}


def profile(name: str, base: str, tf: str, sections: dict = None, **overrides) -> dict:
    """Config del perfil `name` (p.ej. "xauusd_swing") a partir del config `base` (ruta desde la raíz).
    Sin `sections`, el panel muestra el SYMBOL del bot (cada bróker nombra el oro distinto: XAUUSD, XAUUSD-ECN…)."""
    cfg = {k: v for k, v in runpy.run_path(str(ROOT / base)).items() if k.isupper()}
    sections = sections or {"Metales": [cfg["SYMBOL"]]}
    trend, higher, day = _TF[tf]
    mode = name.rsplit("_", 1)[1]
    cfg.update(
        PRIMARY_TF=getattr(mt5, f"TIMEFRAME_{tf}"), TREND_TF=getattr(mt5, f"TIMEFRAME_{trend}"),
        HIGHER_TF=getattr(mt5, f"TIMEFRAME_{higher}"), TF_LABELS=f"{tf}/{trend}/{higher}",
        MACRO_TF_LABEL=higher, SR_24H_CANDLES=day, VWAP_PERIOD=day,
        MAGIC_NUMBER=20260630,             # un solo número para todo el panel: el nivel cuenta TODAS sus operaciones
        ORDER_COMMENT_PREFIX="WEB", TELEGRAM_PREFIX=f"[WEB {name}]", LOG_FILE=f"dashboard_{name}.log",
        PROFILE=name, MODE=mode, MODE_LABEL=_MODE_LABELS[mode], SECTIONS=sections,
    )
    cfg.update(overrides)
    return cfg
