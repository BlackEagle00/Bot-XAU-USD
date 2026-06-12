"""
Obtención y preprocesamiento de datos de mercado desde MT5.
"""
from typing import Optional
import MetaTrader5 as mt5
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