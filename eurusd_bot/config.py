"""
╔══════════════════════════════════════════════════════════════╗
║       EUR/USD Swing Trading Bot — Configuración Central     ║
╚══════════════════════════════════════════════════════════════╝
Edita este archivo antes de ejecutar el bot.
Modo: Swing Trading (H1/H4/D1) — operaciones de horas a días.
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
MAGIC_NUMBER = 20260619    # ID único — distinto al del bot de Oro para no mezclar posiciones

# ─── TEMPORALIDADES ────────────────────────────────────────────────────────────
PRIMARY_TF   = mt5.TIMEFRAME_H1    # TF principal de análisis (H1)
TREND_TF     = mt5.TIMEFRAME_H4    # TF de confirmación de tendencia (H4)
HIGHER_TF    = mt5.TIMEFRAME_D1    # Contexto macro diario (D1)
TF_LABELS    = "H1/H4/D1"         # Etiqueta legible para logs

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
VWAP_PERIOD  = 24          # 24 velas H1 = VWAP rodante de 24 horas
SR_LOOKBACK  = 20          # Mayor lookback para pivots S/R en H1
SR_LEVELS    = 7           # Más niveles S/R para análisis swing
SR_24H_CANDLES = 24        # 24 velas H1 = 24h (rango del día en indicators.py)
SR_CLUSTER_ATR_MULT = 0.30 # Tolerancia para agrupar niveles S/R = 0.30×ATR (escala al instrumento)
PSYCH_LEVEL_STEP    = 0.0050  # Niveles psicológicos cada 50 pips (1.1400, 1.1450...). En Oro sería 5.0

# ─── GESTIÓN DE RIESGO ─────────────────────────────────────────────────────────
RISK_PER_TRADE      = 0.01     # 1% del balance por operación
MAX_OPEN_TRADES     = 3        # Máx 3 simultáneos: con REQUIRE_TREND_ALIGNMENT todos van en la misma
                               # dirección → 3% de riesgo correlacionado en vez de 4% (más balanceado)
MAX_DAILY_LOSS_PCT  = 0.05     # 5% pérdida diaria → detener (más conservador en swing)
SL_ATR_MULT         = 1.2      # SL más ajustado (antes 2.0) — pedido del usuario: se veía muy lejos del entry
TP_ATR_MULT         = 2.7      # TP más cercano (antes 4.5) — mantiene el mismo R:R de 2.25:1
MIN_RR              = 2.0      # R:R mínimo más exigente en swing
MIN_LOT             = 0.01     # Lote mínimo absoluto
MAX_LOT             = 3.0      # Lote máximo absoluto
BREAKEVEN_ATR_MULT  = 0.9      # (FALLBACK) Solo se usa si la posición NO tiene TP definido.
BE_TRIGGER_PCT      = 0.50     # Mover a BE+ cuando el precio recorra ≥ 50% del camino entrada→TP.
                               # Baja a 0.4 para proteger antes; sube para dejar correr más.
BE_PLUS_POINTS      = 5        # "BE+": margen EXTRA (puntos) además del spread. SL queda en:
                               #   entrada ∓ (spread_actual + BE_PLUS_POINTS×point) → sale en positivo.
TRAILING_ATR_MULT   = 1.5      # Trailing más cercano (escalado junto con el SL)
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # Exige separación mínima entre entradas de la misma dirección
ANTI_DUP_ATR_MULT   = 1.0      # Distancia mínima (en ATR) entre entradas misma dirección. Antes 0.5
                               # fijo → apilaba demasiadas ventas pegadas que morían juntas en el
                               # rebote. 1.0 = entradas más separadas. Sube a 1.5-2.0 para separar más.

# ─── TRAILING PROGRESIVO (lock de ganancia) ────────────────────────────────────
# El trailing clásico (TRAILING_ATR_MULT) deja "respirar" al precio, pero cuando el
# trade ya va muy en ganancia devuelve demasiado en un retroceso: el SL queda lejos
# del precio y un "back" puede borrar casi todo el profit. El lock PROGRESIVO mueve
# el SL detrás del precio asegurando una FRACCIÓN CRECIENTE del profit abierto:
# arranca flojo (deja correr la tendencia) y se aprieta hacia ~1:1 conforme el trade
# avanza, para que un retroceso salga en POSITIVO en vez de en pérdida.
# En cada ciclo el trailing aplica el SL MÁS protector entre el ATR clásico y este lock.
USE_PROGRESSIVE_TRAIL = True    # Activar el lock progresivo de ganancia
TRAIL_LOCK_START_ATR  = 0.9     # Empezar a asegurar profit cuando éste supere 0.9×ATR (≈ 1/3 del TP)
TRAIL_LOCK_PCT_MIN    = 0.35    # Al arrancar asegura el 35% del profit abierto (aún deja respirar)
TRAIL_LOCK_PCT_MAX    = 0.90    # Tope: asegura hasta el 90% del profit (≈ 1:1) en trades maduros
TRAIL_LOCK_FULL_ATR   = 2.4     # Llega al MAX cuando el profit alcanza 2.4×ATR (≈ justo antes del TP 2.7×ATR).
                                # La fracción sube linealmente de _MIN a _MAX entre START y FULL.
                                # ¿Asegurar aún más rápido? Baja START y/o sube PCT_MIN.

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 5.0      # Umbral optimizado → más operaciones sin sacrificar calidad (+30-40%)
ATR_VOLATILITY_MIN  = 0.0004   # ATR H1 de EURUSD ≈ 0.0005–0.0015; filtrar mercado plano
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia H1 (anti-contratendencia)
# Anti-agotamiento: no abrir NUEVAS entradas en extremos de RSI (vender el suelo /
# comprar el techo), donde el movimiento suele agotarse y revertir.
RSI_NO_SELL_BELOW   = 32      # No abrir SELL si el RSI H1 ≤ 32 (sobrevendido → posible suelo)
RSI_NO_BUY_ABOVE    = 68      # No abrir BUY  si el RSI H1 ≥ 68 (sobrecomprado → posible techo)
SCORE_WEIGHTS = {
    "ema":      1.3,    # ↑ Alineación EMA es lo más importante para swing
    "rsi":      1.0,    # ↑ RSI en H1 es clave para timing de entrada
    "macd":     1.1,    # ↑ Cruces MACD muy confiables en H1
    "patterns": 0.8,    # ↑ Patrones H1 son señales fuertes de reversión
    "bb":       0.7,    # ↑ Squeeze indica volatilidad baja
    "sr":       0.9,    # = Soportes/Resistencias fundamentales
    "vwap":     0.1,    # ↓ Menos relevante en timeframes altos
    "volume":   0.4,    # ↑ Volumen confirma breakouts
    "trend_tf": 1.0,    # ↑ H4 es MUY importante para contexto swing
    "orderflow":   0.5, # 🟢 Presión compradora/vendedora por ticks (nudge, máx ±0.5)
    "intermarket": 0.8, # 🌐 Sesgo del índice dólar DXY (inverso; nudge, máx ±1.2)
}

# ─── ADX — FILTRO DE FUERZA DE TENDENCIA ───────────────────────────────────────
# En mercado lateral (ADX bajo) los cruces de EMA son ruido y terminan en SL.
# Si ADX < umbral, no se abren NUEVAS operaciones.
USE_ADX_FILTER  = True
ADX_PERIOD      = 14
ADX_MIN_TREND   = 20      # < 20 = lateral/chop (swing). Sube a 25 para exigir tendencia más clara.

# ─── ORDER-FLOW — PRESIÓN COMPRADORA/VENDEDORA POR TICKS ────────────────────────
# Proxy del "volumen de compra vs venta" con ticks recientes: delta ∈ [-1,1]. Nudge.
USE_ORDERFLOW           = True
ORDERFLOW_LOOKBACK_SECS = 300     # ventana de ticks a analizar (swing: 5 min)
ORDERFLOW_MIN_TICKS     = 50

# ─── INTER-MERCADO — ÍNDICE DÓLAR (DXY) ─────────────────────────────────────────
# EUR/USD es INVERSO al dólar: DXY bajando = viento de cola alcista para el EUR.
# ⚠ Verifica el nombre del símbolo del índice dólar en tu broker (Market Watch).
#    XM suele usar "USDX". Si no existe, el factor se desactiva solo (sin error).
USE_INTERMARKET     = True
INTERMARKET_SYMBOL  = "USDX-SEP26"  # Índice dólar (XM, futuro trimestral). Vence ~2026-09-11 → al
                                    # rolar, cambia el sufijo al siguiente contrato (p.ej. USDX-DEC26).
INTERMARKET_INVERSE = True              # EUR/USD es inverso al USD
INTERMARKET_TF      = mt5.TIMEFRAME_H4  # TF para medir la tendencia del DXY (swing)
INTERMARKET_CANDLES = 200

# ─── FILTRO DE NOTICIAS — CALENDARIO ECONÓMICO ──────────────────────────────────
# Bloquea abrir trades alrededor de eventos de alto impacto (NFP, CPI, FOMC, BCE...).
# JSON semanal gratuito de ForexFactory; si no hay internet, NO bloquea (fail-open).
USE_NEWS_FILTER          = True
NEWS_CURRENCIES          = ["USD", "EUR"]  # EUR/USD lo mueven ambas divisas
NEWS_IMPACTS             = ["High"]
NEWS_BLACKOUT_BEFORE_MIN = 30
NEWS_BLACKOUT_AFTER_MIN  = 30
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
TELEGRAM_PREFIX    = "[EURUSD swing]"   # etiqueta para distinguir este bot en el chat

# ─── DATOS ─────────────────────────────────────────────────────────────────────
CANDLES_PRIMARY  = 500    # 500 velas H1 ≈ 20 días de historia
CANDLES_TREND    = 200    # 200 velas H4 ≈ 33 días
CANDLES_HIGHER   = 365    # 365 velas D1 ≈ 1 año de contexto macro

# ─── BOT ───────────────────────────────────────────────────────────────────────
LOOP_INTERVAL    = 60          # 1 minuto entre ciclos (más reactividad, mejor capturas de entrada)
MAX_SLIPPAGE     = 30          # Mayor tolerancia al slippage en swing
MAX_SPREAD_POINTS = 50         # Spread máx permitido (en puntos) = 5 pips en EURUSD. Normal ≈ 1-2 pips;
                               # bloquea ciclos cuando el spread se dispara (noticias, baja liquidez).
LOG_FILE         = "eurusd_bot.log"
