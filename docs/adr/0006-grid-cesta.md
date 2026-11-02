# ADR 0006: Bot de oro "scalping + grid + cesta" y bots solo XAUUSD

## Estado
Aceptado

## Fecha
2026-10-23

## Contexto
- **Pedido.** El usuario quiso concentrar los bots en XAUUSD y sumar un tercer bot. Ese bot abre varias
  operaciones cortas a la vez, incluso con órdenes pendientes que se activan al tocar un precio. Las
  cierra con un margen de profit, sin exigir el TP de cada una, y deja que el capital lo refleje. El
  lote debe crecer con la cuenta.
- **El panel** debía seguir cubriendo todos los activos y sumar una vista Grid solo para XAUUSD.
- **Realidad del grid.** Gana muchas veces poco en rango y pierde de golpe en tendencia. Sin un stop de
  cesta, una tendencia larga del oro (50–100 USD) vacía la cuenta.

## Decisión
- **Módulo `bot_engine/grid.py`**, activado por `USE_GRID`. Tiene funciones puras (`build_basket`,
  `basket_pnl`, `basket_decision`, `entry_allowed`, `must_flatten`, `dd_halt`) que comparten el bot, el
  panel y el backtest.
- **Revisión v2 (mismo día, tras el primer backtest):** la v1 (stop −10 % y 0.01 lote por $200) perdía
  hasta un 91 % de drawdown y quemaba las cuentas de $100. La v2 dimensiona por riesgo de la cesta
  completa, usa un SL real como stop, cierra los viernes y tiene un corte por drawdown.
- **Ajuste final (turno 2):** la suite v2 solo encontró una variante que pasara el in-sample, en H1 (lote
  fijo, umbral 4, TP de cesta 0.25R, riesgo 2 %: PF 1.13→1.10). El grid pasa a H1 y hereda la señal del bot
  swing, que ahora también es H1.
- **Cesta.** Nivel 0 a mercado + límites pendientes, cada una con su TP corto (se re-arma). Se cierra
  por TP de cesta, **stop duro de cesta + tiempo máximo** (elección del usuario) y SL de emergencia.
- **Lote.** `"fixed"` o `"martingale"`, configurable. Los dos se prueban en el backtest.
- **Bots EUR/USD retirados del lanzador.** Sus configs pasan a `dashboard/profiles/_forex_base/` porque
  los perfiles de divisas del panel los heredan.
- **Datos de otros activos** archivados fuera del repo (`../_archivo_otros_activos/`). Se pueden volver
  a bajar de MT5.

## Alternativas consideradas
- **Grid sin stop** ("cerrar solo en profit"). Da un acierto altísimo hasta la primera tendencia,
  y ahí la cuenta queda en cero. Descartado.
- **Grid como modo del bot de scalping.** Mezclaba la gestión SL/TP/trailing con la de cesta. Un bot
  aparte, con su propio magic, mantiene separados sus riesgos y sus logs.

## Consecuencias
- El backtest reporta el grid por **cesta**: % de cestas ganadoras, peor cesta, salidas TP/STOP/TIEMPO,
  Monte Carlo del retorno por cesta e IS/OOS. Un acierto alto no implica rentabilidad: hay que mirar
  el PF y la peor cesta.
- Con poco capital el lote mínimo (0.01) ya es grande frente al ATR del oro. La v2 entonces usa menos
  niveles o no opera: el panel y el log muestran el capital necesario, en vez de arriesgar más de lo previsto.
