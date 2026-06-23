# Backtesting (toolkit independiente)

Framework genérico de backtesting **separado de los bots en vivo**. No se importa desde
ningún bot ni forma parte de su ejecución: es una herramienta autónoma para probar
estrategias sobre datos históricos.

| Archivo | Qué es |
|---|---|
| `trading_backtest_framework.py` | Motor de backtesting (clases base, métricas, ejecución). |
| `metatrader_data_loader.py` | Carga datos históricos OHLCV (CSV / MT5) para alimentar el backtest. |
| `ejemplo_completo_backtest.py` | Ejemplo de uso de punta a punta del framework. |

## Uso

```bash
cd backtesting
python ejemplo_completo_backtest.py
```

> Usa las mismas dependencias del proyecto (`pandas`, `numpy`); instálalas con el
> `requirements.txt` de la raíz. Es código de laboratorio: **no** toca las cuentas ni los
> bots en producción.
