# Comparativa Balance × Bróker (simulación, NO operaciones reales)

<!-- REPLAY -->
## Repetición de señales desde 2026-10-28T16:00:00+00:00 UTC

Actualizado 2026-10-28 17:05 (hora local). Señales leídas: 5. Lote: regla del bot (1 % + tope duro 15 %). Sin break-even ni trailing.

| Balance | Bróker | Ops | Acierto | Neto USD | Neto % | PF | Comisión | TRADE_REJECTED | SIGNAL_BLOCKED | BLOQUEADA_BOT | OCUPADA | Abierta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 100 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 100 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 100 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 100 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 500 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 500 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 500 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 500 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 1,000 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 1,000 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 1,000 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 1,000 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 5,000 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 5,000 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 5,000 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
| 5,000 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 5 | 0 | no |
<!-- /REPLAY -->

<!-- HIST_3 -->
## Histórico (backtest 3 años, 2023-10 → 2026-10)

Motor real sobre M15 XAUUSD-ECN con spread real × perfil, comisión y deslizamiento del perfil, umbral 6.5, 1 operación a la vez, regla de lote del bot (1 % + tope duro 15 %). **No simula** el filtro de noticias, el bloqueo temporal ATR 7.5 ni la latencia (solo `slippage_points`). TRADE_REJECTED = `lot0`; SIGNAL_BLOCKED = señales descartadas por spread (≥ 40 pts o > 25 % del SL; igual para todo balance).

| Balance | Bróker | Ops | Acierto | Neto % | PF | PF IS / OOS | DD máx | Costo USD | TRADE_REJECTED | SIGNAL_BLOCKED |
|---|---|---|---|---|---|---|---|---|---|---|
| 100 | VT_ACTUAL | 78 | 37.2 % | -50.8 % | 0.64 | 0.64 / None | 52.5 % | 4.68 | 5 | 5 |
| 500 | VT_ACTUAL | 2743 | 50.7 % | +231.1 % | 1.10 | 1.11 / 1.1 | 32.4 % | 166.02 | 0 | 5 |
| 1,000 | VT_ACTUAL | 2743 | 50.7 % | +126.3 % | 1.10 | 1.08 / 1.11 | 23.5 % | 231.00 | 0 | 5 |
| 5,000 | VT_ACTUAL | 2743 | 50.7 % | +123.7 % | 1.08 | 1.07 / 1.09 | 30.9 % | 1430.64 | 0 | 5 |
| 100 | SPREAD_ALTO | 57 | 42.1 % | -52.5 % | 0.49 | 0.49 / None | 52.6 % | 9.69 | 5 | 297 |
| 500 | SPREAD_ALTO | 2687 | 49.2 % | +108.8 % | 1.05 | 1.02 / 1.06 | 43.6 % | 457.47 | 0 | 297 |
| 1,000 | SPREAD_ALTO | 2694 | 49.2 % | +53.6 % | 1.05 | 0.98 / 1.08 | 34.3 % | 524.96 | 0 | 297 |
| 5,000 | SPREAD_ALTO | 2695 | 49.3 % | +11.0 % | 1.01 | 0.96 / 1.07 | 36.5 % | 2572.27 | 0 | 297 |
| 100 | RETAIL_STD | 74 | 37.8 % | -55.4 % | 0.61 | 0.61 / None | 56.8 % | 4.44 | 5 | 32 |
| 500 | RETAIL_STD | 2318 | 48.4 % | +26.9 % | 1.02 | 1.03 / 1.01 | 51.0 % | 139.20 | 0 | 32 |
| 1,000 | RETAIL_STD | 2742 | 49.0 % | +49.2 % | 1.04 | 0.99 / 1.07 | 33.7 % | 189.24 | 0 | 32 |
| 5,000 | RETAIL_STD | 2742 | 49.0 % | +13.9 % | 1.02 | 0.97 / 1.06 | 35.7 % | 945.72 | 0 | 32 |
| 100 | ECN_LENTO | 73 | 38.4 % | -55.7 % | 0.60 | 0.6 / None | 57.2 % | 16.79 | 5 | 5 |
| 500 | ECN_LENTO | 2739 | 49.1 % | +121.4 % | 1.05 | 1.03 / 1.06 | 50.2 % | 630.89 | 0 | 5 |
| 1,000 | ECN_LENTO | 2743 | 49.1 % | +56.4 % | 1.05 | 1.0 / 1.07 | 34.7 % | 743.13 | 0 | 5 |
| 5,000 | ECN_LENTO | 2743 | 49.1 % | +29.5 % | 1.03 | 0.98 / 1.08 | 35.1 % | 3799.83 | 0 | 5 |
<!-- /HIST_3 -->

<!-- HIST_1.41 -->
## Histórico (backtest 1.41 años)

Motor real sobre M15 XAUUSD-ECN con spread real × perfil, comisión y deslizamiento del perfil, umbral 6.5, 1 operación a la vez, regla de lote del bot (1 % + tope duro 15 %). **No simula** el filtro de noticias, el bloqueo temporal ATR 7.5 ni la latencia (solo `slippage_points`). TRADE_REJECTED = `lot0`; SIGNAL_BLOCKED = señales descartadas por spread (≥ 40 pts o > 25 % del SL; igual para todo balance).

| Balance | Bróker | Ops | Acierto | Neto % | PF | PF IS / OOS | DD máx | Costo USD | TRADE_REJECTED | SIGNAL_BLOCKED |
|---|---|---|---|---|---|---|---|---|---|---|
| 100 | VT_ACTUAL | 136 | 47.8 % | -26.3 % | 0.94 | 0.94 / None | 50.4 % | 8.16 | 0 | 5 |
| 500 | VT_ACTUAL | 1299 | 51.4 % | +129.1 % | 1.08 | 1.08 / 1.08 | 49.2 % | 77.94 | 0 | 5 |
| 1,000 | VT_ACTUAL | 1304 | 51.4 % | +68.2 % | 1.09 | 1.08 / 1.1 | 32.0 % | 79.44 | 0 | 5 |
| 5,000 | VT_ACTUAL | 1304 | 51.5 % | +46.6 % | 1.08 | 1.07 / 1.1 | 27.7 % | 364.86 | 0 | 5 |
| 100 | SPREAD_ALTO | 132 | 46.2 % | -27.5 % | 0.93 | 0.93 / None | 50.1 % | 22.44 | 0 | 149 |
| 500 | SPREAD_ALTO | 763 | 48.9 % | +4.8 % | 1.00 | 1.03 / 0.41 | 52.0 % | 129.71 | 0 | 149 |
| 1,000 | SPREAD_ALTO | 1283 | 49.9 % | +38.5 % | 1.05 | 1.06 / 1.03 | 32.7 % | 219.98 | 0 | 149 |
| 5,000 | SPREAD_ALTO | 1284 | 49.8 % | +20.4 % | 1.04 | 1.04 / 1.03 | 28.9 % | 927.35 | 0 | 149 |
| 100 | RETAIL_STD | 134 | 45.5 % | -29.7 % | 0.93 | 0.93 / None | 51.9 % | 8.04 | 0 | 21 |
| 500 | RETAIL_STD | 730 | 49.2 % | +11.7 % | 1.01 | 1.01 / None | 50.2 % | 43.80 | 0 | 21 |
| 1,000 | RETAIL_STD | 1301 | 50.0 % | +41.1 % | 1.05 | 1.05 / 1.06 | 36.2 % | 78.84 | 0 | 21 |
| 5,000 | RETAIL_STD | 1302 | 50.0 % | +25.4 % | 1.05 | 1.04 / 1.06 | 29.9 % | 335.82 | 0 | 21 |
| 100 | ECN_LENTO | 126 | 46.0 % | -25.0 % | 0.94 | 0.94 / None | 52.3 % | 28.98 | 0 | 5 |
| 500 | ECN_LENTO | 882 | 49.3 % | +16.9 % | 1.01 | 1.06 / 0.78 | 50.3 % | 202.86 | 0 | 5 |
| 1,000 | ECN_LENTO | 1304 | 50.2 % | +46.3 % | 1.06 | 1.05 / 1.07 | 36.9 % | 302.91 | 0 | 5 |
| 5,000 | ECN_LENTO | 1304 | 50.2 % | +29.8 % | 1.05 | 1.04 / 1.07 | 30.8 % | 1303.41 | 0 | 5 |
<!-- /HIST_1.41 -->

<!-- LIVE -->
## Sombra en vivo

Actualizado 2026-11-01 22:00 (hora local). Señales leídas: 65. Lote: regla del bot (1 % + tope duro 15 %). Sin break-even ni trailing. Pista de vetos: LIBRE (sin tope 15 %, lote mínimo si no cabe, varias posiciones a la vez).

### Señales del bot (diario)

| Balance | Bróker | Ops | Acierto | Neto USD | Neto % | PF | Comisión | TRADE_REJECTED | SIGNAL_BLOCKED | BLOQUEADA_BOT | OCUPADA | Abierta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 67.77 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 3 | 0 | 0 |
| 67.77 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 3 | 0 | 0 |
| 67.77 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 3 | 0 | 0 |
| 67.77 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 3 | 0 | 0 |
| 100 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 100 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 100 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 100 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 500 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 500 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 500 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 500 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 1,000 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 1,000 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 1,000 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 1,000 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 5,000 | VT_ACTUAL | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 5,000 | SPREAD_ALTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 5,000 | RETAIL_STD | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |
| 5,000 | ECN_LENTO | 0 | 0 % | +0.00 | +0.00 % | 0.00 | 0.00 | 0 | 0 | 4 | 0 | 0 |

### Señales vetadas por ⛔ ADX/tendencia, si se hubieran operado (sin 🌡/🌪/📰)

| Balance | Bróker | Ops | Acierto | Neto USD | Neto % | PF | Comisión | TRADE_REJECTED | SIGNAL_BLOCKED | BLOQUEADA_BOT | OCUPADA | Abierta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 67.77 | VT_ACTUAL | 53 | 60 % | +216.02 | +318.75 % | 2.05 | 3.18 | 6 | 0 | 0 | 0 | 0 |
| 67.77 | SPREAD_ALTO | 53 | 60 % | +209.98 | +309.84 % | 2.01 | 3.71 | 6 | 0 | 0 | 0 | 0 |
| 67.77 | RETAIL_STD | 53 | 60 % | +211.88 | +312.65 % | 2.03 | 0.00 | 6 | 0 | 0 | 0 | 0 |
| 67.77 | ECN_LENTO | 53 | 60 % | +215.72 | +318.31 % | 2.04 | 3.71 | 6 | 0 | 0 | 0 | 0 |
| 100 | VT_ACTUAL | 54 | 61 % | +221.67 | +221.67 % | 2.07 | 3.24 | 0 | 0 | 0 | 5 | 0 |
| 100 | SPREAD_ALTO | 54 | 61 % | +215.14 | +215.14 % | 2.04 | 3.78 | 0 | 0 | 0 | 5 | 0 |
| 100 | RETAIL_STD | 54 | 61 % | +217.33 | +217.33 % | 2.05 | 0.00 | 0 | 0 | 0 | 5 | 0 |
| 100 | ECN_LENTO | 54 | 61 % | +221.80 | +221.80 % | 2.07 | 3.78 | 0 | 0 | 0 | 5 | 0 |
| 500 | VT_ACTUAL | 54 | 61 % | +221.67 | +44.33 % | 2.07 | 3.24 | 0 | 0 | 0 | 5 | 0 |
| 500 | SPREAD_ALTO | 54 | 61 % | +215.14 | +43.03 % | 2.04 | 3.78 | 0 | 0 | 0 | 5 | 0 |
| 500 | RETAIL_STD | 54 | 61 % | +217.33 | +43.47 % | 2.05 | 0.00 | 0 | 0 | 0 | 5 | 0 |
| 500 | ECN_LENTO | 54 | 61 % | +221.80 | +44.36 % | 2.07 | 3.78 | 0 | 0 | 0 | 5 | 0 |
| 1,000 | VT_ACTUAL | 54 | 61 % | +221.67 | +22.17 % | 2.07 | 3.24 | 0 | 0 | 0 | 5 | 0 |
| 1,000 | SPREAD_ALTO | 54 | 61 % | +215.14 | +21.51 % | 2.04 | 3.78 | 0 | 0 | 0 | 5 | 0 |
| 1,000 | RETAIL_STD | 54 | 61 % | +217.33 | +21.73 % | 2.05 | 0.00 | 0 | 0 | 0 | 5 | 0 |
| 1,000 | ECN_LENTO | 54 | 61 % | +221.80 | +22.18 % | 2.07 | 3.78 | 0 | 0 | 0 | 5 | 0 |
| 5,000 | VT_ACTUAL | 54 | 61 % | +644.85 | +12.90 % | 1.80 | 11.94 | 0 | 0 | 0 | 5 | 0 |
| 5,000 | SPREAD_ALTO | 54 | 61 % | +621.24 | +12.42 % | 1.77 | 13.93 | 0 | 0 | 0 | 5 | 0 |
| 5,000 | RETAIL_STD | 54 | 61 % | +629.43 | +12.59 % | 1.78 | 0.00 | 0 | 0 | 0 | 5 | 0 |
| 5,000 | ECN_LENTO | 54 | 61 % | +645.12 | +12.90 % | 1.80 | 13.93 | 0 | 0 | 0 | 5 | 0 |
<!-- /LIVE -->
