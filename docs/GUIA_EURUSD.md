# Guía del bot de EUR/USD — Swing y Scalping

Guía completa de los **dos bots de EUR/USD**: `eurusd_bot/` (**swing**) y
`eurusd_scalping_bot/` (**scalping**). Explica qué hace cada uno, cómo se ejecuta, qué
archivos y herramientas necesita, y el detalle de su proceso interno y sus valores afinados.

> El motor es el mismo código copiado que el del oro, pero **sin el filtro macro** y con una
> corrección de soportes/resistencias propia del EUR/USD (ver §5). Para el oro, mira
> [GUIA_GOLD.md](GUIA_GOLD.md).

---

## 0. De un vistazo

| | EUR/USD **Swing** (`eurusd_bot/`) | EUR/USD **Scalping** (`eurusd_scalping_bot/`) |
|---|---|---|
| Símbolo | `EURUSD` | `EURUSD` |
| Magic (ID de trades) | `20260619` | `20260620` |
| Temporalidades (análisis / tendencia / superior) | H1 / H4 / D1 | M5 / M15 / H1 |
| Ciclo (`LOOP_INTERVAL`) | **60 s** | **10 s** |
| Estilo | Pocas operaciones, las aguanta | Scalp puro: entra y sale muy rápido |
| Etiqueta Telegram | `[EURUSD swing]` | `[EURUSD scalp]` |

---

## 1. Cómo se ejecuta

**Requisitos previos** (los mismos para los dos):

| Herramienta | Para qué |
|---|---|
| Windows 10/11 | La API de Python de MT5 solo corre en Windows |
| Python 3.9+ | Lenguaje del bot |
| **Terminal MetaTrader 5 abierto y con sesión iniciada** | El bot se conecta al MT5 que ya tienes corriendo |
| `pip install -r eurusd_bot/requirements.txt` | Dependencias (las mismas para los 4 bots) |
| Archivo `.env` en la raíz | Credenciales MT5 y (opcional) Telegram — ver [README](../README.md) |

**Lanzar el bot:**

```bash
# EUR/USD swing
python run.py eurusd
cd eurusd_bot && python main.py            # alternativa: directo desde la carpeta

# EUR/USD scalping
python run.py eurusd_scalping
cd eurusd_scalping_bot && python main.py
```

Detener con **Ctrl+C**: termina el ciclo actual y se desconecta limpio. **Las posiciones
abiertas no se cierran** al apagar. Si cambias algo en `config.py`, **reinicia el bot**
(tiene el config viejo en memoria hasta que lo relanzas).

> 💡 Pueden correr **a la vez** (incluso junto a los del oro): cada uno solo gestiona los
> trades con su propio Magic, así que no se pisan.

---

## 2. Archivos y herramientas de cada bot

Cada carpeta (`eurusd_bot/` y `eurusd_scalping_bot/`) es **autónoma** y contiene:

```
main.py            → Loop principal: ejecuta el ciclo cada LOOP_INTERVAL segundos
config.py          → TODOS los parámetros de ESE bot (valores propios)
connection.py      → Conecta / reconecta al terminal MT5
data_handler.py    → Descarga velas (OHLCV), cuenta, order-flow (ticks) y sesgo del dólar (DXY)
indicators.py      → EMA, SMA, RSI, MACD, ATR, ADX, Bollinger, VWAP, soportes/resistencias
patterns.py        → 35+ patrones de velas japonesas
signals.py         → Motor de puntuación (score) + filtros que bloquean entradas
risk_manager.py    → Calcula lote, SL y TP; controla pérdida diaria y margen
trade_manager.py   → Abre/cierra órdenes, break-even, trailing, anti-duplicado
news_filter.py     → Calendario económico (bloquea operar en noticias de alto impacto)
telegram_notifier.py → Avisos al celular (opcional)
logger_config.py   → Escribe el log en consola y en el archivo .log
requirements.txt   → Dependencias Python
```

El log de cada bot queda en `eurusd_bot/eurusd_bot.log` y
`eurusd_scalping_bot/eurusd_scalping_bot.log`.

---

## 3. El proceso, ciclo por ciclo

Cada ciclo (60 s en swing, 10 s en scalp) el bot ejecuta esta tubería. Es **idéntica en los
dos**; solo cambian las temporalidades y los valores:

1. **Conexión** — verifica el terminal MT5 y que `EURUSD` esté en el Market Watch.
2. **Datos** — descarga velas de las 3 temporalidades (descarta la vela en formación para no
   actuar con datos incompletos) y calcula los extras: **order-flow** (presión de ticks) y
   **sesgo del dólar DXY**. *(Nota: el EUR/USD descarga el TF superior pero, a diferencia del
   oro, no lo puntúa — ver §5.)*
3. **Indicadores** — EMA(9/21/50/200), RSI, MACD, ATR, **ADX**, Bollinger, VWAP, soportes/resistencias.
4. **Patrones** — detecta patrones de velas (martillo, envolvente, estrella, etc.).
5. **Señal (score)** — suma ponderada de todo → un número con signo (ver §4). Si supera el
   umbral es BUY/SELL; si no, HOLD. Luego los **filtros** (§5) pueden degradarlo a HOLD.
6. **Riesgo** — valida pérdida diaria, máx. trades y margen; calcula **lote, SL y TP** (§6).
7. **Gestión** — sobre las posiciones ya abiertas: break-even (BE+) y trailing progresivo.
   Después, si hay señal válida, abre un trade nuevo.

---

## 4. Cómo leer la señal del log

Ejemplo real del EUR/USD swing:

```
📊 SELL | Score: -5.23 | EMA:-3.90 RSI:+0.40 MACD:+1.65 BB:+0.07 Pat:+0.48 S/R:+0.45 OF:+0.04 IM:-1.20 | ADX:31 | Tendencia: down | ATR: 0.001
```

**Regla del signo:** cada número **positivo (+)** empuja a **comprar** (BUY), **negativo (−)**
a **vender** (SELL), cerca de 0 = no opina.

**El `Score`** es la suma de todos los factores. Si:
- Score **≥ +`MIN_SIGNAL_SCORE`** → BUY
- Score **≤ −`MIN_SIGNAL_SCORE`** → SELL
- En medio → HOLD

En el ejemplo, −5.23 supera el umbral de venta (5.0) **y** el ADX es 31 (tendencia con
fuerza), así que **sí** abrió la operación.

Cada factor mide algo y tiene un **peso** (ya aplicado en el log):

| En el log | Qué mide | Peso swing | Peso scalp |
|---|---|---|---|
| **EMA** | Tendencia de medias móviles (lo más importante) | 1.3 | 1.3 |
| **RSI** | Sobrecompra / sobreventa (timing) | 1.0 | 1.0 |
| **MACD** | Momentum (acelera o frena) | 1.1 | 1.1 |
| **BB** | Bollinger: precio estirado o comprimido | 0.7 | 0.7 |
| **Pat** | Patrones de velas | 0.8 | 0.8 |
| **S/R** | Cercanía a soportes/resistencias | 0.9 | 0.9 |
| **OF** | Order-flow: presión compra/venta por ticks | 0.5 | **0.8** |
| **IM** | Índice dólar DXY (**inverso**: dólar sube → EUR/USD baja) | 0.8 | 0.3 |

> A diferencia del oro, **no hay columna `Macro`** en el log del EUR/USD: estos bots no
> puntúan el TF superior (ver §5).

Los datos del final **no suman**, son contexto: **ADX** = fuerza de la tendencia,
**Tendencia** = dirección en el TF principal, **ATR** = volatilidad (la regla de medir del
riesgo, §6). En EUR/USD el ATR es pequeño (≈ 0.001 = 10 pips) porque el precio se mueve en
decimales.

---

## 5. Filtros que bloquean entradas

Una señal BUY/SELL se convierte en **HOLD** si choca con un filtro. **Solo frenan aperturas
nuevas; nunca cierran una posición abierta.**

| Filtro | Swing | Scalp | Qué hace |
|---|---|---|---|
| Alineación de tendencia | ✔ | ✔ | Solo opera **a favor** de la tendencia del TF principal. |
| Anti-agotamiento RSI | RSI 32 / 68 | RSI 30 / 70 | No vende con RSI muy bajo ni compra con RSI muy alto (no "vender el suelo / comprar el techo"). |
| **ADX (fuerza de tendencia)** | ADX < **20** | ADX < **18** | Si la tendencia no tiene fuerza (mercado lateral), no abre. |
| Noticias de alto impacto | ±30 min (**USD + EUR**) | ±15 min (**USD + EUR**) | No abre alrededor de noticias de ambas divisas (NFP, CPI, FOMC, BCE…). |

> 🟡 **Dos diferencias del EUR/USD frente al oro:**
> 1. **No tiene filtro macro.** El oro veta/sesga según el gráfico diario; el EUR/USD no
>    puntúa el TF superior (por eso su log no muestra `Macro:` ni `D1:`).
> 2. **Soportes/resistencias parametrizados** (`SR_CLUSTER_ATR_MULT`, `PSYCH_LEVEL_STEP`):
>    como el EUR/USD se mueve en decimales (no en dólares como el oro), los niveles clave y
>    los "números redondos" psicológicos se calculan a su escala.

Además, el filtro de **noticias incluye EUR**, no solo USD: al EUR/USD lo mueven las dos
economías, así que también para en eventos del BCE/zona euro.

---

## 6. Riesgo: lote, SL y TP

El score decide *si* y *hacia dónde*; el riesgo se define con el **ATR + el % de riesgo**.
El lote se calcula **al revés**: partiendo de cuánto quieres perder.

```
lote = (1% del balance) / (distancia del SL en dinero)
distancia del SL = SL_ATR_MULT × ATR
distancia del TP = TP_ATR_MULT × ATR
```

Así, **a más volatilidad (ATR alto), el SL es más ancho y el bot compra menos lote** → la
pérdida máxima sigue siendo ~1%.

| Parámetro de riesgo | EUR swing | EUR scalp |
|---|---|---|
| `RISK_PER_TRADE` | 1% por trade | 1% por trade |
| `MAX_OPEN_TRADES` | 3 (riesgo total ≈ 3%) | 3 (≈ 3%) |
| `MAX_DAILY_LOSS_PCT` | 5% → detiene el día | 5% → detiene el día |
| `SL_ATR_MULT` / `TP_ATR_MULT` | 1.2 / 2.7 | 1.0 / 1.5 |
| `MIN_RR` (R:R mínimo) | 2.0 | **1.2** |
| `MAX_SPREAD_POINTS` | 50 (5 pips) | **18 (1.8 pips)** |

> ⚠️ El scalp de EUR/USD es el más exigente con el **spread** (`MAX_SPREAD_POINTS = 18`):
> con TP de solo ~3-8 pips, un spread alto se come la ganancia, así que no opera si está caro.

**Protección de la ganancia** (en cada ciclo, sobre lo abierto):

| Mecanismo | EUR swing | EUR scalp | Qué hace |
|---|---|---|---|
| Break-even "BE+" | dispara al **50%** del camino al TP | al **55%** | Mueve el SL a poco por encima de la entrada (cubre spread + margen) → si revierte, sale en positivo. |
| Trailing ATR | `1.5 × ATR` | `0.5 × ATR` (pegadísimo) | Sigue al precio; en scalp protege cada pip. |
| Lock progresivo | START 0.9×ATR, asegura 35→90% | START 0.5×ATR, asegura 40→90% | A medida que el trade gana, asegura una fracción creciente del profit (≈1:1). |
| Anti-duplicado | `1.0 × ATR` | `0.75 × ATR` | No apila trades en la misma dirección demasiado cerca de uno existente. |

---

## 7. Tabla resumen de valores afinados

| Parámetro | EUR swing | EUR scalp |
|---|---|---|
| `PRIMARY_TF` / `TREND_TF` / `HIGHER_TF` | H1 / H4 / D1 | M5 / M15 / H1 |
| `LOOP_INTERVAL` | 60 s | 10 s |
| `MIN_SIGNAL_SCORE` | 5.0 | 4.5 |
| `SL_ATR_MULT` / `TP_ATR_MULT` | 1.2 / 2.7 | 1.0 / 1.5 |
| `MIN_RR` | 2.0 | 1.2 |
| `RISK_PER_TRADE` / `MAX_OPEN_TRADES` | 1% / 3 | 1% / 3 |
| `BE_TRIGGER_PCT` | 0.50 | 0.55 |
| `TRAILING_ATR_MULT` | 1.5 | 0.5 |
| Lock START / MIN→MAX / FULL | 0.9 / .35→.90 / 2.4 | 0.5 / .40→.90 / 1.3 |
| `ANTI_DUP_ATR_MULT` | 1.0 | 0.75 |
| `ADX_MIN_TREND` | 20 | 18 |
| `RSI_NO_SELL_BELOW` / `RSI_NO_BUY_ABOVE` | 32 / 68 | 30 / 70 |
| `MAX_SPREAD_POINTS` | 50 | 18 |
| Order-flow ventana / peso | 300 s / 0.5 | 120 s / 0.8 |
| DXY TF / peso | H4 / 0.8 | H1 / 0.3 |
| Macro | — (sin filtro macro) | — (sin filtro macro) |
| Noticias ±min / divisas | 30 / USD, EUR | 15 / USD, EUR |

> Los valores viven en cada `config.py` y mandan sobre esta tabla si algún día se afinan.
> Cualquier cambio necesita **reiniciar el bot**.

---

## 8. Ejemplo numérico (EUR/USD swing)

BUY de EUR/USD con `ATR = 0.0010` (10 pips) y balance `10.000 USD`:

| Cálculo | Resultado |
|---|---|
| Dinero a arriesgar (1%) | 100 USD |
| Distancia del SL (`1.2 × 0.0010`) | 0.0012 = 12 pips |
| Distancia del TP (`2.7 × 0.0010`) | 0.0027 = 27 pips |
| Ratio R:R | `27 / 12 ≈ 2.25 : 1` (cumple `MIN_RR = 2.0`) ✅ |
| Lote | ajustado para que, si toca el SL (12 pips), la pérdida sea ≈ 100 USD |

Si el ATR fuera el doble, el SL sería el doble de ancho y el bot compraría **la mitad de
lote**: la pérdida máxima seguiría siendo ~100 USD (1%).
