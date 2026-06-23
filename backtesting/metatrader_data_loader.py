"""
Cargador de datos desde MetaTrader / APIs de brokers
Soporta: MetaTrader5, yfinance, OANDA, etc.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Opciones de importación (instala según lo que uses):
# pip install mt5linux yfinance oanda-v20 pandas numpy

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except:
    MT5_AVAILABLE = False
    print("⚠ MetaTrader5 no instalado. Usa: pip install mt5linux")

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except:
    YFINANCE_AVAILABLE = False
    print("⚠ yfinance no instalado. Usa: pip install yfinance")

try:
    from oanda_v20.contrib.requests import TradesListRequest
    import oanda_v20
    OANDA_AVAILABLE = True
except:
    OANDA_AVAILABLE = False


class MetaTraderDataLoader:
    """Cargar datos directamente desde MetaTrader 5"""

    def __init__(self, account, password, server):
        if not MT5_AVAILABLE:
            raise ImportError("MetaTrader5 no disponible. Instala: pip install mt5linux")

        self.account = account
        self.password = password
        self.server = server

        if not mt5.initialize(login=account, password=password, server=server):
            print(f"Error inicializando MT5: {mt5.last_error()}")

    def get_ohlc_data(self, symbol, timeframe='D1', days=252):
        """
        Obtener datos OHLC desde MetaTrader5

        Args:
            symbol: Par o instrumento (ej: "EURUSD")
            timeframe: 'D1', 'H1', 'M15', etc.
            days: Número de días históricos

        Returns:
            DataFrame con OHLC
        """
        # Mapear timeframes
        timeframes = {
            'M1': mt5.TIMEFRAME_M1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'H1': mt5.TIMEFRAME_H1,
            'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1,
            'W1': mt5.TIMEFRAME_W1,
            'MN1': mt5.TIMEFRAME_MN1,
        }

        tf = timeframes.get(timeframe, mt5.TIMEFRAME_D1)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, days)

        if rates is None:
            print(f"Error obteniendo datos para {symbol}: {mt5.last_error()}")
            return None

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']]
        df.columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        df.set_index('Date', inplace=True)

        return df

    def get_available_symbols(self):
        """Listar todos los símbolos disponibles"""
        return mt5.symbols_get()

    def shutdown(self):
        """Cerrar conexión"""
        mt5.shutdown()


class YFinanceDataLoader:
    """Cargar datos desde Yahoo Finance (acciones, índices, crypto)"""

    def __init__(self):
        if not YFINANCE_AVAILABLE:
            raise ImportError("yfinance no disponible. Instala: pip install yfinance")

    def get_ohlc_data(self, ticker, start_date=None, end_date=None, interval='1d'):
        """
        Obtener datos OHLC desde Yahoo Finance

        Args:
            ticker: Símbolo (ej: "AAPL", "EURUSD=X", "BTC-USD")
            start_date: Fecha inicio (ej: "2023-01-01")
            end_date: Fecha fin (ej: "2024-01-01")
            interval: '1m', '5m', '15m', '1h', '1d', '1wk', '1mo'

        Returns:
            DataFrame con OHLC
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        data = yf.download(ticker, start=start_date, end=end_date, interval=interval, progress=False)
        data.columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
        data = data[['Open', 'High', 'Low', 'Close', 'Volume']]

        return data


class OandaDataLoader:
    """Cargar datos desde OANDA (Forex, CFDs)"""

    def __init__(self, account_id, access_token):
        if not OANDA_AVAILABLE:
            raise ImportError("oanda_v20 no disponible. Instala: pip install oanda-v20")

        self.account_id = account_id
        self.client = oanda_v20.Client(
            accountID=account_id,
            access_token=access_token,
            environment="practice"  # Cambiar a "live" para cuenta real
        )

    def get_ohlc_data(self, instrument, granularity='D', count=252):
        """
        Obtener datos OHLC desde OANDA

        Args:
            instrument: Instrumento (ej: "EUR_USD")
            granularity: 'M1', 'M5', 'H1', 'D', 'W', 'M'
            count: Número de velas

        Returns:
            DataFrame con OHLC
        """
        from oanda_v20.contrib.requests import InstrumentsCandles

        params = {"count": count, "granularity": granularity, "price": "OHLCV"}

        request = InstrumentsCandles(instrument, params=params)
        response = self.client.request(request)

        candles = response['candles']
        data = []

        for candle in candles:
            data.append({
                'Date': pd.to_datetime(candle['time']),
                'Open': float(candle['bid']['o']),
                'High': float(candle['bid']['h']),
                'Low': float(candle['bid']['l']),
                'Close': float(candle['bid']['c']),
                'Volume': int(candle['volume']),
            })

        df = pd.DataFrame(data)
        df.set_index('Date', inplace=True)
        return df


# EJEMPLOS DE USO
if __name__ == "__main__":
    print("\n" + "="*60)
    print("CARGADORES DE DATOS - MetaTrader / Brokers")
    print("="*60)

    # ═══════════════════════════════════════════════════════════
    # OPCIÓN 1: Yahoo Finance (RECOMENDADO para empezar)
    # ═══════════════════════════════════════════════════════════
    if YFINANCE_AVAILABLE:
        print("\n[1] Cargando datos desde Yahoo Finance...")
        yf_loader = YFinanceDataLoader()

        # Ejemplos de tickers
        examples = {
            'Forex': 'EURUSD=X',      # EUR/USD
            'Stock': 'AAPL',           # Apple
            'Crypto': 'BTC-USD',       # Bitcoin
            'Índice': '^GSPC',         # S&P 500
        }

        for category, ticker in examples.items():
            try:
                df = yf_loader.get_ohlc_data(ticker, days=100)
                print(f"✓ {category} ({ticker}): {len(df)} barras cargadas")
                print(f"  Rango: {df.index[0].date()} a {df.index[-1].date()}")
            except Exception as e:
                print(f"✗ Error cargando {category}: {e}")

    # ═══════════════════════════════════════════════════════════
    # OPCIÓN 2: MetaTrader 5 (para usuarios con MT5)
    # ═══════════════════════════════════════════════════════════
    if MT5_AVAILABLE:
        print("\n[2] Cargando datos desde MetaTrader 5...")
        print("Necesitas: Número de cuenta, contraseña, servidor")
        print("Descomenta las líneas abajo y proporciona tus credenciales:")

        # mt5_loader = MetaTraderDataLoader(account=123456, password="tu_password", server="BrokerServer")
        # df = mt5_loader.get_ohlc_data("EURUSD", timeframe="D1", days=252)
        # print(df.head())
        # mt5_loader.shutdown()

    # ═══════════════════════════════════════════════════════════
    # OPCIÓN 3: OANDA (para usuarios con OANDA)
    # ═══════════════════════════════════════════════════════════
    if OANDA_AVAILABLE:
        print("\n[3] OANDA disponible")
        print("Necesitas: Account ID y Access Token")
        print("Descomenta las líneas abajo con tus credenciales:")

        # oanda_loader = OandaDataLoader(account_id="tu_account_id", access_token="tu_token")
        # df = oanda_loader.get_ohlc_data("EUR_USD", granularity="D", count=252)
        # print(df.head())

    print("\n" + "="*60)
    print("INSTRUCCIONES:")
    print("="*60)
    print("1. Para MetaTrader 5:")
    print("   pip install mt5linux")
    print("   Luego descomenta la sección [2] con tus credenciales")
    print("\n2. Para OANDA:")
    print("   pip install oanda-v20")
    print("   Luego descomenta la sección [3] con tus credenciales")
    print("\n3. Para Yahoo Finance (SIN CONFIGURACIÓN):")
    print("   ✓ Ya está funcionando arriba")
    print("\n4. Integración con backtester:")
    print("   df = yf_loader.get_ohlc_data('EURUSD=X')")
    print("   strategy = MovingAverageCrossover(df)")
    print("   strategy.backtest()")
