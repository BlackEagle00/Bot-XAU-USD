"""
Filtro predictivo (meta-labeling).

El motor decide la DIRECCIÓN de la operación; este modelo decide si vale la pena tomarla:
estima P(la operación llega al TP antes que al SL) y solo deja operar si P ≥ τ.

Los modelos los entrena `backtesting/engine_backtest.py --ml` con validación walk-forward
(solo se reporta lo fuera de muestra) y se guardan en
`models/<perfil>_<TF>_<símbolo>.joblib` con: el clasificador, τ, el SL/TP en ATR que usa,
la lista de features y sus métricas fuera de muestra.

Se activa con `USE_ML_FILTER = True` en el config. Sin scikit-learn, sin archivo o con un
archivo de otra versión de features, el bot opera igual que sin filtro (y lo registra).
Los archivos .joblib son pickles: carga solo los que generó tu propio backtest.
"""
import math
from datetime import datetime, timezone
from pathlib import Path

from .logger_config import logger

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
TF_NAMES   = ("M1", "M5", "M10", "M15", "M30", "H1", "H4", "D1", "W1", "MN1")
_BREAKDOWN = ("ema", "rsi", "macd", "bollinger", "patterns", "sr", "vwap", "volume",
              "trend_confirm", "macro")      # order-flow y DXY no: no existen en el histórico
FEATURE_NAMES = [f"bd_{k}" for k in _BREAKDOWN] + [
    "score", "rsi", "adx", "bb_pct", "bb_width", "macd_hist_atr", "dist_ema50_atr",
    "dist_ema200_atr", "atr_pct", "spread_atr", "volume_ratio", "trend_tf_atr",
    "macro_tf_atr", "hour", "weekday", "side",
]
_cache: dict = {}


def _f(value, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _spread_of(ind, a: str, b: str) -> float:
    """(a − b) / ATR del mismo TF; 0 si falta algo."""
    if not ind or ind.get(a) is None or ind.get(b) is None or not ind.get("atr"):
        return 0.0
    return (_f(ind[a]) - _f(ind[b])) / _f(ind["atr"], 1.0)


def features(side: int, price: float, ip: dict, it: dict, ih, signal: dict,
             spread: float, ts: int) -> list:
    """
    Entrada del modelo. Es la MISMA función en el backtest y en vivo.
    side = +1 (BUY) / −1 (SELL): todo lo direccional se multiplica por side, así
    "a favor de la operación" es siempre positivo y un solo modelo sirve a ambos lados.
    ts = hora del servidor (epoch) al decidir.
    """
    atr = _f(ip.get("atr")) or 1e-9
    bd = signal.get("breakdown") or {}
    t = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    vol_ma = _f(ip.get("volume_ma"))
    return [side * _f(bd.get(k)) for k in _BREAKDOWN] + [
        side * _f(signal.get("score")),
        _f(ip.get("rsi"), 50.0),
        _f(ip.get("adx")),
        _f(ip.get("bb_pct"), 0.5),
        _f(ip.get("bb_width")),
        side * _f(ip.get("macd_hist")) / atr,
        side * (price - _f(ip.get("ema50"), price)) / atr,
        side * (price - _f(ip.get("ema200"), price)) / atr,
        atr / price * 100 if price else 0.0,
        spread / atr,
        _f(ip.get("volume")) / vol_ma if vol_ma else 1.0,
        side * _spread_of(it, "ema21", "ema50"),
        side * _spread_of(ih, "ema50", "ema200"),
        t.hour,
        t.weekday(),
        side,
    ]


def model_path(profile: str, tf: str, symbol: str) -> Path:
    return MODELS_DIR / f"{profile}_{tf}_{symbol}.joblib"


MANIFEST = MODELS_DIR / "manifest.json"   # {archivo: sha256} que escribe el backtest al guardar


def file_sha256(path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register(path) -> None:
    """Anota el SHA-256 de un modelo recién guardado (lo llama el backtest)."""
    import json
    path = Path(path)
    data = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    data[path.name] = file_sha256(path)
    MANIFEST.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


def unregister(path) -> None:
    import json
    if MANIFEST.exists():
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if data.pop(Path(path).name, None) is not None:
            MANIFEST.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")


def _trusted(path: Path) -> bool:
    """Un .joblib es un pickle (puede ejecutar código al cargarse): solo se abre si su hash
    coincide con el que anotó tu propio backtest en el manifiesto."""
    import json
    try:
        expected = json.loads(MANIFEST.read_text(encoding="utf-8")).get(path.name)
    except (OSError, ValueError):
        return False
    return bool(expected) and expected == file_sha256(path)


def load(path) -> dict | None:
    """Carga (y cachea) un modelo. None si no existe, no es de confianza, falla o es de otra versión."""
    path = Path(path)
    if path in _cache:
        return _cache[path]
    bundle = None
    if path.exists() and not _trusted(path):
        logger.warning(f"🧠 {path.name} no coincide con models/manifest.json: no se carga. Sin filtro.")
    elif path.exists():
        try:
            import joblib
            bundle = joblib.load(path)
            if bundle.get("features") != FEATURE_NAMES:
                logger.warning(f"🧠 {path.name}: features distintas a las actuales; reentrena. Sin filtro.")
                bundle = None
        except Exception as exc:
            logger.warning(f"🧠 No se pudo cargar {path.name}: {exc}. Sin filtro.")
            bundle = None
    _cache[path] = bundle
    return bundle


def bundle_for(symbol: str):
    """Modelo activo para este símbolo según el config cargado, o None."""
    import config
    if not getattr(config, "USE_ML_FILTER", False):
        return None
    import MetaTrader5 as mt5
    tf = next((n for n in TF_NAMES if getattr(mt5, f"TIMEFRAME_{n}", None) == config.PRIMARY_TF), None)
    profile = Path(config.__file__).resolve().parent.name
    return load(model_path(profile, tf, symbol)) if tf else None


def probability(bundle: dict, feats: list) -> float:
    return float(bundle["model"].predict_proba([feats])[0][1])


def allows(bundle: dict, feats: list):
    """(¿operar?, P(éxito)). Sin modelo siempre permite."""
    if not bundle:
        return True, None
    p = probability(bundle, feats)
    return p >= bundle["tau"], p
