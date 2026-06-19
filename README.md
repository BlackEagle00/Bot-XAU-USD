# Bots de Trading MetaTrader 5 — Oro (XAU/USD) y EUR/USD

Conjunto de **4 bots de trading automático** para MetaTrader 5, cada uno una copia
independiente del mismo motor, afinada para su instrumento y estilo. Combinan análisis
técnico multitemporal, 35+ patrones de velas, gestión de riesgo dinámica y varios
**filtros direccionales** (fuerza de tendencia, presión de order-flow, sesgo del dólar
y un filtro de noticias de alto impacto).

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

Cada bot tiene su propio `config.py`, su `MAGIC_NUMBER` (para no mezclar trades) y su
`.log`. **Pueden correr a la vez** en la misma cuenta sin pisarse: cada uno solo gestiona
las posiciones que él mismo abrió (filtra por su Magic).

> El motor está **copiado**, no compartido: una mejora en un bot hay que replicarla a mano
> en los otros. Esto es intencional para poder afinar cada bot por separado.

---

## Requisitos

| Requisito | Mínimo |
|---|---|
| Windows | 10 / 11 |
| Python | 3.9+ |
| MetaTrader 5 (terminal) | Cualquier broker con XAUUSD y EURUSD |
| Internet | Recomendado (para el filtro de noticias) |

---

## Instalación

```bash
pip install -r xauusd_bot/requirements.txt   # las mismas dependencias para los 4 bots
```

### Credenciales (archivo `.env`)

Las credenciales **no van en `config.py`**: se leen de un archivo `.env` en la raíz del
proyecto (vía `python-dotenv`). Crea `.env` con:

```env
MT5_LOGIN=0            # 0 = usa la cuenta ya abierta en el terminal MT5
MT5_PASSWORD=
MT5_SERVER=
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
> ⚠️ **Verifica el símbolo en tu broker.** Por defecto `INTERMARKET_SYMBOL="USDX"`. Si tu
> broker no lo tiene (o lo llama distinto), busca en *Market Watch → Símbolos* y ajusta el
> nombre. Si no existe, el factor **se desactiva solo** (sin error).

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

---

## Archivos de cada bot

```
<bot>/
├── main.py           → Loop principal y orquestación
├── config.py         → TODOS los parámetros (uno por bot, valores distintos)
├── connection.py     → Conexión / reconexión a MT5
├── data_handler.py   → OHLCV, cuenta, order-flow (ticks) y sesgo DXY
├── indicators.py     → EMA, SMA, RSI, MACD, ATR, ADX, BB, VWAP, S/R
├── patterns.py       → 35+ patrones de velas
├── signals.py        → Motor de scoring + filtros (gates)
├── risk_manager.py   → Lote, SL/TP, pérdida diaria, margen
├── trade_manager.py  → Abrir/cerrar, break-even, trailing progresivo, anti-dup
├── news_filter.py    → Calendario económico (blackout de noticias)
├── logger_config.py  → Logs a consola y a archivo .log
└── requirements.txt  → Dependencias Python
```

`run.py` (raíz) es el lanzador común de los 4 bots.

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
