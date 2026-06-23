"""
Framework de Backtesting para MetaTrader - Multi-mercado
Soporta: Forex, Acciones, Criptomonedas
Estrategias: Media Móvil, RSI, Breakout
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

class TradingStrategy:
    """Clase base para estrategias de trading"""

    def __init__(self, name, data, initial_capital=10000, risk_per_trade=0.02):
        self.name = name
        self.data = data.copy()
        self.initial_capital = initial_capital
        self.risk_per_trade = risk_per_trade
        self.trades = []
        self.equity_curve = [initial_capital]
        self.current_capital = initial_capital

    def calculate_signals(self):
        """Método que heredan las estrategias específicas"""
        raise NotImplementedError

    def backtest(self):
        """Ejecutar backtest"""
        self.calculate_signals()
        self._execute_trades()
        self._calculate_metrics()
        return self.results

    def _execute_trades(self):
        """Simular ejecución de trades basado en señales"""
        position = None
        entry_price = 0
        entry_index = 0

        for i in range(1, len(self.data)):
            current_price = self.data['Close'].iloc[i]
            signal = self.data['Signal'].iloc[i]

            # Cerrar posición si hay señal contraria
            if position is not None:
                opposite_signal = -1 if position == 1 else 1
                if signal == opposite_signal:
                    pnl = (current_price - entry_price) * position
                    pnl_pct = (pnl / entry_price) / self.risk_per_trade

                    self.trades.append({
                        'entry_date': self.data.index[entry_index],
                        'exit_date': self.data.index[i],
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'position': position,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'bars_held': i - entry_index
                    })

                    self.current_capital += pnl
                    self.equity_curve.append(self.current_capital)
                    position = None

            # Abrir nueva posición
            if signal != 0 and position is None:
                position = signal
                entry_price = current_price
                entry_index = i

            # Agregar equity si no hay cambio
            if position is None:
                self.equity_curve.append(self.current_capital)

    def _calculate_metrics(self):
        """Calcular métricas de performance"""
        equity = pd.Series(self.equity_curve)
        returns = equity.pct_change().dropna()

        total_return = (self.equity_curve[-1] - self.initial_capital) / self.initial_capital
        annual_return = total_return / (len(self.data) / 252)

        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

        max_dd = self._calculate_max_drawdown(equity)

        win_rate = len([t for t in self.trades if t['pnl'] > 0]) / len(self.trades) if self.trades else 0
        avg_win = np.mean([t['pnl'] for t in self.trades if t['pnl'] > 0]) if self.trades else 0
        avg_loss = np.mean([t['pnl'] for t in self.trades if t['pnl'] < 0]) if self.trades else 0

        self.results = {
            'strategy': self.name,
            'total_trades': len(self.trades),
            'total_return': total_return,
            'annual_return': annual_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else 0,
        }

    def _calculate_max_drawdown(self, equity):
        """Calcular máximo drawdown"""
        cummax = equity.cummax()
        drawdown = (equity - cummax) / cummax
        return drawdown.min()

    def print_results(self):
        """Imprimir resultados del backtest"""
        print(f"\n{'='*60}")
        print(f"RESULTADOS: {self.results['strategy']}")
        print(f"{'='*60}")
        print(f"Capital inicial: ${self.initial_capital:,.2f}")
        print(f"Capital final: ${self.equity_curve[-1]:,.2f}")
        print(f"Retorno total: {self.results['total_return']:.2%}")
        print(f"Retorno anualizado: {self.results['annual_return']:.2%}")
        print(f"Sharpe Ratio: {self.results['sharpe_ratio']:.2f}")
        print(f"Max Drawdown: {self.results['max_drawdown']:.2%}")
        print(f"\nOperaciones totales: {self.results['total_trades']}")
        print(f"Win Rate: {self.results['win_rate']:.2%}")
        print(f"Ganancia promedio: ${self.results['avg_win']:,.2f}")
        print(f"Pérdida promedio: ${self.results['avg_loss']:,.2f}")
        print(f"Profit Factor: {self.results['profit_factor']:.2f}")
        print(f"{'='*60}\n")


class MovingAverageCrossover(TradingStrategy):
    """Estrategia de cruce de medias móviles"""

    def __init__(self, data, fast_period=10, slow_period=20, **kwargs):
        super().__init__("MA Crossover", data, **kwargs)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def calculate_signals(self):
        """Señales basadas en cruce de medias móviles"""
        self.data['MA_Fast'] = self.data['Close'].rolling(self.fast_period).mean()
        self.data['MA_Slow'] = self.data['Close'].rolling(self.slow_period).mean()

        self.data['Signal'] = 0
        self.data.loc[self.data['MA_Fast'] > self.data['MA_Slow'], 'Signal'] = 1  # Compra
        self.data.loc[self.data['MA_Fast'] < self.data['MA_Slow'], 'Signal'] = -1  # Venta


class RSIMomentum(TradingStrategy):
    """Estrategia basada en RSI (Relative Strength Index)"""

    def __init__(self, data, rsi_period=14, oversold=30, overbought=70, **kwargs):
        super().__init__("RSI Momentum", data, **kwargs)
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought

    def calculate_signals(self):
        """Señales basadas en RSI"""
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()

        rs = gain / loss
        self.data['RSI'] = 100 - (100 / (1 + rs))

        self.data['Signal'] = 0
        self.data.loc[self.data['RSI'] < self.oversold, 'Signal'] = 1  # Sobreventa = Compra
        self.data.loc[self.data['RSI'] > self.overbought, 'Signal'] = -1  # Sobrecompra = Venta


class BreakoutStrategy(TradingStrategy):
    """Estrategia de Breakout"""

    def __init__(self, data, lookback=20, **kwargs):
        super().__init__("Breakout", data, **kwargs)
        self.lookback = lookback

    def calculate_signals(self):
        """Señales basadas en breakouts de máximos/mínimos"""
        self.data['High_Lookback'] = self.data['High'].rolling(self.lookback).max()
        self.data['Low_Lookback'] = self.data['Low'].rolling(self.lookback).min()

        self.data['Signal'] = 0
        self.data.loc[self.data['Close'] > self.data['High_Lookback'].shift(1), 'Signal'] = 1  # Breakout alcista
        self.data.loc[self.data['Close'] < self.data['Low_Lookback'].shift(1), 'Signal'] = -1  # Breakout bajista


class HybridStrategy(TradingStrategy):
    """Estrategia híbrida: combina MA, RSI y Breakout"""

    def __init__(self, data, ma_fast=10, ma_slow=20, rsi_period=14,
                 oversold=30, overbought=70, breakout_lookback=20, **kwargs):
        super().__init__("Hybrid", data, **kwargs)
        self.ma_fast = ma_fast
        self.ma_slow = ma_slow
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.breakout_lookback = breakout_lookback

    def calculate_signals(self):
        """Combina señales de MA, RSI y Breakout"""
        # Medias móviles
        self.data['MA_Fast'] = self.data['Close'].rolling(self.ma_fast).mean()
        self.data['MA_Slow'] = self.data['Close'].rolling(self.ma_slow).mean()

        # RSI
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / loss
        self.data['RSI'] = 100 - (100 / (1 + rs))

        # Breakout
        self.data['High_Lookback'] = self.data['High'].rolling(self.breakout_lookback).max()
        self.data['Low_Lookback'] = self.data['Low'].rolling(self.breakout_lookback).min()

        # Combinar señales (mayoría gana)
        signal_ma = np.where(self.data['MA_Fast'] > self.data['MA_Slow'], 1, -1)
        signal_rsi = np.where(self.data['RSI'] < self.oversold, 1, np.where(self.data['RSI'] > self.overbought, -1, 0))
        signal_breakout = np.where(self.data['Close'] > self.data['High_Lookback'].shift(1), 1,
                                   np.where(self.data['Close'] < self.data['Low_Lookback'].shift(1), -1, 0))

        # Votación: si 2+ indicadores están de acuerdo, genera señal
        combined = signal_ma + signal_rsi + signal_breakout
        self.data['Signal'] = np.sign(combined)


def generate_sample_data(days=252, asset_type='forex'):
    """Generar datos OHLC de ejemplo"""
    dates = pd.date_range(end=datetime.now(), periods=days, freq='D')

    # Simular precio base según tipo de activo
    if asset_type == 'forex':
        base_price = 1.10
    elif asset_type == 'stock':
        base_price = 150.0
    else:  # crypto
        base_price = 45000.0

    # Movimiento de precio con ruido
    returns = np.random.normal(0.0003, 0.02, days)
    prices = base_price * np.exp(np.cumsum(returns))

    data = pd.DataFrame({
        'Date': dates,
        'Open': prices * (1 + np.random.normal(0, 0.005, days)),
        'High': prices * (1 + np.abs(np.random.normal(0, 0.01, days))),
        'Low': prices * (1 - np.abs(np.random.normal(0, 0.01, days))),
        'Close': prices,
        'Volume': np.random.randint(1000000, 10000000, days)
    })

    data.set_index('Date', inplace=True)
    return data


# EJEMPLO DE USO
if __name__ == "__main__":
    print("\n" + "="*60)
    print("FRAMEWORK DE BACKTESTING - MetaTrader")
    print("="*60)

    # Generar datos de ejemplo para diferentes mercados
    forex_data = generate_sample_data(days=252, asset_type='forex')
    stock_data = generate_sample_data(days=252, asset_type='stock')
    crypto_data = generate_sample_data(days=252, asset_type='crypto')

    # Instanciar estrategias
    strategies = [
        MovingAverageCrossover(forex_data, fast_period=10, slow_period=20, initial_capital=10000),
        RSIMomentum(forex_data, rsi_period=14, oversold=30, overbought=70, initial_capital=10000),
        BreakoutStrategy(forex_data, lookback=20, initial_capital=10000),
        HybridStrategy(forex_data, initial_capital=10000),
    ]

    # Ejecutar backtests
    for strategy in strategies:
        strategy.backtest()
        strategy.print_results()

    # Comparar estrategias
    print("\nRESUMEN COMPARATIVO:")
    print("-" * 60)
    results_summary = []
    for strategy in strategies:
        results_summary.append(strategy.results)

    df_results = pd.DataFrame(results_summary)
    print(df_results[['strategy', 'total_return', 'sharpe_ratio', 'max_drawdown', 'win_rate', 'profit_factor']].to_string())

    print("\n✓ Framework listo. Personaliza los parámetros según tus necesidades.")
    print("✓ Usa generate_sample_data() con tus datos reales de MetaTrader.")
