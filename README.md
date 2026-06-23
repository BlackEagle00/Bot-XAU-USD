# Bots de Trading MetaTrader 5 — Oro (XAU/USD) y EUR/USD

Conjunto de **4 bots de trading automático** para MetaTrader 5 que comparten **un único
motor** (`bot_engine/`) y se diferencian solo por su `config.py`. Cada uno está afinado para
su instrumento y estilo. Combinan análisis técnico multitemporal, 35+ patrones de velas,
gestión de riesgo dinámica y varios **filtros direccionales** (fuerza de tendencia, presión
de order-flow, sesgo del dólar y un filtro de noticias de alto impacto).

> ⚠️ Solo Windows: la API de Python de MT5 necesita el **terminal MetaTrader 5 abierto y
> con sesión iniciada** en la misma máquina.

---

## Los 4 bots

| Carpeta | Símbolo | Estilo | Temporalidades | Loop | Magic |
|---|---|---|---|---|---|
| `xauusd_bot/`          | GOLD (Oro) | **Swing**     | H1 / H4 / D1  | 60 s | 20260618 |
| `xauusd_scalping_bot/` | GOLD (Oro) | **Scalping**  | M5 / M15 / H1 | 15 s | 20260621 |
| `eurusd_bot/`          | EUR/USD    | **Swing**     | H1 / H4 / D1  | 60 s | 20260619 |
| `eurusd_scalping_bot/` | EUR/USD    | **Scalping**  | M5 / M15 / H1 | 10 s | 20260620 |

Cada carpeta de bot contiene solo su `config.py` (parámetros propios) y un `main.py` lanzador
delgado; toda la lógica vive en `bot_engine/`. Cada bot tiene su `MAGIC_NUMBER` (para no
mezclar trades) y su `.log`. **Pueden correr a la vez** en la misma cuenta sin pisarse: cada
uno solo gestiona las posiciones que él mismo abrió (filtra por su Magic).

> El motor es **compartido**: una mejora se hace **una sola vez** en `bot_engine/` y aplica a
> los 4 bots. Las diferencias entre bots (temporalidades, contexto macro, escala de S/R,
> umbrales…) se controlan por `config.py`, no duplicando código.

### 📖 Guías detalladas por instrumento

Para el detalle de cada bot (cómo se ejecuta, archivos, proceso ciclo por ciclo, filtros,
riesgo y tabla de valores afinados de **swing** y **scalping**):

| Guía | Cubre |
|---|---|
| [**GUIA_GOLD.md**](docs/GUIA_GOLD.md) | Oro (XAU/USD): `xauusd_bot/` swing + `xauusd_scalping_bot/` scalp |
| [**GUIA_EURUSD.md**](docs/GUIA_EURUSD.md) | EUR/USD: `eurusd_bot/` swing + `eurusd_scalping_bot/` scalp |

Este README es el panorama general; las guías entran en el detalle de cada instrumento.

---

## Requisitos

| Requisito | Mínimo |
|---|---|
| Windows | 10 / 11 |
| Python | 3.9+ |
| MetaTrader 5 (terminal) | Cualquier broker con XAUUSD y EURUSD |
| Internet | Recomendado (filtro de noticias y notificaciones Telegram) |

---

## Instalación

```bash
pip install -r requirements.txt   # las mismas dependencias para los 4 bots
```

### Credenciales (archivo `.env`)

Las credenciales **no van en `config.py`**: se leen de un archivo `.env` en la raíz del
proyecto (vía `python-dotenv`). Copia la plantilla y rellénala (`.env` está en `.gitignore`):

```bash
cp .env.example .env
```

Contenido de `.env`:

```env
MT5_LOGIN=0            # 0 = usa la cuenta ya abierta en el terminal MT5
MT5_PASSWORD=
MT5_SERVER=

# Notificaciones Telegram (opcional; déjalo vacío para desactivarlas)
TELEGRAM_BOT_TOKEN=    # te lo da @BotFather al crear el bot
TELEGRAM_CHAT_ID=      # tu id numérico (háblale a @userinfobot)
```

Si dejas `MT5_LOGIN=0`, el bot usa la cuenta que ya tengas con sesión iniciada en MT5
(lo más cómodo). Cuenta de referencia actual: **demo de XM** (`XMGlobal-MT5`), oro como
`SYMBOL="GOLD"`.

---

## Ejecución

```bash
python run.py                 # menú interactivo para elegir bot
python run.py oro             # lanza uno directo: oro | oro_scalping | eurusd | eurusd_scalping
# — o desde la carpeta del bot —
cd xauusd_bot && python main.py
```

Para detener: **Ctrl+C** — termina el ciclo en curso y se desconecta limpio. Las
posiciones abiertas **se mantienen** en MT5 (no se cierran al apagar el bot).

> 🔁 **Los cambios necesitan reinicio.** Un bot en marcha tiene el código/config viejos en
> memoria: editar `config.py` no hace nada hasta que haces Ctrl+C y lo vuelves a lanzar.

---

## Cómo funciona — ciclo por ciclo

Cada `LOOP_INTERVAL` segundos el bot ejecuta esta tubería:

1. **Conexión** — verifica/reconecta el terminal MT5 y valida el símbolo.
2. **Datos** — descarga OHLCV de las 3 temporalidades (primaria, tendencia, superior) y
   descarta la vela en formación. Además calcula los factores extra: **order-flow** (ticks
   recientes) y **sesgo del dólar (DXY)**.
3. **Indicadores** — EMA(9/21/50/200), SMA(20/50), RSI, MACD, ATR, **ADX**, Bandas de
   Bollinger, VWAP y soportes/resistencias.
4. **Patrones** — 35+ patrones de velas japonesas (Doji, Hammer, Engulfing, Morning Star…).
5. **Señal** — suma ponderada de todo → score (rango ≈ ±12). Si supera `MIN_SIGNAL_SCORE`
   es BUY/SELL; si no, HOLD. Luego varios **filtros** pueden degradar a HOLD (ver abajo).
6. **Riesgo** — valida pérdida diaria, máx. trades simultáneos y margen libre; calcula lote,
   SL y TP.
7. **Gestión** — en **cada** ciclo, sobre las posiciones abiertas del bot: break-even (BE+)
   y trailing stop progresivo. Después intenta abrir un trade nuevo si hay señal válida.

---

## Sistema de scoring

El score combina cada componente con su peso (`SCORE_WEIGHTS` en `config.py`). Pesos del
**oro swing** como referencia (varían por bot):

| Componente | Peso | Qué mide |
|---|---|---|
| EMAs (posición + cruces) | 1.3 | Dirección y momentum |
| RSI | 1.0 | Sobrecompra/sobreventa y timing |
| MACD | 1.1 | Cruce de momentum |
| Patrones de velas | 0.8 | Reversión/continuación |
| Bollinger Bands | 0.7 | Rango y squeeze |
| Soporte/Resistencia | 0.9 | Niveles clave |
| VWAP | 0.1 | Precio justo intradía |
| Volumen (de velas) | 0.4 | Confirmación del movimiento |
| Confirmación TF tendencia | 1.0 | EMA del H4/M15 |
| **Macro** (solo oro) | 0.8 / 0.5 | Sesgo del D1 (swing) / H1 (scalp) |
| **🟢 Order-flow** (nuevo) | 0.5–0.8 | Presión compra/venta por ticks |
| **🌐 Inter-mercado DXY** (nuevo) | 0.3–0.8 | Sesgo del dólar (inverso) |

`score ≥ +MIN_SIGNAL_SCORE` → **BUY** · `score ≤ −MIN_SIGNAL_SCORE` → **SELL** · resto → **HOLD**.

---

## Filtros que bloquean entradas (gates)

Una señal BUY/SELL se convierte en HOLD si choca con alguno de estos filtros. Solo frenan
**aperturas nuevas**; nunca cierran una posición abierta.

| Filtro | Flag | Qué hace |
|---|---|---|
| **Alineación de tendencia** | `REQUIRE_TREND_ALIGNMENT` | Solo opera a favor de la tendencia de la TF primaria (no contra-tendencia). |
| **Anti-agotamiento RSI** | (siempre activo) | No vende con RSI ≤ `RSI_NO_SELL_BELOW` ni compra con RSI ≥ `RSI_NO_BUY_ABOVE` (no "vender el suelo / comprar el techo"). |
| **ADX (fuerza de tendencia)** | `USE_ADX_FILTER` | Si ADX < `ADX_MIN_TREND` el mercado está lateral (chop) → no abre. |
| **Macro (solo oro)** | `REQUIRE_MACRO_ALIGNMENT` | Oro swing: veta operar contra un D1 en tendencia fuerte. Oro scalp: solo sesgo, sin veto. |
| **Noticias de alto impacto** | `USE_NEWS_FILTER` | No abre en la ventana ± minutos alrededor de NFP/CPI/FOMC/BCE, etc. |

---

## Gestión de riesgo y protección de ganancia

| Mecanismo | Flag | Comportamiento |
|---|---|---|
| **Break-even "BE+"** | `USE_BREAKEVEN` | Cuando el precio recorre `BE_TRIGGER_PCT` del camino al TP, mueve el SL a `entrada ∓ (spread + BE_PLUS_POINTS)` → sale en positivo, no exactamente en cero. |
| **Trailing + lock progresivo** | `USE_TRAILING_STOP` / `USE_PROGRESSIVE_TRAIL` | Cada ciclo toma el SL **más protector** entre el trailing ATR clásico y el *lock progresivo*: a medida que el trade gana, asegura una fracción creciente del profit (de `TRAIL_LOCK_PCT_MIN` a `TRAIL_LOCK_PCT_MAX` ≈ 1:1). Un retroceso sale en ganancia, no en pérdida. |
| **Anti-duplicado** | `USE_ANTI_DUPLICATE` | No apila trades en la misma dirección a menos de `ANTI_DUP_ATR_MULT × ATR` de uno existente. |
| **Lote dinámico** | — | Se recalcula en cada trade según el balance y la distancia del SL (`RISK_PER_TRADE`). |
| **Límite de pérdida diaria** | — | Detiene nuevas operaciones si la pérdida del día ≥ `MAX_DAILY_LOSS_PCT`. |
| **Margen mínimo** | — | No opera si el margen libre cae por debajo del umbral de seguridad. |

> El riesgo *correlacionado* total ≈ `MAX_OPEN_TRADES × RISK_PER_TRADE`, porque con
> `REQUIRE_TREND_ALIGNMENT` todas las posiciones van en la misma dirección. El oro swing,
> con 5 trades × 1%, está en ~5%.

---

## Factores direccionales extra (nuevos)

Cuatro factores que ayudan a decidir si el precio sube o baja. Todos van detrás de un
interruptor y **degradan con elegancia**: si fallan, el bot sigue operando sin ellos.

### 🟢 Order-flow (presión compra/venta) — `USE_ORDERFLOW`
Aproxima el "volumen de compra vs venta" con los ticks recientes (en CFDs **no hay volumen
real**): `delta = (compras − ventas)/(compras + ventas) ∈ [−1, 1]`. Suma como *nudge* al
score. Ventana: `ORDERFLOW_LOOKBACK_SECS` (300 s swing / 120 s scalp).

### 🌐 Inter-mercado: índice dólar (DXY) — `USE_INTERMARKET`
El oro y el EUR/USD son **inversos al dólar**: si el DXY baja, hay viento de cola alcista.
El bot mide la tendencia del DXY y sesga el score (`INTERMARKET_INVERSE=True`).
> ⚠️ **Símbolo del índice dólar.** En la cuenta XM de referencia es `USDX-SEP26` (contrato de
> **futuros trimestral**, "US Dollar Index"), ya configurado en `INTERMARKET_SYMBOL` de los 4 bots.
> Al vencer (~2026-09-11) hay que cambiar el sufijo al siguiente contrato (p. ej. `USDX-DEC26`).
> Si el símbolo no existe en tu broker, el factor **se desactiva solo** (sin error).

### ⚡ ADX (fuerza de tendencia) — `USE_ADX_FILTER`
Mide si la tendencia tiene fuerza (no su dirección). Si ADX < `ADX_MIN_TREND` el mercado
está lateral y los cruces son ruido → no abre. Es el filtro más barato y efectivo contra
el "chop".

### 📰 Filtro de noticias — `USE_NEWS_FILTER`
Usa el calendario económico semanal de **ForexFactory** (JSON gratuito) y bloquea abrir
trades en la ventana `±NEWS_BLACKOUT_*_MIN` alrededor de eventos de alto impacto de las
divisas en `NEWS_CURRENCIES`. Módulo: `news_filter.py`.
> Si no hay internet, por defecto **NO bloquea** (`NEWS_FAIL_OPEN=True`) para no congelar el
> bot. Pon `False` si prefieres no operar a ciegas cuando el calendario no carga.

---

## Notificaciones por Telegram (opcional) — `USE_TELEGRAM`

Te avisa al **celular** de la actividad del bot sin tener que mirar la consola ni
conectarte por escritorio remoto. Módulo: `telegram_notifier.py` (solo stdlib, igual que
el filtro de noticias: envía en un hilo aparte para no frenar el loop y **degrada con
elegancia** si Telegram falla).

Avisa cuando el bot:
- 🟢 **arranca** / 🔴 **se detiene** (con símbolo, temporalidades y balance),
- 🟢 **abre** una operación (ticket, lote, entry, SL, TP),
- ✅/🔴 **cierra** una operación por SL/TP o manual, con el **P&L realizado**,
- ⚠️/✅ **pierde / recupera** la conexión con MT5 (avisa una sola vez, sin spam).

Cada bot manda un **prefijo** para distinguirlo en el mismo chat: `[GOLD swing]`,
`[GOLD scalp]`, `[EURUSD swing]`, `[EURUSD scalp]`.

**Configuración (una sola vez, sirve para los 4 bots):**
1. En Telegram habla con **@BotFather** → `/newbot` → copia el **token**.
2. Habla con **@userinfobot** → copia tu **chat_id** (número).
3. Escríbele "hola" a **tu** bot (si no, Telegram no le deja enviarte mensajes).
4. Pon ambos valores en el `.env` (`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`).
5. Reinicia los bots.

> Si dejas el token o el chat_id vacíos, las notificaciones **se desactivan solas** (sin
> error). Para apagarlas a propósito, pon `USE_TELEGRAM = False`. No añade dependencias
> nuevas (usa `urllib` de la stdlib). La detección de cierres compara los tickets abiertos
> entre ciclos: un trade que abre y cierra dentro del mismo ciclo puede no notificar el
> cierre (el de apertura siempre sale).

---

## Interruptores (on/off) — resumen

Todos en `config.py` de cada bot. Valor por defecto entre paréntesis:

| Flag | Por defecto | Efecto |
|---|---|---|
| `USE_BREAKEVEN` | `True` | Activa el break-even "BE+". |
| `USE_TRAILING_STOP` | `True` | Activa el trailing stop. |
| `USE_PROGRESSIVE_TRAIL` | `True` | El trailing asegura fracción creciente del profit (≈1:1). |
| `USE_ANTI_DUPLICATE` | `True` | Exige separación mínima entre entradas de la misma dirección. |
| `USE_ADX_FILTER` | `True` | Bloquea entradas en mercado lateral (ADX bajo). |
| `USE_ORDERFLOW` | `True` | Suma la presión compra/venta por ticks al score. |
| `USE_INTERMARKET` | `True` | Suma el sesgo del dólar (DXY) al score. |
| `USE_NEWS_FILTER` | `True` | Bloquea operar alrededor de noticias de alto impacto. |
| `USE_TELEGRAM` | `True` | Envía notificaciones al celular (se desactiva sola sin token/chat_id). |
| `REQUIRE_TREND_ALIGNMENT` | `True` | Solo opera a favor de la tendencia. |
| `REQUIRE_MACRO_ALIGNMENT` | `True` oro swing / `False` oro scalp | Veta operar contra la tendencia macro (solo oro). |
| `INTERMARKET_INVERSE` | `True` | El activo se mueve inverso al dólar (oro/EUR). |
| `NEWS_FAIL_OPEN` | `True` | Si el calendario no carga, permite operar (no congela el bot). |

---

## Afinado por bot (valores actuales)

Mantén estos valores **intencionalmente distintos** por instrumento/estilo:

| Parámetro | Oro swing | Oro scalp | EUR swing | EUR scalp |
|---|---|---|---|---|
| `MIN_SIGNAL_SCORE` | 5.0 | 5.5 | 5.0 | 4.5 |
| `SL_ATR_MULT` / `TP_ATR_MULT` | 2.0 / 4.5 | 1.5 / 3.0 | 1.2 / 2.7 | 1.0 / 1.5 |
| `MIN_RR` | 2.0 | 1.8 | 2.0 | 1.2 |
| `RISK_PER_TRADE` / `MAX_OPEN_TRADES` | 1% / 5 | 1% / 3 | 1% / 3 | 1% / 3 |
| `BE_TRIGGER_PCT` | 0.40 | 0.55 | 0.50 | 0.55 |
| `TRAILING_ATR_MULT` | 2.5 | 1.0 | 1.5 | 0.5 |
| Lock progresivo START / MIN→MAX / FULL | 1.5 / .35→.90 / 4.0 | 1.0 / .40→.90 / 2.7 | 0.9 / .35→.90 / 2.4 | 0.5 / .40→.90 / 1.3 |
| `ADX_MIN_TREND` | 20 | 18 | 20 | 18 |
| Order-flow ventana / peso | 300 s / 0.5 | 120 s / 0.8 | 300 s / 0.5 | 120 s / 0.8 |
| DXY TF / peso | H4 / 0.8 | H1 / 0.4 | H4 / 0.8 | H1 / 0.3 |
| Noticias ±min / divisas | 30 / USD | 15 / USD | 30 / USD,EUR | 15 / USD,EUR |
| `RSI_NO_SELL_BELOW` / `RSI_NO_BUY_ABOVE` | 32 / 68 | 30 / 70 | 32 / 68 | 30 / 70 |
| `MAX_SPREAD_POINTS` | 80 | 70 | 50 | 18 |
| Filtro macro | D1 (veto) | H1 (sesgo) | — | — |

---

## Qué verás en consola

```
📊 BUY  | Score:  +6.10 | EMA:+2.10 RSI:+0.63 MACD:+0.81 BB:+0.40 Pat:+0.80 S/R:+0.45
        Macro:+1.20 OF:+0.40 IM:+1.20 | ADX:31 | Tendencia: up | D1: up | ATR: 8.42
🎯 Señal BUY | Score: +6.10 | Lote: 0.20 | Entry: 2045.23 | SL: 2028.39 | TP: 2083.13
✅ BUY abierto | Ticket: #38291042 | ...
☑  BE+ BUY #38291042 | SL: 2028.39 → 2045.48 (recorrido ...)
↑  Trailing BUY #38291042 | SL 2045.48 → 2058.10 | lock progresivo asegura 62% del profit
📰 Trade SELL bloqueado por noticia de alto impacto: USD High: Core CPI @ 12:30 UTC
── STATUS 14:40:00 ── Ciclo #20 | Trades sesión: 2 | P&L hoy: +34.50 USD | ...
```

> Nota cosmética: la consola de Windows (cp1252) puede mostrar `UnicodeEncodeError` por los
> emojis. El archivo `.log` es UTF-8 y queda perfecto. No afecta al funcionamiento.

> 📖 **¿Empezando?** Cada instrumento tiene su guía detallada (cómo leer el log, los filtros,
> el riesgo y los valores afinados de sus variantes swing y scalping):
> [**Guía del ORO**](docs/GUIA_GOLD.md) · [**Guía del EUR/USD**](docs/GUIA_EURUSD.md).

---

## Estructura del proyecto

```
Bot-XAU-USD/
├── run.py              → Lanzador común de los 4 bots
├── requirements.txt    → Dependencias del proyecto
├── .env.example        → Plantilla de credenciales (copiar a .env)
├── README.md           → Este panorama general
├── CLAUDE.md           → Guía para agentes/IA que trabajen el repo
├── bot_engine/         → ⚙️ EL MOTOR COMPARTIDO (toda la lógica; ver detalle abajo)
├── xauusd_bot/         → config.py + main.py (Oro swing)
├── xauusd_scalping_bot/→ config.py + main.py (Oro scalping)
├── eurusd_bot/         → config.py + main.py (EUR/USD swing)
├── eurusd_scalping_bot/→ config.py + main.py (EUR/USD scalping)
├── docs/               → Guías por instrumento, brokers, migración (+ historico/)
└── backtesting/        → Toolkit de backtesting independiente (no usado por los bots)
```

Cada carpeta de bot tiene solo **dos** archivos:

```
<bot>/
├── config.py   → TODOS los parámetros de ese bot (valores propios)
└── main.py     → Lanzador delgado: pone su config.py en sys.path y llama a bot_engine.core.run()
```

## El motor compartido (`bot_engine/`)

```
bot_engine/
├── core.py           → Loop principal y orquestación (run(), _run_cycle(), _try_open_trade())
├── connection.py     → Conexión / reconexión a MT5
├── data_handler.py   → OHLCV, cuenta, order-flow (ticks) y sesgo DXY
├── indicators.py     → EMA, SMA, RSI, MACD, ATR, ADX, BB, VWAP, S/R (parametrizado por config)
├── patterns.py       → 35+ patrones de velas
├── signals.py        → Motor de scoring + filtros (gates); macro gated por USE_MACRO_CONTEXT
├── risk_manager.py   → Lote, SL/TP, pérdida diaria, margen
├── trade_manager.py  → Abrir/cerrar, break-even, trailing progresivo, anti-dup
├── news_filter.py    → Calendario económico (blackout de noticias)
├── telegram_notifier.py → Notificaciones a Telegram (opcional)
└── logger_config.py  → Logs a consola y a archivo .log
```

Los módulos del motor se importan entre sí con imports relativos (`from .signals import …`) y
leen los parámetros con `from config import …`, que resuelve al `config.py` del bot que lo
lanzó (su carpeta va primero en `sys.path`). Como cada bot corre en su **propio proceso**, no
se mezclan configs. `run.py` (raíz) es el lanzador común de los 4 bots.

---

## Compatibilidad con brokers

El bot detecta automáticamente el modo de ejecución (`FOK`/`IOC`/`RETURN`), la distancia
mínima de SL/TP (`trade_stops_level`) y el paso/mín/máx de lote. Probado contra ICMarkets,
Pepperstone, XM y FP Markets. El nombre del oro varía por broker (`XAUUSD`, `GOLD`,
`XAUUSDm`): ajústalo en `SYMBOL` dentro de `config.py`.

---

## Advertencia de riesgo

> **El trading automatizado conlleva riesgo de pérdida de capital.** Este bot es una
> herramienta de ayuda, no una garantía de beneficios. Pruébalo siempre en **cuenta demo**
> antes de usar fondos reales. Nunca arriesgues dinero que no puedas permitirte perder.
> El rendimiento pasado no garantiza resultados futuros.
