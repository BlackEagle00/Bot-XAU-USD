# Guía del bot de ORO (XAU/USD) — Swing y Scalping

Guía completa de los **dos bots del oro**: `xauusd_bot/` (**swing**) y `xauusd_scalping_bot/`
(**scalping**). Explica qué hace cada uno, cómo se ejecuta, qué archivos y herramientas
necesita, y el detalle de su proceso interno y sus valores afinados.

> El motor de ambos es el mismo código copiado; cambian las **temporalidades**, los **valores**
> y un detalle clave del oro: el **filtro macro** (ver más abajo). Para EUR/USD, mira
> [GUIA_EURUSD.md](GUIA_EURUSD.md).

---

## 0. De un vistazo

| | Oro **Swing** (`xauusd_bot/`) | Oro **Scalping** (`xauusd_scalping_bot/`) |
|---|---|---|
| Símbolo | `GOLD` | `GOLD` |
| Magic (ID de trades) | `20260618` | `20260621` |
| Temporalidades (análisis / tendencia / macro) | H1 / H4 / **D1** | M5 / M15 / **H1** |
| Ciclo (`LOOP_INTERVAL`) | **60 s** | **15 s** |
| Estilo | Pocas operaciones, las aguanta | Muchas operaciones, entra y sale rápido |
| Etiqueta Telegram | `[GOLD swing]` | `[GOLD scalp]` |

---

## 1. Cómo se ejecuta

**Requisitos previos** (los mismos para los dos):

| Herramienta | Para qué |
|---|---|
| Windows 10/11 | La API de Python de MT5 solo corre en Windows |
| Python 3.9+ | Lenguaje del bot |
| **Terminal MetaTrader 5 abierto y con sesión iniciada** | El bot se conecta al MT5 que ya tienes corriendo |
| `pip install -r xauusd_bot/requirements.txt` | Dependencias (las mismas para los 4 bots) |
| Archivo `.env` en la raíz | Credenciales MT5 y (opcional) Telegram — ver [README](../README.md) |

**Lanzar el bot:**

```bash
# Oro swing
python run.py oro
cd xauusd_bot && python main.py          # alternativa: directo desde la carpeta

# Oro scalping
python run.py oro_scalping
cd xauusd_scalping_bot && python main.py
```

Detener con **Ctrl+C**: termina el ciclo actual y se desconecta limpio. **Las posiciones
abiertas no se cierran** al apagar. Si cambias algo en `config.py`, **reinicia el bot**
(tiene el config viejo en memoria hasta que lo relanzas).

> 💡 Pueden correr **a la vez** (incluso junto a los de EUR/USD): cada uno solo gestiona los
> trades con su propio Magic, así que no se pisan.

---

## 2. Archivos y herramientas de cada bot

Cada carpeta (`xauusd_bot/` y `xauusd_scalping_bot/`) es **autónoma** y contiene:

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

El log de cada bot queda en `xauusd_bot/xauusd_bot.log` y
`xauusd_scalping_bot/xauusd_scalping_bot.log`.

---

## 3. El proceso, ciclo por ciclo

Cada ciclo (60 s en swing, 15 s en scalp) el bot ejecuta esta tubería. Es **idéntica en los
dos**; solo cambian las temporalidades y los valores:

1. **Conexión** — verifica el terminal MT5 y que `GOLD` esté en el Market Watch.
2. **Datos** — descarga velas de las 3 temporalidades (descarta la vela en formación para no
   actuar con datos incompletos) y calcula los extras: **order-flow** (presión de ticks) y
   **sesgo del dólar DXY**.
3. **Indicadores** — EMA(9/21/50/200), RSI, MACD, ATR, **ADX**, Bollinger, VWAP, soportes/resistencias.
4. **Patrones** — detecta patrones de velas (martillo, envolvente, estrella, etc.).
5. **Señal (score)** — suma ponderada de todo → un número con signo (ver §4). Si supera el
   umbral es BUY/SELL; si no, HOLD. Luego los **filtros** (§5) pueden degradarlo a HOLD.
6. **Riesgo** — valida pérdida diaria, máx. trades y margen; calcula **lote, SL y TP** (§6).
7. **Gestión** — sobre las posiciones ya abiertas: break-even (BE+) y trailing progresivo.
   Después, si hay señal válida, abre un trade nuevo.

---

## 4. Cómo leer la señal del log

Ejemplo real del oro swing:

```
📊 HOLD | Score: -9.5 | EMA:-3.90 RSI:+0.40 MACD:-1.43 BB:+0.84 Pat:+0.00 S/R:+0.00 Macro:-1.20 OF:-0.02 IM:-1.20 | ADX:17 | Tendencia: down | D1: down | ATR: 18.122
```

**Regla del signo:** cada número **positivo (+)** empuja a **comprar** (BUY), **negativo (−)**
a **vender** (SELL), cerca de 0 = no opina.

**El `Score`** es la suma de todos los factores. Si:
- Score **≥ +`MIN_SIGNAL_SCORE`** → BUY
- Score **≤ −`MIN_SIGNAL_SCORE`** → SELL
- En medio → HOLD

Cada factor mide algo y tiene un **peso** (ya aplicado en el log):

| En el log | Qué mide | Peso swing | Peso scalp |
|---|---|---|---|
| **EMA** | Tendencia de medias móviles (lo más importante) | 1.3 | 1.3 |
| **RSI** | Sobrecompra / sobreventa (timing) | 1.0 | 1.0 |
| **MACD** | Momentum (acelera o frena) | 1.1 | 1.1 |
| **BB** | Bollinger: precio estirado o comprimido | 0.7 | 0.7 |
| **Pat** | Patrones de velas | 0.8 | 0.8 |
| **S/R** | Cercanía a soportes/resistencias | 0.9 | 0.9 |
| **Macro** | Tendencia del TF superior (**D1** swing / **H1** scalp) | **0.8** | **0.5** |
| **OF** | Order-flow: presión compra/venta por ticks | 0.5 | **0.8** |
| **IM** | Índice dólar DXY (**inverso**: dólar sube → oro baja) | 0.8 | 0.4 |

Los datos del final **no suman**, son contexto: **ADX** = fuerza de la tendencia,
**Tendencia** = dirección en el TF principal, **D1** = dirección del diario, **ATR** =
volatilidad (la regla de medir del riesgo, §6).

---

## 5. Filtros que bloquean entradas

Una señal BUY/SELL se convierte en **HOLD** si choca con un filtro. **Solo frenan aperturas
nuevas; nunca cierran una posición abierta.**

| Filtro | Swing | Scalp | Qué hace |
|---|---|---|---|
| Alineación de tendencia | ✔ | ✔ | Solo opera **a favor** de la tendencia del TF principal. |
| Anti-agotamiento RSI | RSI 32 / 68 | RSI 30 / 70 | No vende con RSI muy bajo ni compra con RSI muy alto (no "vender el suelo / comprar el techo"). |
| **ADX (fuerza de tendencia)** | ADX < **20** | ADX < **18** | Si la tendencia no tiene fuerza (mercado lateral), no abre. *Este fue el que bloqueó el oro swing toda una sesión con ADX 15-17.* |
| **Macro (exclusivo del oro)** | **D1 con VETO** | H1 solo sesgo | Swing: si el **diario** marca tendencia fuerte (EMAs en cascada), **veta** operar en contra. Scalp: el H1 solo inclina el score, **sin veto**. |
| Noticias de alto impacto | ±30 min (USD) | ±15 min (USD) | No abre alrededor de NFP/CPI/FOMC, etc. |

> 🟡 **La diferencia clave del oro frente al EUR/USD** es el **filtro macro**: el oro swing
> respeta el gráfico diario con veto duro; el scalp solo lo usa como empujón suave. Los bots
> de EUR/USD **no tienen** este filtro.

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

| Parámetro de riesgo | Oro swing | Oro scalp |
|---|---|---|
| `RISK_PER_TRADE` | 1% por trade | 1% por trade |
| `MAX_OPEN_TRADES` | **5** (riesgo total ≈ 5%) | 3 (≈ 3%) |
| `MAX_DAILY_LOSS_PCT` | 5% → detiene el día | 5% → detiene el día |
| `SL_ATR_MULT` / `TP_ATR_MULT` | 2.0 / 4.5 | 1.5 / 3.0 |
| `MIN_RR` (R:R mínimo) | 2.0 | 1.8 |
| `MAX_SPREAD_POINTS` | 80 | 70 |

**Protección de la ganancia** (en cada ciclo, sobre lo abierto):

| Mecanismo | Oro swing | Oro scalp | Qué hace |
|---|---|---|---|
| Break-even "BE+" | dispara al **40%** del camino al TP | al **55%** | Mueve el SL a poco por encima de la entrada (cubre spread + margen) → si revierte, sale en positivo. |
| Trailing ATR | `2.5 × ATR` | `1.0 × ATR` | Sigue al precio dejando respirar la tendencia. |
| Lock progresivo | START 1.5×ATR, asegura 35→90% | START 1.0×ATR, asegura 40→90% | A medida que el trade gana, asegura una fracción creciente del profit (≈1:1). |
| Anti-duplicado | `1.0 × ATR` | `0.75 × ATR` | No apila trades en la misma dirección demasiado cerca de uno existente. |

---

## 7. Tabla resumen de valores afinados

| Parámetro | Oro swing | Oro scalp |
|---|---|---|
| `PRIMARY_TF` / `TREND_TF` / `HIGHER_TF` | H1 / H4 / D1 | M5 / M15 / H1 |
| `LOOP_INTERVAL` | 60 s | 15 s |
| `MIN_SIGNAL_SCORE` | 5.0 | 5.5 |
| `SL_ATR_MULT` / `TP_ATR_MULT` | 2.0 / 4.5 | 1.5 / 3.0 |
| `MIN_RR` | 2.0 | 1.8 |
| `RISK_PER_TRADE` / `MAX_OPEN_TRADES` | 1% / 5 | 1% / 3 |
| `BE_TRIGGER_PCT` | 0.40 | 0.55 |
| `TRAILING_ATR_MULT` | 2.5 | 1.0 |
| Lock START / MIN→MAX / FULL | 1.5 / .35→.90 / 4.0 | 1.0 / .40→.90 / 2.7 |
| `ANTI_DUP_ATR_MULT` | 1.0 | 0.75 |
| `ADX_MIN_TREND` | 20 | 18 |
| `RSI_NO_SELL_BELOW` / `RSI_NO_BUY_ABOVE` | 32 / 68 | 30 / 70 |
| `MAX_SPREAD_POINTS` | 80 | 70 |
| Order-flow ventana / peso | 300 s / 0.5 | 120 s / 0.8 |
| DXY TF / peso | H4 / 0.8 | H1 / 0.4 |
| Macro | **D1 (veto)** | **H1 (sesgo)** |
| Noticias ±min / divisas | 30 / USD | 15 / USD |

> Los valores viven en cada `config.py` y mandan sobre esta tabla si algún día se afinan.
> Cualquier cambio necesita **reiniciar el bot**.

---

## 8. Ejemplo numérico (oro swing)

BUY de oro con `ATR = 8.42` y balance `10.000 USD`:

| Cálculo | Resultado |
|---|---|
| Dinero a arriesgar (1%) | 100 USD |
| Distancia del SL (`2.0 × 8.42`) | 16.84 USD por onza |
| Distancia del TP (`4.5 × 8.42`) | 37.89 USD por onza |
| Ratio R:R | `37.89 / 16.84 ≈ 2.25 : 1` (cumple `MIN_RR = 2.0`) ✅ |
| Lote | ajustado para que, si toca el SL, la pérdida sea ≈ 100 USD |

Si el ATR fuera el doble, el SL sería el doble de ancho y el bot compraría **la mitad de
lote**: la pérdida máxima seguiría siendo ~100 USD (1%).
