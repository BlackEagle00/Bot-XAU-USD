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
BREAKEVEN_ATR_MULT  = 0.6      # Asegura MUY rápido: SL a break-even apenas hay +0.6×ATR de profit
TRAILING_ATR_MULT   = 0.5      # Trailing pegadísimo al precio (scalp: protege cada pip)
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # No acumular en el mismo nivel de precio
                               # True  = exige al menos 0.5×ATR de distancia entre entradas

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 4.5      # Umbral más bajo → MÁS entradas frecuentes (el scalp puro vive del
                               # volumen de operaciones rápidas, no de esperar la señal perfecta)
ATR_VOLATILITY_MIN  = 0.00012  # ATR M5 de EURUSD ≈ 0.0002–0.0006; filtrar mercado plano
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia M5 (anti-contratendencia)
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
}

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
