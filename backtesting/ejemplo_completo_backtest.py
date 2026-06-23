"""
EJEMPLO COMPLETO: Backtesting con datos reales
Integra cargador de datos + estrategias
"""

import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta

# Importar las clases del framework
# (Asegúrate de que trading_backtest_framework.py esté en el mismo directorio)
from trading_backtest_framework import (
    MovingAverageCrossover,
    RSIMomentum,
    BreakoutStrategy,
    HybridStrategy,
    generate_sample_data
)

try:
    import yfinance as yf
except:
    print("⚠ yfinance no instalado. Instala con: pip install yfinance")
    sys.exit(1)


def load_data_yfinance(ticker, days=365):
    """Cargar datos reales desde Yahoo Finance"""
    print(f"\n📥 Descargando datos de {ticker}...")
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    try:
        data = yf.download(ticker, start=start_date, end=end_date, progress=False)
        data.columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
        data = data[['Open', 'High', 'Low', 'Close', 'Volume']]
        print(f"✓ {len(data)} barras descargadas ({data.index[0].date()} a {data.index[-1].date()})")
        return data
    except Exception as e:
        print(f"✗ Error: {e}")
        return None


def run_backtest_single_strategy(data, strategy_class, params, initial_capital=10000):
    """Ejecutar un backtest individual"""
    strategy = strategy_class(data, initial_capital=initial_capital, **params)
    strategy.backtest()
    return strategy


def run_optimization(data, strategy_class, param_grid, initial_capital=10000):
    """Optimizar parámetros de una estrategia (grid search)"""
    results = []

    # Generar todas las combinaciones
    param_combinations = generate_param_combinations(param_grid)
    total_combos = len(param_combinations)

    print(f"\n🔍 Optimizando {strategy_class.__name__}...")
    print(f"   Probando {total_combos} combinaciones...")

    for i, params in enumerate(param_combinations, 1):
        try:
            strategy = run_backtest_single_strategy(data, strategy_class, params, initial_capital)
            results.append({
                'params': params,
                'results': strategy.results
            })
            if i % max(1, total_combos // 10) == 0:
                print(f"   Progreso: {i}/{total_combos}")
        except Exception as e:
            print(f"   ✗ Error con params {params}: {e}")
            continue

    # Ordenar por Sharpe Ratio
    results.sort(key=lambda x: x['results']['sharpe_ratio'], reverse=True)

    print(f"\n✓ Top 5 combinaciones:")
    for i, result in enumerate(results[:5], 1):
        print(f"\n   [{i}] Parámetros: {result['params']}")
        print(f"       Retorno: {result['results']['total_return']:.2%}")
        print(f"       Sharpe: {result['results']['sharpe_ratio']:.2f}")
        print(f"       Max DD: {result['results']['max_drawdown']:.2%}")
        print(f"       Win Rate: {result['results']['win_rate']:.2%}")

    return results


def generate_param_combinations(param_grid):
    """Generar todas las combinaciones de parámetros"""
    import itertools

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = []

    for combo in itertools.product(*values):
        combinations.append(dict(zip(keys, combo)))

    return combinations


def compare_strategies(data, strategies_config, initial_capital=10000):
    """Comparar múltiples estrategias"""
    print("\n" + "="*70)
    print("COMPARACIÓN DE ESTRATEGIAS")
    print("="*70)

    results_list = []

    for strategy_name, (strategy_class, params) in strategies_config.items():
        print(f"\n▶ Backtesting {strategy_name}...")
        strategy = run_backtest_single_strategy(data, strategy_class, params, initial_capital)
        strategy.print_results()
        results_list.append(strategy.results)

    # Crear tabla comparativa
    df_comparison = pd.DataFrame(results_list)
    print("\n" + "="*70)
    print("RESUMEN COMPARATIVO")
    print("="*70)
    print(df_comparison[['strategy', 'total_return', 'sharpe_ratio', 'max_drawdown', 'win_rate', 'profit_factor']].to_string(index=False))

    return results_list


# ════════════════════════════════════════════════════════════════════════
# MAIN - EJEMPLOS DE USO
# ════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🤖 BACKTESTER - Sistema de Trading Automático")
    print("="*70)

    # ───────────────────────────────────────────────────────────────────
    # ESCENARIO 1: Backtest simple con datos reales (Forex)
    # ───────────────────────────────────────────────────────────────────
    print("\n📊 ESCENARIO 1: Backtest Forex (EUR/USD)")
    print("-" * 70)

    data_forex = load_data_yfinance('EURUSD=X', days=252)
    if data_forex is not None:
        strategies = {
            'MA Crossover': (MovingAverageCrossover, {'fast_period': 10, 'slow_period': 20}),
            'RSI Momentum': (RSIMomentum, {'rsi_period': 14, 'oversold': 30, 'overbought': 70}),
            'Breakout': (BreakoutStrategy, {'lookback': 20}),
            'Hybrid': (HybridStrategy, {}),
        }
        compare_strategies(data_forex, strategies, initial_capital=10000)

    # ───────────────────────────────────────────────────────────────────
    # ESCENARIO 2: Backtest con acciones (Apple)
    # ───────────────────────────────────────────────────────────────────
    print("\n\n📊 ESCENARIO 2: Backtest de Acciones (Apple - AAPL)")
    print("-" * 70)

    data_stock = load_data_yfinance('AAPL', days=365)
    if data_stock is not None:
        strategies = {
            'MA Crossover': (MovingAverageCrossover, {'fast_period': 20, 'slow_period': 50}),
            'Hybrid': (HybridStrategy, {}),
        }
        compare_strategies(data_stock, strategies, initial_capital=10000)

    # ───────────────────────────────────────────────────────────────────
    # ESCENARIO 3: Backtest con Criptomonedas
    # ───────────────────────────────────────────────────────────────────
    print("\n\n📊 ESCENARIO 3: Backtest de Criptomonedas (Bitcoin - BTC-USD)")
    print("-" * 70)

    data_crypto = load_data_yfinance('BTC-USD', days=365)
    if data_crypto is not None:
        strategies = {
            'MA Crossover': (MovingAverageCrossover, {'fast_period': 10, 'slow_period': 30}),
            'RSI Momentum': (RSIMomentum, {'rsi_period': 14, 'oversold': 30, 'overbought': 70}),
        }
        compare_strategies(data_crypto, strategies, initial_capital=5000)

    # ───────────────────────────────────────────────────────────────────
    # ESCENARIO 4: Optimización de parámetros (MA Crossover en Forex)
    # ───────────────────────────────────────────────────────────────────
    print("\n\n🔍 ESCENARIO 4: Optimización de parámetros (MA Crossover)")
    print("-" * 70)

    if data_forex is not None:
        param_grid = {
            'fast_period': [5, 10, 15, 20],
            'slow_period': [30, 40, 50, 60],
        }
        optimization_results = run_optimization(
            data_forex,
            MovingAverageCrossover,
            param_grid,
            initial_capital=10000
        )

    # ───────────────────────────────────────────────────────────────────
    # RESUMEN FINAL
    # ───────────────────────────────────────────────────────────────────
    print("\n\n" + "="*70)
    print("✅ BACKTESTING COMPLETADO")
    print("="*70)
    print("\n🎯 PRÓXIMOS PASOS:")
    print("   1. Ajusta los parámetros según tus preferencias")
    print("   2. Prueba con diferentes pares/acciones/cryptos")
    print("   3. Optimiza usando grid search")
    print("   4. Valida con datos out-of-sample")
    print("   5. Cuando estés listo, convierte a EA de MetaTrader")
    print("\n💡 Para cargar datos de MetaTrader directamente:")
    print("   - Edita metatrader_data_loader.py con tus credenciales")
    print("   - O usa la API REST de tu broker (OANDA, Interactive Brokers, etc.)")
