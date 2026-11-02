# Sistema XAUUSD — controles de ejecución (2026-10-27)

Informe de las etapas 1 (seguridad de ejecución), 2 (backtest con costes y línea base) y 3 (experimentos).
La etapa 4 (resto de la documentación) sigue pendiente. Las etapas 1 y 2 no cambian la estrategia. La etapa 3
cambia dos cosas, cada una con evidencia fuera de muestra: Scalping salta el régimen de volatilidad baja y Swing
apaga el filtro ML. Los resultados son de backtest, no una promesa de rentabilidad.

## Qué cambió

| Módulo | Cambio |
|---|---|
| `bot_engine/coordinator.py` (nuevo) | Instancia única por bot; estados `IDLE` / `<MOTOR>_ACTIVE` / `DRAINING` / `SAFE_MODE` según el bróker; estado persistente; cortacircuitos; `validate_config()`; conciliación al arrancar. |
| `bot_engine/journal.py` (nuevo) | Diario JSONL `<bot>/journal.jsonl`: una línea por decisión, con versión git y hash de config (sin credenciales). |
| `trade_manager.open_trade` | `order_check` antes de enviar; sin respuesta → concilia **sin reenviar**; `DONE_PARTIAL` cuenta como fill; verifica el SL en la posición (lo repone o cierra la posición); registra precio pedido/real, slippage y latencia. Sigue devolviendo el ticket (no cambia para `core`, el panel ni `test_runner`). |
| `risk_manager.can_open_trade` | Si falla la lectura de posiciones de la cuenta, bloquea (antes contaba 0 abiertas). |
| `core` | Compuerta del coordinador antes de cada entrada; estado persistido cada ciclo; `terminal_info().connected`; filtro ML fail-closed. |
| `news_filter` | Una caché de otra semana o de más de 24 h cuenta como "calendario no disponible" (aplica `NEWS_FAIL_OPEN`). |
| configs | `ORDER_FAIL_LIMIT=3`, `STALE_TICK_SEC` (120 scalping / 600 swing), `ML_FAIL_CLOSED=True`. |

## Estados del coordinador

Solo `IDLE` y el estado del propio motor autorizan entradas. Las posiciones abiertas se gestionan
(BE+, trailing, cierres) en cualquier estado.

| Estado | Cuándo |
|---|---|
| `IDLE` | Sin posiciones ni órdenes en el símbolo. |
| `SCALPING_ACTIVE` / `SWING_ACTIVE` | Solo hay posiciones u órdenes de este motor (los límites los pone `risk_manager`). |
| `DRAINING` | Hay posiciones u órdenes de **otro** magic en el símbolo: el otro bot, el panel (20260630) o manuales (magic 0). |
| `SAFE_MODE` | Cortacircuitos activo, configuración inválida o no se pudo leer el bróker. |

Además de los estados, `entry_gate` rechaza entradas por cuatro motivos:
- el terminal está desconectado;
- Algo Trading está apagado;
- el precio no cambió en `STALE_TICK_SEC` (pausa diaria o feed caído);
- la cuenta cambió, o pasó a real sin `ALLOW_LIVE_TRADING=1`. Este último motivo también activa `SAFE_MODE`.

## Cortacircuitos (`SAFE_MODE`)

| Disparo | Cómo se suelta |
|---|---|
| `ORDER_FAIL_LIMIT` rechazos seguidos (`order_check` u `order_send`) | Reiniciar el bot: la conciliación lo suelta si las posiciones propias se leen y todas tienen SL. |
| Orden sin respuesta y sin posición nueva en el bróker ("resultado desconocido") | Igual. **Revisa MT5 antes de reiniciar.** |
| Posición propia sin SL que no se pudo reponer (se intenta cerrarla) | Igual, una vez protegida o cerrada. |
| Cambio de cuenta en el terminal / cuenta real sin la variable | Igual. |
| `state.json` corrupto (se guarda como `state.json.corrupt`) | Manual: revisar y **borrar** `state/state.json.corrupt`, luego reiniciar. |

Persisten entre reinicios (`<bot>/state/state.json`, escritura atómica): la última vela operada, el pico
de equity y el corte por drawdown, el día del corte diario, los fallos de orden y el cortacircuitos.
Antes, reiniciar borraba el corte por drawdown y el diario.

## Operación

- Arrancar en real (solo si el usuario lo pide): `ALLOW_LIVE_TRADING=1` **solo en el proceso**, nunca en `.env`.
- Una segunda copia del mismo bot aborta al arrancar ("Ya hay otra instancia").
- Leer el diario (cada `rejected` dice por qué no se operó una señal):
  `Get-Content xauusd_scalping_bot\journal.jsonl -Tail 20`
- Eventos: `start`, `signal`, `rejected`, `authorized`, `refused`, `sent`, `filled`, `protected`, `unprotected`, `unknown`, `breaker`, `breaker_cleared`.
- `state/` y `journal.jsonl` están en `.gitignore`.

## Verificación hecha (2026-10-27)

- `python tests/test_engine.py`: **68 pruebas OK** (55 anteriores + 13 nuevas: instancia única,
  `DRAINING` / `SAFE_MODE`, estado y archivo corrupto, conciliación, fallos seguidos, compuerta de
  entrada, config inválida, `order_check`, sin respuesta sin reenvío, fill parcial, SL ausente,
  lectura fallida en `can_open_trade`, caché de noticias vieja, ML fail-closed). Los mocks reproducen la
  API documentada de MT5; **no equivalen al servidor real**.
- En vivo (cuenta real, XAUUSD-ECN, hedging):
  - `order_check` de solo verificación devolvió 0, con un margen de 8.12 USD;
  - el coordinador marcó `IDLE`;
  - sin la variable `ALLOW_LIVE_TRADING` bloqueó la cuenta real;
  - el bot se relanzó a las 18:48 con la conciliación en 0 posiciones;
  - una segunda copia abortó.

## Etapa 2: backtest con costes y línea base congelada (2026-10-27)

- **Costes nuevos** en `backtesting/engine_backtest.py`, con valor 0 por defecto, así que los resultados viejos se reproducen idénticos:
  - `BT_COMMISSION_PER_LOT`: USD por lote, ida y vuelta.
  - `BT_SLIPPAGE_POINTS`: puntos por lado. Se descuenta del P&L y no mueve el precio dentro de la triple barrera.
  - Cuando hay costes, la `r` de cada operación es **neta** y la bruta queda en `r_gross`.
- **Comisión real medida:** 126 deals de la cuenta real en XAUUSD-ECN, todos con −0.03 USD por lado por cada 0.01 lote, es decir **6 USD por lote ida y vuelta**.
- **Swap:** es por puntos (largo −76.2, corto +36.6 por lote y día). No se modela porque el Scalping cierra en 120 min como máximo.
- **Métricas nuevas por balance:**
  - `sortino`, `net_expectancy_usd`, `cost_total` y `cost_per_trade`;
  - `r_dist`: percentiles e histograma de 0.5 R;
  - `by_regime`: ADX tendencia/lateral × terciles de ATR%, calculado con las 2 000 velas previas y sin mirar el futuro (hay una prueba que lo verifica).
- **Reporte:** incluye `engine_hash` y `costs`, y `not_simulated` ya no lista lo que sí se simula.
- **Línea base congelada:** `backtesting/baselines/baseline_scalping_2026-10-27.json`. Contiene el comando exacto, el periodo 2023-10-27 → 2026-10-27, el `engine_hash` y las métricas. Cada cambio de estrategia se compara contra ella con el mismo comando.

Resultados de M15, score 6.5, una operación a la vez, spread real por hora:

| Cuenta 1 000 USD | Sin costes | Con comisión real |
|---|---|---|
| Operaciones | 3 831 | 3 831 |
| PF (IS / OOS) | 1.06 (1.06 / 1.05) | **1.04 (1.04 / 1.05)** |
| Neto 3 años / DD máx. | +106.2 % / 35.4 % | **+74.5 % / 40.7 %** |
| Sharpe / Sortino | 0.93 / 1.58 | 0.74 / 1.24 |
| Expectativa | 0.026 R (0.28 USD) | 0.016 R (0.20 USD) |
| Coste por operación | 0 | 0.09 USD (total 349.6 USD) |
| Monte Carlo: DD p95 / P(pérdida) | 58 % / 9 % | 65 % / **24 %** |

Por régimen, con comisión: volatilidad alta PF 1.17 (1 505 op.), media PF 0.99 (1 179) y baja **PF 0.94** (1 147).
Ninguna operación cae en "lateral" porque el filtro ADX ya bloquea esas entradas. Que la volatilidad baja pierda es una hipótesis para la etapa 3, todavía sin aplicar.

**Cuenta de 55 USD:** 20 operaciones, PF 0.42 y −47.6 %. El corte por drawdown se activa el 2023-11-08 y después el bot no opera más. Con un solo comienzo, ese resultado depende de la suerte de las primeras operaciones; la ventaja (pequeña) solo aparece con cientos de operaciones.

## Etapa 3: experimentos (2026-10-27)

Mismo comando que la línea base (M15, score 6.5, una operación, spread real, comisión de 6 USD por lote) y una sola
variante por corrida. Todas las opciones nuevas están apagadas por defecto; con todo apagado, el motor reproduce la
línea base exacta (3 831 operaciones, PF 1.04, +74.5 %), y eso también lo verifica una corrida.

| Scalping, 1 000 USD | Op. | PF (IS / OOS) | Neto | DD | MC P(pérdida) | Decisión |
|---|---|---|---|---|---|---|
| Línea base | 3 831 | 1.04 (1.04 / 1.05) | +74.5 % | 40.7 % | 24 % | — |
| **Sin volatilidad baja** (`SKIP_REGIMES`) | 2 743 | **1.10 (1.08 / 1.11)** | +126 % | **23.7 %** | **4 %** | **Activado** |
| Tope de la familia de tendencia = 4 (`TREND_FAMILY_CAP`) | 1 043 | 1.07 (**0.87** / 1.20) | +31 % | 31.8 % | 57 % | Descartado: pierde en IS |
| Tope de la familia de tendencia = 6 | 2 964 | 1.02 (1.04 / 1.01) | +28 % | 48.1 % | 44 % | Descartado |
| VWAP de sesión (`VWAP_SESSION`) | 3 785 | 1.05 (1.04 / 1.06) | +88 % | 34.3 % | 23.5 % | Experimental: mejora dentro del ruido |

- **Régimen.** La etiqueta es ADX × tercil del ATR% de las 2 000 velas anteriores (`indicators.regime_labels`, una
  sola función para el backtest y para el bot en vivo).
  - **Cómo se eligió:** en IS, la volatilidad baja era la peor (PF 0.97, contra 1.06 la alta y 1.08 la media), y
    en OOS se confirmó (PF 0.90).
  - **En vivo:** `core._regime_now()` baja 2 600 velas cerradas (2 000 para los terciles y 600 de calentamiento) y
    rechaza la entrada con "🌡 … régimen tendencia/baja". Sin historia suficiente, también rechaza.
  - **Paridad:** en 1 500 velas reales elegidas al azar, la etiqueta en vivo y la del backtest coincidieron
    1 500/1 500.
  - **Ojo:** en OOS la volatilidad media también perdió (PF 0.93). No se filtra porque en IS ganaba (1.08); filtrarla
    ahora sería ajustar al resultado.
- **Familia de tendencia.** EMA, MACD, el TF de tendencia y el macro derivan de medias móviles. Ponerle un tope a
  su suma sacrifica más señales buenas que ruido.
- **VWAP de sesión.** Se reinicia a las 00:00 del servidor y pondera con `tick_volume` (actividad del bróker, no
  volumen real negociado).
- **Cuenta de 55 USD:** con el filtro, 60 operaciones, PF 0.74 y −49.5 %. El corte por caída máxima (50 %) sigue
  deteniéndolo pronto. La ventaja solo aparece con cientos de operaciones.

| Swing, 1 000 USD, comisión + swap reales, sin el corte por caída máxima | Op. | PF (IS / OOS) | Neto | DD |
|---|---|---|---|---|
| **H4/D1/W1 (actual)** | 231 | **1.27 (1.08 / 1.45)** | +131 % | 41.2 % |
| H1/H4/D1 | 796 | 1.10 (1.23 / 1.04) | +95 % | 40.6 % |

- **Temporalidades.** Se queda en H4: H1/H4/D1 es peor fuera de muestra. Con el corte por caída máxima vigente
  (30 %), las dos variantes llegan a él y dejan de operar, así que esta tabla se corrió sin el corte.
- **Filtro ML** (walk-forward trimestral, con calibración nueva por ventana: `brier`/`logloss` frente a la tasa
  base):
  - con el filtro, OOS da 106 operaciones, PF **0.90** y −15.6 %; sin el filtro, en el mismo periodo, PF 1.09 y
    +8.4 %;
  - el Brier del modelo fue peor que la tasa base en 6 de 8 ventanas, así que las probabilidades no informan.
  - → `USE_ML_FILTER = False` en `xauusd_bot/config.py`. Además, en XAUUSD-ECN no hay ningún modelo (el que existe es
    de `XAUUSD`), así que con `ML_FAIL_CLOSED` Swing habría bloqueado todas sus entradas.
  - Pendiente: reetiquetar a "TP antes que SL" y volver a entrenar.
- **Swap en el backtest:** `BT_SWAP_LONG_POINTS` / `BT_SWAP_SHORT_POINTS` (puntos por lote y noche, sin el triple de
  los miércoles).

## Experimento: M5 como entrada de las señales de M15 (2026-10-28)

Backtest de M15 en la ventana que cubre el M5 del bróker (2025-06-02 → 2026-10-27, 17 meses), 1 000 USD, mismos costes
y filtro de la etapa 3. Opciones solo de backtest (`--set`): `ENTRY_EXEC_TF="M5"`, `ENTRY_MODE` y `ENTRY_PULLBACK_ATR`.
Sin ellas, el resultado es idéntico: V0 repite `_m15same` exacto.
Criterios fijados antes de correr: OOS +0.02 R y PF OOS ≥ control, IS no peor, ≥ 60 % de las operaciones, DD y p_loss no peores.

| Variante | Op. | PF (IS / OOS) | R/op | DD | p_loss MC | 55 USD |
|---|---|---|---|---|---|---|
| Control M15 a mercado (recorrido M5) | 1 303 | 1.09 (1.08 / 1.10) | +0.036 | 31.9 % | 12.6 % | −12.3 % |
| Retroceso 0.15 ATR | 1 182 | 1.06 (1.08 / 1.04) | +0.020 | 33.3 % | 30.3 % | −52.1 % |
| Retroceso 0.25 ATR | 1 102 | 1.06 (1.05 / 1.08) | +0.026 | 32.1 % | 28.7 % | −43.5 % |
| Retroceso 0.40 ATR (mejor en IS) | 957 | 1.11 (1.13 / 1.07) | +0.057 | 16.8 % | 10.3 % | −35.5 % |
| Confirmación vela + EMA9/21 de M5 | 979 | 1.05 (1.04 / 1.06) | +0.003 | 45.0 % | 52.4 % | −35.2 % |
| M5 como TF primario (sin M15) | 3 477 | 1.03 (0.92 / 1.04) | −0.004 | 44.6 % | 68.8 % | −27.4 % |

**Decisión: no se adopta.** El retroceso de 0.40 ATR (elegido en IS) baja el DD a la mitad, pero su PF fuera de muestra
(1.07) queda por debajo del control (1.10): no cumple el criterio 1. La confirmación y M5 como primario no tienen ventaja.
Revisar el retroceso de 0.40 cuando haya más historia de M5 (hoy, un solo régimen de mercado).

## Guardas de riesgo post-Fed (2026-10-28)

Pedido del usuario tras el pico de la Fed: tres guardas nuevas para una cuenta pequeña.

- **Spread al enviar** (`trade_manager.open_trade`): con el tick del envío, si el spread es ≥ `MAX_SPREAD_POINTS` (40 pts), no se manda la orden y queda `SIGNAL_BLOCKED: Spread abuse detected`. 40 pts es más estricto que los 4.5 pips (45 pts) propuestos. En 30 días el spread real tuvo mediana 10 y máximo 17.
- **Tope duro del lote mínimo** (`MIN_LOT_CAP_HARD`): rechaza la entrada (`TRADE_REJECTED: …`) si el lote 0.01 arriesga más que `MAX_RISK_MIN_LOT` (15 %). No activa los niveles de cuenta de `ENFORCE_CAPITAL_LEVEL`. Se descartó el 2 % literal: con 57 USD habría rechazado el 100 % hasta unos 490 USD de balance.
- **Velas M1 anómalas** (`anomalous_bars` + `core._anomaly_now`): si una vela M1 tiene un rango mayor que 3× la media de las 20 anteriores, se bloquean las entradas durante 30 min. Es sin estado: el enfriamiento sale de las propias velas. Se descartó la regla de mechas > 70 %, que se cumple en el 29 % de las velas M1 y bloquearía el 100 % del tiempo. `ANOMALY_BLOCK=False` (solo informa, "⚡ (simulado)") hasta validarlo.

Backtest: M15, 1.41 años desde 2025-06-02, spread real, comisión 6 USD/lote, umbral 6.5 y `SKIP_REGIMES=('tendencia/baja',)`.

| Variante | 1000 USD: op / PF / neto / DD | 55 USD: op / PF / neto / corte por DD |
|---|---|---|
| Control (`_ctl`) | 1304 / 1.09 (IS 1.08, OOS 1.10) / +68.2 % / 32.0 % | 27 / 0.94 / −12.8 % / 2025-06-19 |
| Tope duro 15 % (`_hard15`) | igual (no actúa con 1000) | 13 / 0.47 / −44.0 % / 2025-08-04 (268 rechazos) |
| M1 anómala 3× (`_anom3`) | 1276 / 1.09 (IS 1.08, OOS 1.10) / +67.4 % / 32.0 % | igual que el control |

Lectura:
- **Tope del 15 %:** con 55 USD no salva la cuenta; solo retrasa el corte por DD (de junio a agosto de 2025) y empeora el PF. Quita sobre todo operaciones de volatilidad alta, que son las mejores del sistema: tendencia/alta tiene PF 1.18 y tendencia/media 0.96 (control a 1000). Reduce la pérdida por operación, no mejora la ventaja.
- **Velas M1:** el terminal solo tiene M1 desde 2026-07-20 (3 meses), así que el filtro actúa únicamente ahí. Quita 28 operaciones de 1304 (2 %) con un efecto neutro: PF y DD iguales, −0.8 pp de neto. Cumple el criterio pre-registrado (PF OOS ≥ control y DD ≤ control) solo por empate, sin evidencia de mejora. Muestra corta.

## Filtro M30 (experimento, 2026-10-28) — NO activado en vivo

`--set M30_FILTER='ema21'|'ema50'` (clave de backtest, `POST_KEYS`): la señal M15 solo entra si la última vela M30
**cerrada** al abrir la vela de entrada tiene EMA9 por encima (BUY) o por debajo (SELL) de la EMA21 / EMA50.
Misma base que el control (spread real, comisión 6, umbral 6.5, 1 operación, tope duro 15 %), 1 000 USD:

| Periodo | Variante | Ops | PF | PF IS / OOS | Neto | DD |
|---|---|---|---|---|---|---|
| 1.41 años | control | 1305 | 1.09 | 1.08 / 1.10 | +69.0 % | 31.5 % |
| 1.41 años | M30 EMA9/21 | 1276 | 1.07 | 1.08 / 1.05 | +52.6 % | 39.0 % |
| 1.41 años | M30 EMA9/50 | 1276 | 1.10 | 1.11 / 1.09 | +76.8 % | 30.7 % |
| 3 años | control | 2746 | 1.10 | 1.08 / 1.10 | +126.4 % | 23.5 % |
| 3 años | M30 EMA9/21 | 2694 | 1.09 | 1.06 / 1.10 | +109.8 % | 27.4 % |
| 3 años | M30 EMA9/50 | 2688 | 1.11 | 1.08 / 1.13 | +148.2 % | 22.7 % |

EMA9/21 empeora en los dos periodos. EMA9/50 quita ~2 % de las operaciones y mejora un poco el neto, pero el PF
fuera de muestra no mejora en los dos periodos (1.09 vs 1.10 en 17 meses; 1.13 vs 1.10 en 3 años): diferencia dentro
del ruido. Con 57 USD EMA9/50 es idéntico al control. Decisión: no se implementa en vivo; la vela M30 queda como
contexto en los reportes.

## Límites conocidos

- Aún no se ha probado ninguna orden real con el código nuevo: la ruta de fill y protección se verificó solo con mocks.
- La conciliación tras un resultado vacío espera 3 s. Si el bróker tarda más, entra en `SAFE_MODE` por precaución.
- En una cuenta netting, una posición que suma volumen a otra ya abierta no se distingue por ticket nuevo: se usa la posición propia más reciente. La cuenta actual es hedging.
- El panel (`dashboard/worker.py`) usa el `open_trade` verificado, pero no consulta el coordinador antes de abrir. Una orden del panel deja al bot en `DRAINING`, no al revés.
- El slippage sigue en 0 en el backtest hasta medirlo con órdenes reales (la primera, #19599627, tuvo 0 puntos).
