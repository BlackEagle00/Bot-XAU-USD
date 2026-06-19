"""
Obtención y preprocesamiento de datos de mercado desde MT5.
"""
from typing import Optional
from datetime import datetime, timedelta
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from logger_config import logger
from config import (
    SYMBOL, PRIMARY_TF, TREND_TF, HIGHER_TF,
    CANDLES_PRIMARY, CANDLES_TREND, CANDLES_HIGHER
)


def fetch_ohlcv(symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
    """
    Obtiene datos OHLCV del terminal MT5.

    Returns:
        DataFrame con columnas: open, high, low, close, volume (indexado por tiempo)
        o None si falla la obtención.
    """
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)

    if rates is None or len(rates) == 0:
        logger.error(
            f"Sin datos para {symbol} TF={timeframe}: {mt5.last_error()}"
        )
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    df.rename(columns={"tick_volume": "volume"}, inplace=True)

    # Eliminar la última vela (aún en formación) para evitar señales falsas
    return df[["open", "high", "low", "close", "volume"]].iloc[:-1]


def get_market_data() -> Optional[dict]:
    """
    Obtiene datos de mercado para las tres temporalidades configuradas.

    Returns:
        dict con keys "primary", "trend", "higher" → DataFrames
        o None si alguna temporalidad crítica falla.
    """
    primary = fetch_ohlcv(SYMBOL, PRIMARY_TF, CANDLES_PRIMARY)
    trend   = fetch_ohlcv(SYMBOL, TREND_TF,   CANDLES_TREND)
    higher  = fetch_ohlcv(SYMBOL, HIGHER_TF,  CANDLES_HIGHER)

    if primary is None or trend is None:
        logger.error("No se pudieron obtener datos del mercado (TF primario o tendencia).")
        return None

    return {"primary": primary, "trend": trend, "higher": higher}


def get_tick() -> Optional[mt5.Tick]:
    """Obtiene el tick actual (bid/ask en tiempo real)."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        logger.warning(f"No se pudo obtener tick para {SYMBOL}")
    return tick


def get_current_price() -> Optional[float]:
    """Retorna el precio mid actual."""
    tick = get_tick()
    if tick:
        return (tick.bid + tick.ask) / 2
    return None


def get_symbol_info() -> Optional[mt5.SymbolInfo]:
    return mt5.symbol_info(SYMBOL)


def get_account_info() -> Optional[mt5.AccountInfo]:
    return mt5.account_info()


def get_open_positions() -> list:
    """Retorna todas las posiciones abiertas del bot (filtradas por MAGIC_NUMBER)."""
    from config import MAGIC_NUMBER
    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is None:
        return []
    return [p for p in positions if p.magic == MAGIC_NUMBER]


# ═══════════════════════════════════════════════════════════════════════════════
# ORDER-FLOW — presión compradora/vendedora aproximada por ticks
# ═══════════════════════════════════════════════════════════════════════════════

def get_orderflow_delta() -> Optional[float]:
    """
    Aproxima la presión compradora vs vendedora con los ticks recientes.

    En CFDs no hay volumen real, así que se clasifica cada tick:
      • Si el broker marca el lado del trade (TICK_FLAG_BUY/SELL) → se usa eso.
      • Si no (lo habitual en CFDs) → regla del uptick sobre el precio medio:
        tick que sube = compra, tick que baja = venta.

    Returns:
        delta ∈ [-1, 1]  →  +1 solo compras, -1 solo ventas, 0 equilibrio.
        None si no hay suficientes ticks para fiarse.
    """
    from config import ORDERFLOW_LOOKBACK_SECS, ORDERFLOW_MIN_TICKS

    t_to   = datetime.now()
    t_from = t_to - timedelta(seconds=ORDERFLOW_LOOKBACK_SECS)
    try:
        ticks = mt5.copy_ticks_range(SYMBOL, t_from, t_to, mt5.COPY_TICKS_ALL)
    except Exception as exc:
        logger.debug(f"Order-flow: error obteniendo ticks: {exc}")
        return None

    if ticks is None or len(ticks) < ORDERFLOW_MIN_TICKS:
        return None

    flags     = ticks["flags"]
    buy_mask  = (flags & mt5.TICK_FLAG_BUY).astype(bool)
    sell_mask = (flags & mt5.TICK_FLAG_SELL).astype(bool)
    buys  = int(np.count_nonzero(buy_mask & ~sell_mask))
    sells = int(np.count_nonzero(sell_mask & ~buy_mask))

    # Fallback: el broker no marca lado de trade → regla del uptick sobre el mid
    if (buys + sells) < ORDERFLOW_MIN_TICKS:
        mid  = (ticks["bid"] + ticks["ask"]) / 2.0
        dmid = np.diff(mid)
        buys  = int(np.count_nonzero(dmid > 0))
        sells = int(np.count_nonzero(dmid < 0))

    total = buys + sells
    if total < ORDERFLOW_MIN_TICKS:
        return None
    return float((buys - sells) / total)


# ═══════════════════════════════════════════════════════════════════════════════
# INTER-MERCADO — sesgo del índice dólar (DXY)
# ═══════════════════════════════════════════════════════════════════════════════

def get_intermarket_bias() -> Optional[tuple]:
    """
    Tendencia del índice dólar (DXY) para sesgar el activo (el oro/EUR es inverso).

    Returns:
        (trend, strong) con trend ∈ {"up", "down", "neutral"} y strong: bool
        (True = EMA21/EMA50 alineadas y precio del lado correcto).
        None si el símbolo no está disponible en el broker (se desactiva solo).
    """
    from config import INTERMARKET_SYMBOL, INTERMARKET_TF, INTERMARKET_CANDLES

    if not INTERMARKET_SYMBOL:
        return None
    if not mt5.symbol_select(INTERMARKET_SYMBOL, True):
        logger.debug(f"Inter-mercado: '{INTERMARKET_SYMBOL}' no disponible en el broker.")
        return None

    rates = mt5.copy_rates_from_pos(INTERMARKET_SYMBOL, INTERMARKET_TF, 0, INTERMARKET_CANDLES)
    if rates is None or len(rates) < 60:
        return None

    close    = pd.Series([float(r["close"]) for r in rates])
    ema_fast = close.ewm(span=21, adjust=False).mean().iloc[-1]
    ema_slow = close.ewm(span=50, adjust=False).mean().iloc[-1]
    price    = close.iloc[-1]

    if ema_fast > ema_slow and price > ema_fast:
        return ("up", True)
    if ema_fast < ema_slow and price < ema_fast:
        return ("down", True)
    if price > ema_slow:
        return ("up", False)
    if price < ema_slow:
        return ("down", False)
    return ("neutral", False)