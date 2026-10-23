# Arquitectura

Cómo está armado el sistema y por qué. Las decisiones grandes tienen su ADR en [`adr/`](adr/).
Los valores numéricos exactos viven en cada `config.py`; aquí solo se citan para dar escala.

## Vista general

Tres programas usan **un solo motor** (`bot_engine/`):

```mermaid
flowchart LR
    subgraph Programas
        B["Bots automáticos<br/>xauusd_bot, xauusd_scalping_bot,<br/>eurusd_bot, eurusd_scalping_bot"]
        P["Panel web<br/>dashboard/server.py + 6 worker.py"]
        T["Backtest<br/>backtesting/engine_backtest.py<br/>backtesting/calibrate.py"]
    end
    E["bot_engine/<br/>indicadores · patrones · señales<br/>riesgo · órdenes · filtro predictivo"]
    C1["config.py del bot"] --> B
    C2["dashboard/profiles/&lt;clase&gt;_&lt;modo&gt;/config.py"] --> P
    C2 --> T
    C1 --> T
    B --> E
    P --> E
    T --> E
    E <--> MT5[("Terminal MetaTrader 5<br/>(cuenta demo)")]
    M[("models/*.joblib<br/>+ manifest.json")] --> E
    T -- "entrena y registra" --> M
```

- **Un proceso por config.** El motor importa `from config import …`. Cada proceso pone la carpeta
  de su config primero en `sys.path`, así que dos configs nunca chocan
  ([ADR 0001](adr/0001-motor-compartido.md)).
- **MT5 es la única fuente de datos y de órdenes.** El paquete `MetaTrader5` solo funciona en
  Windows, con el terminal abierto en el mismo usuario.

## El ciclo del bot

`bot_engine/core.py` → `run()` repite `_run_cycle()` cada `LOOP_INTERVAL` segundos:

```mermaid
flowchart TD
    A[connection: verifica MT5 y cuenta demo] --> B[data_handler: velas de 3 temporalidades<br/>sin la vela en formación]
    B --> C[trade_manager: break-even y trailing<br/>solo con ganancia]
    C --> D[indicators + patterns]
    D --> E[signals.generate_signal<br/>score ponderado + filtros]
    E -->|HOLD| Z[esperar]
    E -->|BUY/SELL| F{ml_filter<br/>P de TP antes que SL ≥ τ}
    F -->|no| Z
    F -->|sí o sin modelo| G[news_filter → can_open_trade<br/>anti-duplicado → spread_ok]
    G --> H[calculate_sl_tp → lot_plan<br/>riesgo según capital]
    H --> I[open_trade]
```

| Etapa | Módulo | Nota |
|---|---|---|
| Datos | `data_handler.py` | Las horas son del **servidor** (`server_now()`), nunca la hora local. |
| Indicadores | `indicators.py` | EMA, RSI, MACD, ATR, ADX, Bollinger, VWAP, soportes y resistencias. |
| Patrones | `patterns.py` | 44 patrones de velas; su aporte al score se limita a ±4. |
| Señal | `signals.py` | Score ponderado (rango aprox. ±12) contra `MIN_SIGNAL_SCORE`; filtros de tendencia, RSI, ADX y macro. |
| Filtro predictivo | `ml_filter.py` | Meta-labeling con gradient boosting; solo carga modelos registrados en el manifiesto ([ADR 0002](adr/0002-filtro-predictivo-walk-forward.md)). |
| Riesgo | `risk_manager.py` | Nivel de capital, lote dinámico, riesgo elevado hasta 5 %, límite diario por bot y por cuenta ([ADR 0004](adr/0004-riesgo-cuentas-pequenas.md)). |
| Órdenes | `trade_manager.py` | Filling mode, `stops_level`, BE+, trailing progresivo; todo filtrado por `MAGIC_NUMBER`. |

## El panel web

```mermaid
sequenceDiagram
    participant N as Navegador (127.0.0.1)
    participant S as server.py
    participant W as worker.py (1 por perfil)
    participant M as MT5
    participant F as Feeds de noticias
    S->>W: arranca 6 procesos (forex/metals/stocks × scalping/swing)
    loop cada ciclo
        W->>M: velas, ticks y cuenta
        W-->>S: {"type":"analysis", ...} por stdout
    end
    loop cada 10 min
        S->>F: RSS (Google Noticias, CNBC, Investing) + calendario ForexFactory
    end
    N->>S: GET /api/analysis?mode=swing
    S-->>N: secciones unidas de los perfiles de ese modo
    N->>S: GET /api/news
    N->>S: POST /api/trade + X-Token
    S->>S: valida Host/Origin, token, lista blanca, 1 orden por activo cada 5 s
    S->>W: {"type":"trade", "ts": ...} por stdin
    W->>M: mismas compuertas que el bot y order_send
    W-->>S: trade_result
    S-->>N: "Se ha realizado la apertura de una operación BUY…"
```

- **Solo librería estándar** (`http.server`, `xml.etree`, `urllib`), sin CDN de scripts
  ([ADR 0005](adr/0005-panel-stdlib.md)). Las fuentes se cargan de Google Fonts y tienen respaldo del sistema.
- **Protocolo JSON por líneas.** El worker manda los logs del motor a stderr para no corromper stdout.
- **Gotcha de Windows.** El worker carga los modelos de scikit-learn **antes** de iniciar el hilo
  que lee stdin. Importar sklearn mientras un hilo bloquea `sys.stdin` deja el proceso colgado.
- **Órdenes viejas.** El worker descarta una orden con más de `TRADE_MAX_AGE` = 15 s; así nunca
  abre una orden que el servidor ya informó como vencida.
- **Horarios.** El servidor entrega epoch, y la página los convierte a la hora del sistema con `Intl`.
  Las sesiones de mercado se calculan con zonas IANA (Nueva York, Londres, Tokio, Sídney), así que
  el cambio de horario se maneja solo.
- **Ventaja de cada perfil.** El worker lee `backtesting/reports/calibration_<perfil>.json`. Si el PF
  fuera de muestra de la configuración vigente es ≤ 1, la página muestra "Sin ventaja probada".

## Perfiles por clase de activo

`dashboard/profiles/_base.py` → `profile(name, base, tf, sections, **overrides)` arma el config de
cada clase partiendo del config de un bot ([ADR 0003](adr/0003-perfiles-por-clase.md)):

| Perfil | Hereda de | Activos |
|---|---|---|
| `forex_swing` / `forex_scalping` | `eurusd_bot` / `eurusd_scalping_bot` | EURUSD, GBPUSD, USDJPY, AUDUSD |
| `metals_swing` / `metals_scalping` | `xauusd_bot` / `xauusd_scalping_bot` | XAUUSD, XAGUSD |
| `stocks_swing` / `stocks_scalping` | configs del oro, sin claves en dólares | AAPL, NVDA, TSLA, MSFT, AMZN, GOOG, META, IBIT, ETH |

Los parámetros que elige `backtesting/calibrate.py` se escriben debajo de la marca
`# ── Parámetros calibrados para esta clase …` de cada `config.py`, junto con un comentario que
registra la fecha y las métricas fuera de muestra.

## Backtest y calibración

```mermaid
flowchart LR
    H[(Histórico MT5<br/>3 años)] --> S[Señales del motor real<br/>multiprocessing + caché por hash]
    S --> O[Resultado de cada señal<br/>triple barrera, spread real,<br/>BE y trailing reales]
    O --> SIM[simulate: cuenta con 100 / 1 000 / 10 000 USD]
    O --> WF[walk-forward trimestral con purga]
    WF --> ML[modelo por activo<br/>se guarda solo si OOS ≥ 75 % y PF > 1]
    S -- "umbral ≈ 0" --> CAL[calibrate.py<br/>rejilla por clase]
    CAL --> CFG[config.py del perfil]
```

- **Caché de señales.** La clave es `engine_hash`: el código de `bot_engine/`, el config del perfil,
  `_base.py`, los 4 configs de bots y los `--set`. Cambiar cualquiera de esos archivos invalida la caché.
- **Calibración con una sola pasada del motor.** Con umbral ≈ 0, la acción con umbral U es la misma
  acción si |score| ≥ U. Los filtros no dependen del umbral, y
  `test_threshold_applied_later_matches_engine` lo comprueba.

## Seguridad (resumen)

Más detalle en [`../SECURITY.md`](../SECURITY.md).

- **Cuenta.** Solo demo, salvo `ALLOW_LIVE_TRADING=1` en el `.env`.
- **Secretos.** Viven en el `.env`, que está en `.gitignore`.
- **Panel.** Escucha solo en `127.0.0.1`; pide token por sesión y revisa Host/Origin (anti
  DNS-rebinding y anti CSRF); tiene CSP y no se puede incrustar en otra página.
- **Modelos.** Un `.joblib` es un pickle, así que puede ejecutar código al cargarse. Por eso se verifica
  su SHA-256 contra `models/manifest.json` **antes** de `joblib.load`.
- **Noticias.** Son datos de terceros. Se rechazan las respuestas de más de 2 MB, los XML con
  DOCTYPE/ENTITY y los enlaces que no sean http(s), y la página escapa todo antes de mostrarlo.
