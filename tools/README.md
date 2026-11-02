# tools/ — scripts de reporte (solo lectura, no abren órdenes)

Se ejecutan desde la raíz del repo con `PYTHONIOENCODING=utf-8`, con el terminal MT5 abierto. La salida de los logs se filtra siempre con
`grep -avE "Login|login|Servidor|CUENTA|#[0-9]{6,}"` (los logs contienen datos de la cuenta).

| Script | Uso | Qué da |
|---|---|---|
| `bots_summary.py` | `python tools/bots_summary.py "2026-10-27 16:26" 55.27` | balance/equity, abiertas y cierres por magic (30 min y desde la fecha) |
| `report_extra.py` | `python tools/report_extra.py` | operación hipotética de cada señal "BUY/SELL bloqueado" del log + foto M1/M5/M15/M30/H1/H4 |
| `mfe_live.py` | `python tools/mfe_live.py` | avance máximo a favor de esas señales en vivo (% del camino al TP) |
| `mfe_bt.py` | `python tools/mfe_bt.py` | lo mismo sobre las señales del caché del backtest de 3 años, por grupo de filtro |
| `atr_freq.py` | `python tools/atr_freq.py` | % del tiempo con ATR M15 bajo el tope del 15 % según el balance |
| `range_bt.py` | `python tools/range_bt.py [M15\|M5]` | backtest del módulo de rango (ADX < 18, ruptura falsa de redondo/extremo 2 h), en/fuera de muestra. 2026-10-29: sin ventaja (PF en muestra < 1) |

`report_extra.py`/`mfe_live.py` leen el log desde `SINCE` (constante arriba: cámbiala por la fecha del día).
`mfe_bt.py` apunta a un caché concreto de `backtesting/data/` (cambia de nombre si cambia el motor).
