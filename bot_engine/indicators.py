"""
Indicadores Técnicos — Implementación manual con NumPy/Pandas.

Indicadores incluidos:
  EMA (9, 21, 50, 200) | SMA (20, 50) | RSI | MACD | ATR
  Bandas de Bollinger  | VWAP Rodante | Soporte & Resistencia
"""
import pandas as pd
import numpy as np
from typing import Tuple, List
from config import (
    EMA_FAST, EMA_MED, EMA_SLOW, EMA_TREND,
    SMA_FAST, SMA_SLOW,
    RSI_PERIOD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ATR_PERIOD, BB_PERIOD, BB_STD,
    VWAP_PERIOD, SR_LOOKBACK, SR_LEVELS, SR_24H_CANDLES,
    ADX_PERIOD,
    SR_CLUSTER_ATR_MULT, SR_TOLERANCE_FLOOR, PSYCH_LEVEL_STEP, PSYCH_LEVEL_COUNT,
)


# ═══════════════════════════════════════════════════════════════════════════════
# MEDIAS MÓVILES
# ═══════════════════════════════════════════════════════════════════════════════

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Media Móvil Exponencial."""
    return series.ewm(span=period, adjust=False).mean()


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    """Media Móvil Simple."""
    return series.rolling(window=period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
# RSI — Relative Strength Index
# ═══════════════════════════════════════════════════════════════════════════════

def calc_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """
    RSI con suavizado exponencial (Wilder's).
    Retorna valores 0-100. > 70 sobrecompra, < 30 sobreventa.
    """
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


# ═══════════════════════════════════════════════════════════════════════════════
# MACD — Moving Average Convergence Divergence
# ═══════════════════════════════════════════════════════════════════════════════

def calc_macd(close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns:
        (macd_line, signal_line, histogram)
        - macd_line    : EMA_FAST - EMA_SLOW
        - signal_line  : EMA(macd_line, MACD_SIGNAL)
        - histogram    : macd_line - signal_line
    """
    ema_fast    = calc_ema(close, MACD_FAST)
    ema_slow    = calc_ema(close, MACD_SLOW)
    macd_line   = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, MACD_SIGNAL)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


# ═══════════════════════════════════════════════════════════════════════════════
# ATR — Average True Range
# ═══════════════════════════════════════════════════════════════════════════════

def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = ATR_PERIOD) -> pd.Series:
    """
    True Range = max(H-L, |H-C_prev|, |L-C_prev|).
    ATR = EMA(TR, period).
    """
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
# ADX — Average Directional Index (fuerza de la tendencia)
# ═══════════════════════════════════════════════════════════════════════════════

def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series,
             period: int = ADX_PERIOD) -> pd.Series:
    """
    ADX (Average Directional Index) — mide la FUERZA de la tendencia, no su dirección.
      • ADX > ~25  → tendencia fuerte (seguir tendencia tiene sentido)
      • ADX < ~20  → mercado lateral / chop (los cruces son ruido)
    Suavizado de Wilder (igual estilo que ATR/RSI del resto del módulo).
    """
    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm   = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm  = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_w    = tr.ewm(com=period - 1, min_periods=period).mean()
    plus_di  = 100 * plus_dm.ewm(com=period - 1, min_periods=period).mean() / atr_w
    minus_di = 100 * minus_dm.ewm(com=period - 1, min_periods=period).mean() / atr_w
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(com=period - 1, min_periods=period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
# BANDAS DE BOLLINGER
# ═══════════════════════════════════════════════════════════════════════════════

def calc_bollinger(close: pd.Series,
                   period: int = BB_PERIOD,
                   std: float   = BB_STD) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns: (upper, middle, lower)
    """
    middle  = calc_sma(close, period)
    std_dev = close.rolling(window=period).std(ddof=0)
    upper   = middle + std * std_dev
    lower   = middle - std * std_dev
    return upper, middle, lower


def calc_bb_percent(close: pd.Series,
                    upper: pd.Series,
                    lower: pd.Series) -> pd.Series:
    """%B: 0 = banda inferior, 1 = banda superior. < 0 o > 1 = fuera de bandas."""
    band_width = (upper - lower).replace(0, np.nan)
    return (close - lower) / band_width


def calc_bb_width(upper: pd.Series,
                  lower: pd.Series,
                  middle: pd.Series) -> pd.Series:
    """Ancho normalizado. Bajo → squeeze (baja volatilidad → próxima expansión)."""
    return (upper - lower) / middle.replace(0, np.nan)


# ═══════════════════════════════════════════════════════════════════════════════
# VWAP — Volume Weighted Average Price (rodante)
# ═══════════════════════════════════════════════════════════════════════════════

def calc_vwap(high: pd.Series, low: pd.Series,
              close: pd.Series, volume: pd.Series,
              period: int = VWAP_PERIOD) -> pd.Series:
    """
    VWAP Rodante sobre las últimas `period` velas.
    Precio por encima del VWAP → sesgo alcista; por debajo → bajista.
    """
    tp  = (high + low + close) / 3
    vol = volume.replace(0, np.nan)
    return (tp * vol).rolling(period).sum() / vol.rolling(period).sum()


# ═══════════════════════════════════════════════════════════════════════════════
# SOPORTE & RESISTENCIA
# ═══════════════════════════════════════════════════════════════════════════════

def _find_pivot_highs(high: pd.Series, lookback: int) -> List[float]:
    """Detecta máximos locales (swing highs)."""
    pivots = []
    for i in range(lookback, len(high) - lookback):
        window = high.iloc[i - lookback: i + lookback + 1]
        if float(high.iloc[i]) == float(window.max()):
            pivots.append(float(high.iloc[i]))
    return pivots


def _find_pivot_lows(low: pd.Series, lookback: int) -> List[float]:
    """Detecta mínimos locales (swing lows)."""
    pivots = []
    for i in range(lookback, len(low) - lookback):
        window = low.iloc[i - lookback: i + lookback + 1]
        if float(low.iloc[i]) == float(window.min()):
            pivots.append(float(low.iloc[i]))
    return pivots


def _cluster_levels(levels: List[float], tolerance: float = 0.50) -> List[float]:
    """Agrupa niveles cercanos en uno solo (promedio del grupo)."""
    if not levels:
        return []
    sorted_lvls = sorted(levels)
    clusters = [[sorted_lvls[0]]]
    for lvl in sorted_lvls[1:]:
        if lvl - clusters[-1][-1] <= tolerance:
            clusters[-1].append(lvl)
        else:
            clusters.append([lvl])
    return [float(np.mean(c)) for c in clusters]


def get_support_resistance(df: pd.DataFrame,
                           current_price: float,
                           atr: float = 1.0) -> dict:
    """
    Calcula niveles de soporte y resistencia usando:
      1. Pivot highs/lows de la historia
      2. Máximo/mínimo de las últimas 24h (en M5 ≈ 288 velas)
      3. Niveles psicológicos redondos ($X00, $X50, $X25, $X75)

    Returns:
        {"supports": [...], "resistances": [...]}
        Ordenados por proximidad al precio actual.
    """
    # Tolerancia de agrupación relativa al instrumento. El piso (SR_TOLERANCE_FLOOR)
    # solo aplica al Oro (0.5 $); en forex es 0.0 para no romper la escala en decimales.
    tolerance = max(atr * SR_CLUSTER_ATR_MULT, SR_TOLERANCE_FLOOR)

    # 1. Pivots históricos
    p_highs = _find_pivot_highs(df["high"], SR_LOOKBACK)
    p_lows  = _find_pivot_lows(df["low"],  SR_LOOKBACK)

    all_res = _cluster_levels(p_highs, tolerance)
    all_sup = _cluster_levels(p_lows,  tolerance)

    # 2. Rango de las últimas 24h (SR_24H_CANDLES se ajusta al TF primario)
    last_24h = df.tail(SR_24H_CANDLES)
    all_res.append(float(last_24h["high"].max()))
    all_sup.append(float(last_24h["low"].min()))

    # 3. Niveles psicológicos cercanos al precio (paso/cantidad según el instrumento:
    #    Oro = 5.0 × 5 niveles, EURUSD = 0.0050 × 6 niveles — definido en config).
    step = PSYCH_LEVEL_STEP
    base = round(current_price / step) * step
    for k in range(-PSYCH_LEVEL_COUNT, PSYCH_LEVEL_COUNT + 1):
        lvl = base + k * step
        if lvl > current_price + tolerance:
            all_res.append(float(lvl))
        elif lvl < current_price - tolerance:
            all_sup.append(float(lvl))

    # Filtrar y ordenar
    supports    = sorted(
        [s for s in set(all_sup) if s < current_price - tolerance],
        reverse=True
    )[:SR_LEVELS]
    resistances = sorted(
        [r for r in set(all_res) if r > current_price + tolerance]
    )[:SR_LEVELS]

    return {"supports": supports, "resistances": resistances}


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN MAESTRA — calcula todo de una vez
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_all(df: pd.DataFrame, current_price: float) -> dict:
    """
    Calcula todos los indicadores sobre el DataFrame proporcionado.
    Retorna un diccionario con el último valor (y el anterior) de cada indicador.
    """
    c = df["close"]
    h = df["high"]
    lo = df["low"]
    v  = df["volume"]

    # — Medias Móviles —
    ema9   = calc_ema(c, EMA_FAST)
    ema21  = calc_ema(c, EMA_MED)
    ema50  = calc_ema(c, EMA_SLOW)
    ema200 = calc_ema(c, EMA_TREND)
    sma20  = calc_sma(c, SMA_FAST)
    sma50  = calc_sma(c, SMA_SLOW)

    # — RSI —
    rsi = calc_rsi(c)

    # — MACD —
    macd_line, macd_sig, macd_hist = calc_macd(c)

    # — ATR —
    atr = calc_atr(h, lo, c)

    # — ADX (fuerza de tendencia) —
    adx = calc_adx(h, lo, c)

    # — Bollinger —
    bb_u, bb_m, bb_l = calc_bollinger(c)
    bb_pct   = calc_bb_percent(c, bb_u, bb_l)
    bb_width = calc_bb_width(bb_u, bb_l, bb_m)

    # — VWAP —
    vwap = calc_vwap(h, lo, c, v)

    # — Volumen MA —
    vol_ma = calc_sma(v, 20)

    # — S/R —
    atr_last = float(atr.iloc[-1]) if not atr.empty else 1.0
    sr = get_support_resistance(df, current_price, atr_last)

    def _val(s: pd.Series, offset: int = 0) -> float:
        idx = -(1 + offset)
        try:
            v = float(s.iloc[idx])
            return v if not np.isnan(v) else None
        except Exception:
            return None

    return {
        # EMAs
        "ema9":          _val(ema9),
        "ema21":         _val(ema21),
        "ema50":         _val(ema50),
        "ema200":        _val(ema200),
        "ema9_prev":     _val(ema9,  1),
        "ema21_prev":    _val(ema21, 1),
        # SMAs
        "sma20":         _val(sma20),
        "sma50":         _val(sma50),
        # RSI
        "rsi":           _val(rsi),
        "rsi_prev":      _val(rsi, 1),
        # MACD
        "macd":          _val(macd_line),
        "macd_signal":   _val(macd_sig),
        "macd_hist":     _val(macd_hist),
        "macd_prev":     _val(macd_line, 1),
        "macd_sig_prev": _val(macd_sig,  1),
        "macd_hist_prev":_val(macd_hist, 1),
        # ATR
        "atr":           _val(atr),
        # ADX (fuerza de tendencia)
        "adx":           _val(adx),
        "adx_prev":      _val(adx, 1),
        # Bollinger
        "bb_upper":      _val(bb_u),
        "bb_mid":        _val(bb_m),
        "bb_lower":      _val(bb_l),
        "bb_pct":        _val(bb_pct),
        "bb_width":      _val(bb_width),
        "bb_width_prev": _val(bb_width, 1),
        # VWAP
        "vwap":          _val(vwap),
        # Volumen
        "volume":        _val(v),
        "volume_ma":     _val(vol_ma),
        # Soporte / Resistencia
        "supports":      sr["supports"],
        "resistances":   sr["resistances"],
    }