"""
Indicadores Técnicos — Implementación manual con NumPy/Pandas.

Indicadores incluidos:
  EMA (9, 21, 50, 200) | SMA (20, 50) | RSI | MACD | ATR
  Bandas de Bollinger  | VWAP Rodante | Soporte & Resistencia
"""
import pandas as pd
import numpy as np
from typing import Tuple, List
import config as _cfg
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


def calc_vwap_session(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """VWAP acumulado desde el inicio del día (el índice es la hora del servidor de MT5).
    El volumen es tick_volume: pondera por actividad del bróker, no por volumen real negociado."""
    tp  = (high + low + close) / 3
    vol = volume.replace(0, np.nan)
    day = high.index.normalize()
    return (tp * vol).groupby(day).cumsum() / vol.groupby(day).cumsum()


# ═══════════════════════════════════════════════════════════════════════════════
# SOPORTE & RESISTENCIA
# ═══════════════════════════════════════════════════════════════════════════════

def _find_pivots(values: pd.Series, lookback: int, reduce) -> List[float]:
    """Valores que son el extremo (reduce = np.nanmax/np.nanmin) de su ventana ±lookback.
    Vectorizado: el bucle con .iloc tardaba ~75 ms por llamada con 1500 velas."""
    v = values.to_numpy(dtype=float)
    if len(v) < 2 * lookback + 1:
        return []
    ext = reduce(np.lib.stride_tricks.sliding_window_view(v, 2 * lookback + 1), axis=1)
    mid = v[lookback:len(v) - lookback]
    return mid[mid == ext].tolist()


def _find_pivot_highs(high: pd.Series, lookback: int) -> List[float]:
    """Detecta máximos locales (swing highs)."""
    return _find_pivots(high, lookback, np.nanmax)


def _find_pivot_lows(low: pd.Series, lookback: int) -> List[float]:
    """Detecta mínimos locales (swing lows)."""
    return _find_pivots(low, lookback, np.nanmin)


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

    # — VWAP — (VWAP_SESSION, experimental: anclado al día del SERVIDOR, que es lo que traen las velas de MT5)
    vwap = calc_vwap_session(h, lo, c, v) if getattr(_cfg, "VWAP_SESSION", False) else calc_vwap(h, lo, c, v)

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


# Régimen de mercado (ADX × terciles de ATR%) — usado por el filtro SKIP_REGIMES y por las métricas del backtest
def regime_labels(p: pd.DataFrame, adx_min: float, window: int = 2000, min_hist: int = 500, shift: int = 1) -> np.ndarray:
    """Régimen de cada vela con datos CERRADOS hasta la anterior (sin mirar el futuro):
    'tendencia'/'lateral' por ADX ≥ adx_min, y volatilidad 'baja'/'media'/'alta' por los terciles del ATR%
    de las `window` velas previas. 'sin datos' mientras no haya `min_hist` velas de historia.
    shift=0: la etiqueta de la vela SIGUIENTE a la última fila (vivo: las velas ya vienen sin la que se forma)."""
    h, l, c = p["high"].astype(float), p["low"].astype(float), p["close"].astype(float)
    adx = calc_adx(h, l, c).shift(shift)
    atrp = (calc_atr(h, l, c) / c).shift(shift)
    roll = atrp.rolling(window, min_periods=min_hist)
    q1, q2 = roll.quantile(1 / 3), roll.quantile(2 / 3)
    vol = np.where(atrp <= q1, "baja", np.where(atrp <= q2, "media", "alta"))
    trend = np.where(adx >= adx_min, "tendencia", "lateral")
    lab = np.char.add(np.char.add(trend.astype(str), "/"), vol.astype(str))
    return np.where(q2.isna() | adx.isna(), "sin datos", lab)


# Vela anómala (inyección de liquidez) — filtro ALTA_VOLATILIDAD_ANÓMALA de core y del backtest
def anomalous_bars(high, low, mult: float, lookback: int = 20) -> np.ndarray:
    """True en la vela cuyo rango supera `mult` × el rango medio de las `lookback` velas ANTERIORES (sin futuro)."""
    rng = pd.Series(np.asarray(high, float) - np.asarray(low, float))
    avg = rng.shift(1).rolling(lookback).mean()
    return (rng > mult * avg).to_numpy()


# ── Estrategias complementarias (SIGNAL_SOURCES / DXY_VETO). Apagadas por defecto; las mismas funciones las usan
#    core en vivo (última fila = última vela cerrada) y el backtest (todo el histórico de una vez). ──────────────
def _ohlc(df: pd.DataFrame):
    return tuple(df[k].astype(float) for k in ("open", "high", "low", "close"))


def london_breakout(df: pd.DataFrame, asia=(2, 10), london=(10, 13), buf_atr: float = 0.0,
                    trend: bool = True) -> np.ndarray:
    """+1/-1 en la vela que cierra fuera del rango asiático del mismo día servidor dentro de la ventana de Londres
    (horas servidor de APERTURA de la vela; 10 h servidor ≈ apertura de Londres). Solo la primera ruptura por día y
    lado; trend=True exige EMA21 vs EMA50 a favor. Causal: el rango solo usa velas asiáticas, todas anteriores."""
    _, h, l, c = _ohlc(df)
    idx = pd.DatetimeIndex(df.index)
    hr, day = idx.hour, idx.normalize()
    in_asia = (hr >= asia[0]) & (hr < asia[1])
    in_lon = (hr >= london[0]) & (hr < london[1])
    a_hi = h.where(in_asia).groupby(day).transform("max")
    a_lo = l.where(in_asia).groupby(day).transform("min")
    pad = buf_atr * calc_atr(h, l, c) if buf_atr else 0.0
    up, dn = in_lon & (c > a_hi + pad), in_lon & (c < a_lo - pad)
    if trend:
        e21, e50 = calc_ema(c, 21), calc_ema(c, 50)
        up, dn = up & (e21 > e50), dn & (e21 < e50)
    up = up & (up.groupby(day).cumsum() == 1)
    dn = dn & (dn.groupby(day).cumsum() == 1)
    return np.where(up, 1, np.where(dn, -1, 0)).astype(int)


def smc_retest(df: pd.DataFrame, lookback: int = 48, impulse_atr: float = 1.0, trend: bool = True) -> np.ndarray:
    """+1/-1 en la vela que vuelve a una zona SMC aún válida y cierra a favor (alcista: toca la zona y cierra verde).
    Zonas, nacidas al cerrar la vela j tras una vela de impulso j-1 (cuerpo ≥ impulse_atr×ATR):
      Fair Value Gap: low[j] > high[j-2] (alcista) / high[j] < low[j-2] (bajista);
      Order Block: la vela j-2 contraria al impulso (su rango completo).
    Una zona vale `lookback` velas, se usa desde j+1, se consume al primer toque y se invalida si una vela cierra
    al otro lado. El resultado en la vela i solo depende de las ~lookback+3 velas previas (vivo = backtest)."""
    so, sh, sl, sc = _ohlc(df)
    o, h, l, c = so.to_numpy(), sh.to_numpy(), sl.to_numpy(), sc.to_numpy()
    atr = calc_atr(sh, sl, sc).to_numpy(float)
    e21, e50 = calc_ema(sc, 21).to_numpy(), calc_ema(sc, 50).to_numpy()
    out, zones = np.zeros(len(c), int), []                  # zona = (lado, abajo, arriba, vela de nacimiento)
    for i in range(len(c)):
        keep = []
        for side, bot, top, born in zones:
            if i - born > lookback or (side > 0 and c[i] < bot) or (side < 0 and c[i] > top):
                continue                                    # caducada o invalidada
            ok_trend = not trend or (e21[i] > e50[i] if side > 0 else e21[i] < e50[i])
            touched = (l[i] <= top and c[i] > o[i]) if side > 0 else (h[i] >= bot and c[i] < o[i])
            if touched and ok_trend and out[i] == 0:
                out[i] = side                               # consumida
                continue
            keep.append((side, bot, top, born))
        zones = keep
        if i >= 2 and atr[i - 1] == atr[i - 1] and abs(c[i - 1] - o[i - 1]) >= impulse_atr * atr[i - 1]:
            bull = c[i - 1] > o[i - 1]
            if bull and l[i] > h[i - 2]:
                zones.append((1, h[i - 2], l[i], i))
            if not bull and h[i] < l[i - 2]:
                zones.append((-1, h[i], l[i - 2], i))
            if bull and c[i - 2] < o[i - 2]:
                zones.append((1, l[i - 2], h[i - 2], i))
            if not bull and c[i - 2] > o[i - 2]:
                zones.append((-1, l[i - 2], h[i - 2], i))
    return out


def extra_source(df: pd.DataFrame, name: str, cfg) -> np.ndarray:
    """Señal (+1/-1/0 por vela) de una fuente complementaria de SIGNAL_SOURCES con los parámetros del config."""
    if name == "lb":
        return london_breakout(df, tuple(getattr(cfg, "LB_ASIA_HOURS", (2, 10))),
                               tuple(getattr(cfg, "LB_LONDON_HOURS", (10, 13))),
                               float(getattr(cfg, "LB_BUFFER_ATR", 0.0)), bool(getattr(cfg, "LB_TREND", True)))
    if name == "smc":
        return smc_retest(df, int(getattr(cfg, "SMC_LOOKBACK", 48)), float(getattr(cfg, "SMC_IMPULSE_ATR", 1.0)),
                          bool(getattr(cfg, "SMC_TREND", True)))
    raise ValueError(f"fuente desconocida: {name}")


def dxy_bias(close) -> np.ndarray:
    """Sesgo del índice dólar por vela cerrada (regla de get_intermarket_bias): EMA21/EMA50 alineadas y precio del
    lado correcto = ±2 (fuerte); solo precio vs EMA50 = ±1; si no, 0."""
    c = pd.Series(np.asarray(close, float))
    f, s = c.ewm(span=21, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    return np.select([(f > s) & (c > f), (f < s) & (c < f), c > s, c < s], [2, -2, 1, -1], 0)
