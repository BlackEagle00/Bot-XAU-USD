# ADR 0004: Operar cuentas pequeñas con riesgo elevado acotado al 5 %

## Estado
Aceptado

## Fecha
2026-10-16

## Contexto
- **Problema.** Con 100 USD, el lote mínimo de muchos activos arriesga más del 1 % del capital. El
  bot los saltaba, así que la cuenta casi no operaba. El usuario pidió poder operar desde 100 USD o
  menos aceptando más riesgo, con un tope de **5 % por operación**.
- **Riesgo combinado.** Dos bots en la misma cuenta podían sumar dos límites diarios.

## Decisión
- **Lote mínimo con riesgo elevado.** Si el lote al 1 % queda por debajo del mínimo, pero el lote
  mínimo arriesga ≤ `MAX_RISK_MIN_LOT` (por defecto 0.05), `lot_plan` devuelve el lote mínimo.
  También informa con cuánto capital se vuelve al 1 %. El log y el panel lo marcan como **riesgo elevado**.
- **Si ni el 5 % alcanza**, el lote es 0 y el activo no se opera. Pasa, por ejemplo, con el oro H4
  y 100 USD.
- **Niveles de capital.** Se mantienen: Micro < 500 USD tiene 1 operación abierta y corte del 5 %
  diario; Pequeño, 2 operaciones y 7 %; Estándar, los valores del config.
- **Límite diario de cuenta.** `ACCOUNT_MAX_DAILY_LOSS_PCT` (por defecto 0.10) suma los cierres de
  **todos** los números mágicos más el flotante, y bloquea a todos los bots.

## Alternativas consideradas
- **Riesgo fijo en 1 %.** Es lo más seguro, pero con 100 USD casi nunca opera. Va contra lo que pidió el usuario.
- **Sin tope.** El oro H4 arriesgaría ~30 % por operación. Inaceptable.

## Consecuencias
- Con 5 % por operación, 10 pérdidas seguidas ≈ −40 % de la cuenta. Hay que declararlo y mostrarlo.
- El backtest usa la misma `lot_plan`, así que los resultados con 100 USD ya reflejan este riesgo.
