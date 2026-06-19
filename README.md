# XAU/USD Scalping Bot — MetaTrader 5

Bot de trading automático para el par **XAU/USD (Oro)** enfocado en scalping con
gestión de riesgo dinámica, análisis multitemporal y detección de 35+ patrones de velas.

---

## Requisitos del sistema

| Requisito | Versión mínima |
|---|---|
| Windows | 10 / 11 (MT5 solo corre en Windows) |
| Python | 3.9+ |
| MetaTrader 5 (terminal) | Cualquier broker con XAUUSD |
| RAM libre | 512 MB |

> El terminal MetaTrader 5 debe estar **abierto y con sesión iniciada** antes de ejecutar el bot.

---

## Instalación

```bash
# 1. Clonar o descargar el proyecto
cd xauusd_bot

# 2. (Opcional) Crear entorno virtual
python -m venv venv
venv\Scripts\activate       # Windows

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## Configuración

Abre `config.py` y ajusta los siguientes valores **antes** de ejecutar:

### Cuenta MT5

```python
MT5_LOGIN    = 0      # Tu número de cuenta (0 = usa la cuenta activa en el terminal)
MT5_PASSWORD = ""     # Contraseña (dejar vacío si ya iniciaste sesión en MT5)
MT5_SERVER   = ""     # Servidor del broker (ej: "ICMarkets-Demo02")
```

> Si MT5 ya tiene una sesión activa y `MT5_LOGIN = 0`, el bot la usa directamente.

### Símbolo

Algunos brokers nombran el oro diferente. Ajusta según el tuyo:

```python
SYMBOL = "XAUUSD"    # Alternativas: "GOLD", "XAUUSD.", "XAUUSDm"
```

### Riesgo por operación

```python
RISK_PER_TRADE     = 0.01   # 1% del balance por trade
MAX_OPEN_TRADES    = 5      # Máximo de posiciones simultáneas
MAX_DAILY_LOSS_PCT = 0.05   # Detiene el bot si pierde 5% en el día
```

### SL y TP (basados en ATR)

```python
SL_ATR_MULT = 1.5   # Stop Loss = 1.5 × ATR
TP_ATR_MULT = 2.5   # Take Profit = 2.5 × ATR
```

### Umbral de señal

```python
MIN_SIGNAL_SCORE = 4.5  # Score mínimo para abrir trade (rango: −12 a +12)
```

Reducir a 3.5 para más trades (más agresivo). Subir a 5.5 para menos trades (más conservador).

---

## Ejecución

```bash
python main.py
```

Para detener: **Ctrl+C** — el bot finaliza el ciclo actual y se desconecta limpiamente.
Las posiciones abiertas se **mantienen en MT5** al detener el bot.

---

## Qué verás en consola

```
════════════════════════════════════════════════════════════════
🤖  XAU/USD Scalping Bot  |  by mt5-python
════════════════════════════════════════════════════════════════
[14:30:00] INFO | ✅ Conectado. Cuenta: #12345678 @ ICMarkets-Demo02
[14:30:00] INFO | ✅ XAUUSD | Dígitos: 2 | Punto: 0.01 | Contrato: 100 oz
[14:30:00] INFO | ⚙   Símbolo: XAUUSD | TF: M5/M15/H1 | Score mín: ±4.5 | Riesgo: 1%/trade
[14:30:00] INFO | 💰  Balance: 10,000.00 USD | Equity: 10,000.00 | Margen libre: 10,000.00
[14:30:00] INFO | ▶   Bot activo. Presiona Ctrl+C para detener.
[14:30:00] INFO | 🔄 Loop iniciado (cada 30s). Ctrl+C para detener.

[14:30:30] INFO | 📊 HOLD | Score:  +2.41 | EMA:+1.20 RSI:-0.27 MACD:+0.72 ... | ATR: 1.145
[14:31:00] INFO | 📊 BUY  | Score:  +5.23 | EMA:+2.10 RSI:+0.63 MACD:+0.81 ... | ATR: 1.234
[14:31:00] INFO | 🕯 Patrones alcistas: Bullish Engulfing, Hammer
[14:31:00] INFO | 🎯 Señal BUY | Score: +5.23 | Lote: 0.44 | Entry: 2045.23 | SL: 2043.38 | TP: 2048.31
[14:31:00] INFO | ✅ BUY abierto | Ticket: #38291042 | Lote: 0.44 | Entry: 2045.23 | SL: 2043.38 | TP: 2048.31
[14:31:30] INFO | ☑  Break-even BUY #38291042 | SL: 2043.38 → 2045.24
[14:32:00] INFO | ↑  Trailing BUY #38291042 | SL 2045.24 → 2046.15
[14:40:00] INFO | ── STATUS 14:40:00 ── Ciclo #20 | Trades sesión: 3 | P&L hoy: +$34.50 | Balance: 10,034.50 USD
```

---

## Cómo funciona

### Ciclo de 30 segundos

Cada ciclo el bot:

1. **Verifica la conexión** con MT5 y reconecta si es necesario.
2. **Descarga 300 velas** de M5 (scalping), M15 (tendencia) y H1 (contexto).
3. **Calcula 9 indicadores** en tiempo real:
   - EMA 9, 21, 50, 200 — dirección y momentum
   - SMA 20, 50 — tendencia suavizada
   - RSI (14) — sobrecompra/sobreventa
   - MACD (12/26/9) — cruce de momentum
   - ATR (14) — volatilidad (también define SL/TP y lote)
   - Bandas de Bollinger (20, 2σ) — rango y squeeze
   - VWAP rodante — precio justo institucional
   - Soporte y Resistencia — niveles clave por pivots + psicológicos
4. **Detecta 35+ patrones** de velas japonesas (Doji, Hammer, Engulfing, Morning Star, Three White Soldiers, etc.)
5. **Calcula el score ponderado** sumando todos los indicadores con sus pesos.
6. **Gestiona las posiciones abiertas** (break-even y trailing stop).
7. **Abre un trade** si el score supera el umbral y las condiciones de riesgo se cumplen.

### Sistema de scoring

| Componente | Peso | Rango bruto |
|---|---|---|
| EMAs (posición + cruces) | ×1.0 | −3.0 a +3.0 |
| RSI | ×0.9 | −2.0 a +2.0 |
| MACD | ×0.9 | −2.0 a +2.0 |
| Patrones de velas | ×0.8 | −4.0 a +4.0 |
| Bollinger Bands | ×0.6 | −2.0 a +2.0 |
| Soporte/Resistencia | ×0.5 | −1.5 a +1.5 |
| VWAP | ×0.3 | −1.0 a +1.0 |
| Volumen | ×0.2 | −0.5 a +0.5 |
| Confirmación M15 | ×0.4 | (del score EMA) |

Score ≥ +4.5 → **BUY** | Score ≤ −4.5 → **SELL** | Intermedio → **HOLD**

### Trades por señal

- **1 señal = 1 trade** en cada ciclo de 30 segundos.
- Si el mercado sigue favorable en ciclos consecutivos, el bot acumula hasta **5 trades simultáneos**.
- Cada trade tiene SL, TP y trailing stop **independientes**.
- El único límite de cantidad es `MAX_OPEN_TRADES` (no hay filtro de proximidad de precio).

### Gestión de riesgo automática

| Mecanismo | Comportamiento |
|---|---|
| Break-even | Dos modos configurables — ver detalle abajo |
| Trailing stop | SL sigue al precio a 0.8×ATR de distancia |
| Lote dinámico | Se recalcula en cada trade según balance actual |
| Límite diario | Bloquea nuevas operaciones si pérdida ≥ 5% del balance |
| Margen mínimo | No opera si margen libre < 10% del balance |

#### Break-even — modo "pct_tp" (regla matemática, por defecto)

Mueve el SL a break-even cuando el profit alcanza un **% de la distancia al TP real**
de la posición (no del ATR actual, que puede cambiar después de abrir el trade):

```python
BREAKEVEN_MODE = "pct_tp"
BREAKEVEN_TRIGGER_PCT_OF_TP = 0.60   # Espera el 60% del camino al TP
BREAKEVEN_BUFFER_USD = 0.50          # BE+ : margen para cubrir spread/comisión
```

Ejemplo: si el TP está a $20 de la entrada, el SL se mueve a break-even
cuando el precio ya recorrió $12 (60%) a favor.

#### Break-even — modo "structure" (regla técnica)

No usa porcentajes fijos. Solo mueve el SL cuando hay **confirmación real**
en velas de 1 minuto:

1. **Micro-fractal a favor**: si ya se formó un mínimo más alto (BUY) o
   máximo más bajo (SELL) que la entrada, ese nivel sirve de "escudo" —
   el SL se coloca justo debajo/encima de él.
2. **Vela de ruptura confirmada**: si aún no hay fractal pero ya cerró una
   vela M1 con cuerpo grande a favor (≥ 0.4×ATR de M1), se usa el
   break-even clásico (entrada + buffer).

Si ninguna condición se cumple, el SL **no se mueve**, incluso si el precio
ya está en profit — esto evita reaccionar a rupturas falsas o ruido de 1 minuto.

```python
BREAKEVEN_MODE = "structure"
MICRO_FRACTAL_LOOKBACK = 2              # Velas a cada lado para confirmar el fractal
BREAKOUT_CANDLE_BODY_ATR_MULT = 0.4     # Cuerpo mínimo de la vela de confirmación
```

---

## Archivos del proyecto

```
xauusd_bot/
├── main.py           → Loop principal, punto de entrada
├── config.py         → TODOS los parámetros configurables
├── connection.py     → Conexión y reconexión a MT5
├── data_handler.py   → Descarga de OHLCV y datos de cuenta
├── indicators.py     → EMA, SMA, RSI, MACD, ATR, BB, VWAP, S&R
├── patterns.py       → 35+ patrones de velas japonesas
├── signals.py        → Motor de scoring ponderado
├── risk_manager.py   → Lote, SL/TP, pérdida diaria
├── trade_manager.py  → Abrir, cerrar, trailing, break-even
├── logger_config.py  → Logs a consola y archivo .log
└── requirements.txt  → Dependencias Python
```

---

## Compatibilidad con brokers

El bot detecta automáticamente:
- Modo de ejecución de órdenes (`ORDER_FILLING_FOK`, `IOC`, o `RETURN`)
- Distancia mínima de SL/TP exigida por el broker (`trade_stops_level`)
- Paso de lote y lote mínimo/máximo del símbolo

Probado con brokers que ofrecen: ICMarkets, Pepperstone, XM, FP Markets.
El nombre del símbolo puede variar (`XAUUSD`, `GOLD`, `XAUUSDm`). Ajusta `SYMBOL` en `config.py`.

---

## Advertencia de riesgo

> **El trading automatizado conlleva riesgo de pérdida de capital.**
> Este bot es una herramienta de ayuda, no una garantía de beneficios.
> Prueba siempre en una **cuenta demo** antes de usar fondos reales.
> Nunca arriesgues dinero que no puedas permitirte perder.
> El rendimiento pasado no garantiza resultados futuros.