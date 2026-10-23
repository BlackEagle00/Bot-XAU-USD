"""
Base común de los perfiles del panel: un config independiente por CLASE de activo y MODO.

Cada `dashboard/profiles/<clase>_<modo>/config.py` llama a `profile(...)`: parte del config de
un bot (EUR/USD para divisas, oro para metales y acciones), quita las claves en unidades
absolutas de ese activo (todo queda relativo al ATR) y aplica los parámetros calibrados para
su clase con `backtesting/calibrate.py`.
"""
import runpy
from pathlib import Path

import MetaTrader5 as mt5

ROOT = Path(__file__).resolve().parents[2]
# TF primario → (tendencia, superior, velas en 24 h)
_TF = {"M15": ("H1", "H4", 96), "H1": ("H4", "D1", 24), "H4": ("D1", "W1", 6)}


def profile(name: str, base: str, tf: str, sections: dict, **overrides) -> dict:
    """Config del perfil `name` (p.ej. "forex_swing") a partir del config del bot `base`."""
    cfg = {k: v for k, v in runpy.run_path(str(ROOT / base / "config.py")).items() if k.isupper()}
    trend, higher, day = _TF[tf]
    mode = name.rsplit("_", 1)[1]
    cfg.update(
        PRIMARY_TF=getattr(mt5, f"TIMEFRAME_{tf}"), TREND_TF=getattr(mt5, f"TIMEFRAME_{trend}"),
        HIGHER_TF=getattr(mt5, f"TIMEFRAME_{higher}"), TF_LABELS=f"{tf}/{trend}/{higher}",
        MACRO_TF_LABEL=higher, SR_24H_CANDLES=day, VWAP_PERIOD=day,
        USE_MACRO_CONTEXT=True,            # calcula la tendencia superior (su peso sale del config base)
        ATR_VOLATILITY_MIN=0, SR_TOLERANCE_FLOOR=0.0, PSYCH_LEVEL_COUNT=0,   # sin unidades absolutas
        MAX_LOT=500.0,                     # tope de seguridad (acciones van por unidades); manda el riesgo
        MAGIC_NUMBER=20260630,             # un solo número para todo el panel: el nivel cuenta TODAS sus operaciones
        ORDER_COMMENT_PREFIX="WEB", TELEGRAM_PREFIX=f"[WEB {name}]", LOG_FILE=f"dashboard_{name}.log",
        NEWS_CURRENCIES=["USD", "EUR", "GBP", "JPY", "AUD"],
        USE_ML_FILTER=True,                # usa models/<perfil>_<TF>_<símbolo>.joblib si existe y está en el manifiesto
        REQUIRE_MACRO_FOR_SELL=False,
        PROFILE=name, MODE=mode, MODE_LABEL="Scalping" if mode == "scalping" else "Swing", SECTIONS=sections,
    )
    cfg.update(overrides)
    return cfg
