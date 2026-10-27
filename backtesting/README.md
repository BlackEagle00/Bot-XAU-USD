# Backtesting del motor real + filtro predictivo

`engine_backtest.py` prueba **el mismo motor que opera en vivo** (`bot_engine/`) sobre el histórico
de MT5, vela a vela y sin mirar el futuro, y entrena el **filtro predictivo** (`bot_engine/ml_filter.py`)
con validación walk-forward. No toca la cuenta: solo lee velas.

## Uso

Desde la raíz del repo, con el terminal MT5 abierto:

```bash
python backtesting/engine_backtest.py xauusd_bot H4 --ml                     # oro, config del bot swing
python backtesting/engine_backtest.py xauusd_scalping_bot M15 --ml           # oro, config del bot scalping
python backtesting/engine_backtest.py forex_swing H4 --symbol EURUSD --ml    # perfil de clase del panel
python backtesting/engine_backtest.py xauusd_bot H1 --set REQUIRE_MACRO_FOR_SELL=True   # probar una regla
# opciones: --years 3  --balances 100,1000,10000  --mc 2000  --workers N  --refresh
```

- **Perfil**: carpeta de un bot (usa su `config.py`) o un perfil de clase del panel
  (`dashboard/profiles/<forex|metals|stocks>_<scalping|swing>/`, armado con `_base.profile()`).
- `--signals-only` solo genera la caché de señales (para `calibrate.py`); `--set K=V` cambia una clave
  sin tocar el config y nunca guarda modelos.
- **Temporalidades**: M5 / M10 / M15 (tendencia M15 / M30 / H1, superior H1 / H1 / H4) y
  H1 / H4 / D1 / W1 (tendencia H4 / D1 / W1 / MN1, superior D1 / W1 / MN1 / —).

## Qué hace

1. **Señales**: `calculate_all` → `analyze_patterns` → `generate_signal` al cierre de cada vela, solo
   con velas ya cerradas; para BUY/SELL guarda también las features del modelo. En paralelo, con caché
   en `backtesting/data/signals_*.pkl.gz` (se recalcula sola si cambia el código o el config).
2. **Resultado de cada señal (triple barrera)**: entrada en la apertura siguiente con el **spread real**,
   SL/TP por ATR, R:R mínimo, spread ≤ 25% del stop y BE+/trailing de `trade_manager`. Se calcula
   para el SL/TP del config y para 7 combinaciones más (TP más corto que el SL sube el acierto).
3. **Cuenta**, para cada balance (100 / 1 000 / 10 000 USD): **niveles por capital**
   (`risk_manager.capital_tier`), lote dinámico, máximo de abiertas, anti-duplicado y límite diario.
4. **`--ml` — walk-forward anclado por trimestres con purga**: en cada ventana entrena
   `HistGradientBoostingClassifier` solo con operaciones ya terminadas, elige SL/TP y el umbral τ en
   una validación interna (acierto ≥ 80%, ≥ 30 operaciones y ganancia) y opera el trimestre siguiente.
   **Todo lo reportado como "ml" y "base_oos" es fuera de muestra** y sobre la misma ventana.
   Si el resultado fuera de muestra logra **≥ 75% de acierto con PF > 1**, guarda el modelo en
   `models/<perfil>_<TF>_<símbolo>.joblib`; si no, borra el que hubiera.
5. **Monte Carlo**: re-muestrea el orden de las operaciones → drawdown mediano y al 95%, P(pérdida).

**No reproduce**: filtro de noticias, order-flow, DXY, swaps, comisiones ni margen. El BE+/trailing
se evalúa una vez por vela (en vivo cada 15-60 s); si una vela toca SL y TP, cuenta como SL.

## Salida

`backtesting/reports/<perfil>_<símbolo>_<TF>.json`: cobertura, señales, `base` (3 años, sin filtro),
`base_oos` y `ml` (fuera de muestra), por balance: PF, acierto, expectativa en R, drawdown, Sharpe,
CAGR, desglose anual y por lado, bloqueos; `folds` del walk-forward; `mc`; `model` guardado.
Veredicto: **Rentable** (PF ≥ 1,2, expectativa > 0 y ≥ 2/3 de los años positivos), **Marginal**
(PF 1,0–1,2) o **No rentable**. `backtesting/data/`, `backtesting/reports/` y `models/` están en `.gitignore`.

> El terminal entrega como máximo "Máx. barras en gráfico" velas (100 000 por defecto): en M5 eso son
> ~17 meses. Para 3 años completos sube ese valor a Ilimitado en MT5 (Herramientas → Opciones → Gráficos)
> y corre con `--refresh`.

## Grid y suite XAUUSD (`xau_suite.py`)

Con un config `USE_GRID=True`, `engine_backtest.py` no usa la triple barrera. Corre `simulate_grid`
(cesta vela a vela, en orden conservador) y reporta en la clave `"grid"`, por variante de `--sweep` y
por balance: métricas, `basket` (cestas, % ganadoras, peor cesta, salidas), `basket_split` (IS/OOS) y
`mc` sobre el retorno por cesta.

```bash
python backtesting/xau_suite.py                # scalping M1/M5/M15/H1 · swing H1/H4 · grid M1/M5/M15/H1
python backtesting/xau_suite.py --summary      # rehace reports/xau_suite.md con los reportes existentes
python backtesting/engine_backtest.py xauusd_scalping_bot M15 --end 2026-10-16   # repetir un periodo (regresión)
```

- **Análisis por operación** (todos los bots): minutos por operación, resultado por sesión (UTC),
  días hasta duplicar y `split` in-sample (60 %) / fuera de muestra (40 %).
- **Elección de la variante del grid.** Se hace solo con el IS (≥ 30 cestas, 1 000 USD). El OOS es el
  resultado.
- **M1.** Por defecto MT5 guarda ~100 000 velas de 1 minuto (~3 meses), así que la suite usa
  `--years 0.27`.

## Calibración por clase (`calibrate.py`)

```bash
# 1) caché con umbral ≈ 0 de cada activo y TF de la clase (scalping: M15; swing: H1 y H4)
python backtesting/engine_backtest.py forex_swing H1 --symbol EURUSD --set MIN_SIGNAL_SCORE=0.01 --signals-only
# 2) rejilla + walk-forward; --write escribe en el config del perfil solo si mejora fuera de muestra
python backtesting/calibrate.py forex_swing --write
```

- **Rejilla:** umbral {3…7} × "ventas solo con macro bajista" × SL/TP (`COMBOS`) × TF.
- **Selección:** walk-forward trimestral con purga, sumando todos los activos de la clase y con ≥ 30
  operaciones en entrenamiento. Se compara contra los parámetros actuales en las mismas ventanas.
- **Por qué alcanza una sola pasada del motor:** con umbral ≈ 0, la acción con umbral U es la misma si
  |score| ≥ U, porque los filtros no dependen del umbral (`test_threshold_applied_later_matches_engine`).
- **Salida:** `backtesting/reports/calibration_<perfil>.json`. El panel lo lee y marca "Sin ventaja
  probada" si el PF fuera de muestra de lo vigente es ≤ 1.
