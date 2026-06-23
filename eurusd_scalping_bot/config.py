"""
╔══════════════════════════════════════════════════════════════╗
║       EUR/USD Scalping Bot — Configuración Central           ║
╚══════════════════════════════════════════════════════════════╝
Edita este archivo antes de ejecutar el bot.
Modo: Scalping PURO (M5/M15/H1) — operaciones de segundos a pocos minutos.
"""
import os
import MetaTrader5 as mt5
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# ─── CUENTA MT5 ────────────────────────────────────────────────────────────────
# ─── CREDENCIALES CARGADAS DESDE .env (seguridad mejorada) ─────────────────────
MT5_LOGIN    = int(os.getenv('MT5_LOGIN', 0))              # Número de cuenta
MT5_PASSWORD = os.getenv('MT5_PASSWORD', '')               # Contraseña de la cuenta
MT5_SERVER   = os.getenv('MT5_SERVER', '')                 # Servidor del broker

# ─── SÍMBOLO ───────────────────────────────────────────────────────────────────
SYMBOL       = "EURUSD"    # Puede variar por broker: EURUSD, EURUSD.m, etc.
MAGIC_NUMBER = 20260620    # ID único — distinto a los bots de Oro y EUR/USD swing

# ─── TEMPORALIDADES ────────────────────────────────────────────────────────────
PRIMARY_TF   = mt5.TIMEFRAME_M5     # TF principal de análisis (M5)
TREND_TF     = mt5.TIMEFRAME_M15    # TF de confirmación de tendencia (M15)
HIGHER_TF    = mt5.TIMEFRAME_H1     # Contexto de tendencia mayor (H1)
TF_LABELS    = "M5/M15/H1"         # Etiqueta legible para logs

# ─── PARÁMETROS DE INDICADORES ─────────────────────────────────────────────────
EMA_FAST     = 9
EMA_MED      = 21
EMA_SLOW     = 50
EMA_TREND    = 200
SMA_FAST     = 20
SMA_SLOW     = 50
RSI_PERIOD   = 14
RSI_OB       = 70          # Umbral sobrecompra
RSI_OS       = 30          # Umbral sobreventa
MACD_FAST    = 12
MACD_SLOW    = 26
MACD_SIGNAL  = 9
ATR_PERIOD   = 14
BB_PERIOD    = 20
BB_STD       = 2.0
VWAP_PERIOD  = 288         # 288 velas M5 = VWAP rodante de 24 horas (antes 24 velas H1)
SR_LOOKBACK  = 14          # Lookback más corto para pivots S/R locales en M5
SR_LEVELS    = 5           # Menos niveles, más cercanos al precio (scalping)
SR_24H_CANDLES = 288       # 288 velas M5 = 24h (antes 24 velas H1)
SR_CLUSTER_ATR_MULT = 0.30 # Tolerancia para agrupar niveles S/R = 0.30×ATR (escala al instrumento)
PSYCH_LEVEL_STEP    = 0.0010  # Niveles psicológicos cada 10 pips (más granular para scalping M5)

# ─── GESTIÓN DE RIESGO ─────────────────────────────────────────────────────────
RISK_PER_TRADE      = 0.01     # 1% del balance por operación
MAX_OPEN_TRADES     = 3        # Menos trades simultáneos: en scalping rotan más rápido
MAX_DAILY_LOSS_PCT  = 0.05     # 5% pérdida diaria → detener
SL_ATR_MULT         = 1.0      # SL muy ajustado: scalp puro, pérdidas pequeñas (~3-8 pips en M5)
TP_ATR_MULT         = 1.5      # TP corto → R:R 1.5:1. Entrar y salir rápido (no aguantar el movimiento)
MIN_RR              = 1.2      # R:R real mínimo (FUNCIONAL: descarta si el broker deforma el SL/TP)
MIN_LOT             = 0.01     # Lote mínimo absoluto
MAX_LOT             = 3.0      # Lote máximo absoluto
BREAKEVEN_ATR_MULT  = 0.6      # (FALLBACK) Solo se usa si la posición NO tiene TP definido.
BE_TRIGGER_PCT      = 0.55     # Mover a BE+ cuando el precio recorra ≥ 55% del camino entrada→TP
                               # (regla 50-70%, calza bien en scalping). Baja para proteger antes.
BE_PLUS_POINTS      = 5        # "BE+": margen EXTRA (puntos) además del spread. SL queda en:
                               #   entrada ∓ (spread_actual + BE_PLUS_POINTS×point) → sale en positivo.
TRAILING_ATR_MULT   = 0.5      # Trailing pegadísimo al precio (scalp: protege cada pip)
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # Exige separación mínima entre entradas de la misma dirección
ANTI_DUP_ATR_MULT   = 0.75     # Distancia mínima (en ATR) entre entradas misma dirección. Antes 0.5
                               # fijo → apilaba demasiado. 0.75 separa más sin frenar tanto el
                               # ritmo del scalping. Sube a 1.0+ para separar aún más.

# ─── TRAILING PROGRESIVO (lock de ganancia) ────────────────────────────────────
# El trailing clásico (TRAILING_ATR_MULT) deja "respirar" al precio, pero cuando el
# trade ya va muy en ganancia devuelve demasiado en un retroceso: el SL queda lejos
# del precio y un "back" puede borrar casi todo el profit. El lock PROGRESIVO mueve
# el SL detrás del precio asegurando una FRACCIÓN CRECIENTE del profit abierto:
# arranca flojo (deja correr la tendencia) y se aprieta hacia ~1:1 conforme el trade
# avanza, para que un retroceso salga en POSITIVO en vez de en pérdida.
# En cada ciclo el trailing aplica el SL MÁS protector entre el ATR clásico y este lock.
USE_PROGRESSIVE_TRAIL = True    # Activar el lock progresivo de ganancia
TRAIL_LOCK_START_ATR  = 0.5     # Empezar a asegurar profit cuando éste supere 0.5×ATR (≈ 1/3 del TP corto)
TRAIL_LOCK_PCT_MIN    = 0.40    # Al arrancar asegura el 40% del profit (scalp puro → protege cada pip)
TRAIL_LOCK_PCT_MAX    = 0.90    # Tope: asegura hasta el 90% del profit (≈ 1:1) en trades maduros
TRAIL_LOCK_FULL_ATR   = 1.3     # Llega al MAX cuando el profit alcanza 1.3×ATR (≈ justo antes del TP 1.5×ATR).
                                # La fracción sube linealmente de _MIN a _MAX entre START y FULL.
                                # ¿Asegurar aún más rápido? Baja START y/o sube PCT_MIN.

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 4.5      # Umbral más bajo → MÁS entradas frecuentes (el scalp puro vive del
                               # volumen de operaciones rápidas, no de esperar la señal perfecta)
ATR_VOLATILITY_MIN  = 0.00012  # ATR M5 de EURUSD ≈ 0.0002–0.0006; filtrar mercado plano
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia M5 (anti-contratendencia)
# Anti-agotamiento: no abrir NUEVAS entradas en extremos de RSI (vender el suelo /
# comprar el techo), donde el movimiento suele agotarse y revertir.
RSI_NO_SELL_BELOW   = 30      # No abrir SELL si el RSI M5 ≤ 30 (sobrevendido → posible suelo)
RSI_NO_BUY_ABOVE    = 70      # No abrir BUY  si el RSI M5 ≥ 70 (sobrecomprado → posible techo)
SCORE_WEIGHTS = {
    "ema":      1.3,    # ↑ Alineación EMA sigue siendo lo más importante
    "rsi":      1.0,    # ↑ RSI en M5 es clave para timing de entrada
    "macd":     1.1,    # ↑ Cruces MACD confiables como confirmación de momentum
    "patterns": 0.8,    # ↑ Patrones de vela en M5 (más ruidosos, pero útiles)
    "bb":       0.7,    # ↑ Squeeze indica volatilidad baja
    "sr":       0.9,    # = Soportes/Resistencias fundamentales
    "vwap":     0.3,    # ↑ Más relevante en scalping (precio justo intradía)
    "volume":   0.4,    # ↑ Volumen confirma breakouts
    "trend_tf": 0.8,    # ↓ M15 confirma, pero pesa algo menos que en swing
    "orderflow":   0.8, # 🟢 Presión compradora/vendedora por ticks (scalp: más peso)
    "intermarket": 0.3, # 🌐 Sesgo del índice dólar DXY (inverso; poco peso en scalp puro)
}

# ─── ADX — FILTRO DE FUERZA DE TENDENCIA ───────────────────────────────────────
# En mercado lateral (ADX bajo) los cruces son ruido; si ADX < umbral, no abrir.
USE_ADX_FILTER  = True
ADX_PERIOD      = 14
ADX_MIN_TREND   = 18      # scalping M5 es más ruidoso → umbral algo más bajo que swing.

# ─── ORDER-FLOW — PRESIÓN COMPRADORA/VENDEDORA POR TICKS ────────────────────────
# Proxy del "volumen de compra vs venta" con ticks recientes: delta ∈ [-1,1]. Nudge.
USE_ORDERFLOW           = True
ORDERFLOW_LOOKBACK_SECS = 120     # ventana de ticks (scalp puro: 2 min, muy reactivo)
ORDERFLOW_MIN_TICKS     = 50

# ─── INTER-MERCADO — ÍNDICE DÓLAR (DXY) ─────────────────────────────────────────
# EUR/USD es INVERSO al dólar. ⚠ Verifica el símbolo del índice dólar en tu broker;
#    XM suele usar "USDX". Si no existe, el factor se desactiva solo (sin error).
USE_INTERMARKET     = True
INTERMARKET_SYMBOL  = "USDX-SEP26"  # Índice dólar (XM, futuro trimestral). Vence ~2026-09-11 → al
                                    # rolar, cambia el sufijo al siguiente contrato (p.ej. USDX-DEC26).
INTERMARKET_INVERSE = True
INTERMARKET_TF      = mt5.TIMEFRAME_H1   # TF del DXY (scalping: H1)
INTERMARKET_CANDLES = 200

# ─── FILTRO DE NOTICIAS — CALENDARIO ECONÓMICO ──────────────────────────────────
# Bloquea abrir trades alrededor de eventos de alto impacto (NFP, CPI, FOMC, BCE...).
# JSON semanal gratuito de ForexFactory; si no hay internet, NO bloquea (fail-open).
USE_NEWS_FILTER          = True
NEWS_CURRENCIES          = ["USD", "EUR"]  # EUR/USD lo mueven ambas divisas
NEWS_IMPACTS             = ["High"]
NEWS_BLACKOUT_BEFORE_MIN = 15              # scalp: ventana más corta
NEWS_BLACKOUT_AFTER_MIN  = 15
NEWS_FAIL_OPEN           = True

# ─── NOTIFICACIONES TELEGRAM ────────────────────────────────────────────────────
# Avisa al celular cuando el bot abre/cierra trades, arranca/se detiene o pierde
# la conexión. El TOKEN y el CHAT_ID se cargan desde .env (NO los pongas aquí).
# Cómo obtenerlos (una sola vez, sirven para los 4 bots):
#   1. En Telegram habla con @BotFather → /newbot → te da el TELEGRAM_BOT_TOKEN.
#   2. Habla con @userinfobot → te da tu TELEGRAM_CHAT_ID (número).
#   3. Escríbele "hola" a TU propio bot primero; si no, no puede enviarte mensajes.
#   4. En el .env agrega:  TELEGRAM_BOT_TOKEN=...   y   TELEGRAM_CHAT_ID=...
# Si falta el token o el chat_id, las notificaciones se desactivan solas (sin error).
USE_TELEGRAM       = True
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_PREFIX    = "[EURUSD scalp]"   # etiqueta para distinguir este bot en el chat

# ─── DATOS ─────────────────────────────────────────────────────────────────────
CANDLES_PRIMARY  = 1500   # 1500 velas M5 ≈ 5.2 días (suficiente para EMA200 estable)
CANDLES_TREND    = 500    # 500 velas M15 ≈ 5.2 días
CANDLES_HIGHER   = 500    # 500 velas H1 ≈ 20 días de contexto

# ─── BOT ───────────────────────────────────────────────────────────────────────
LOOP_INTERVAL    = 10           # 10s entre ciclos: reaccionar muy rápido dentro de la vela M5
MAX_SLIPPAGE     = 15            # Menor tolerancia: en scalping el slippage pesa más sobre el TP
MAX_SPREAD_POINTS = 18          # Spread máx = 1.8 pips. Con TP de ~3-8 pips el spread pesa muchísimo,
                                # así que somos estrictos: solo entradas baratas. Si nunca opera y tu
                                # broker tiene spread mayor, súbelo (pero el scalp puro necesita spread bajo).
LOG_FILE         = "eurusd_scalping_bot.log"
