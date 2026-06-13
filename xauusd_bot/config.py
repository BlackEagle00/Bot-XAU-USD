"""
╔══════════════════════════════════════════════════════════════╗
║       XAU/USD Swing Trading Bot — Configuración Central     ║
╚══════════════════════════════════════════════════════════════╝
Edita este archivo antes de ejecutar el bot.
Modo: Swing Trading (H1/H4/D1) — operaciones de horas a días.
"""
import MetaTrader5 as mt5

# ─── CUENTA MT5 ────────────────────────────────────────────────────────────────
# ─── CREDENCIALES DE EJEMPLO CUENTA DEMO ───────────────────────────────────────
MT5_LOGIN    = 10011299165           # Número de cuenta (0 = usar cuenta activa en el terminal)
MT5_PASSWORD = "1wZwC!Vw"          # Contraseña de la cuenta
MT5_SERVER   = "MetaQuotes-Demo"          # Servidor del broker (ej: "ICMarkets-Demo02")

# ─── SÍMBOLO ───────────────────────────────────────────────────────────────────
SYMBOL       = "XAUUSD"    # Puede variar por broker: GOLD, XAUUSD.
MAGIC_NUMBER = 20250101    # ID único para identificar los trades del bot

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

# ─── GESTIÓN DE RIESGO ─────────────────────────────────────────────────────────
RISK_PER_TRADE      = 0.01     # 1% del balance por operación
MAX_OPEN_TRADES     = 2        # Máximo 2 trades simultáneos (swing = calidad > cantidad)
MAX_DAILY_LOSS_PCT  = 0.05     # 5% pérdida diaria → detener (más conservador en swing)
SL_ATR_MULT         = 2.0      # SL más amplio para tolerar movimientos normales de H1
TP_ATR_MULT         = 4.5      # TP amplio → R:R de 2.25:1
MIN_RR              = 2.0      # R:R mínimo más exigente en swing
MIN_LOT             = 0.01     # Lote mínimo absoluto
MAX_LOT             = 3.0      # Lote máximo absoluto
BREAKEVEN_ATR_MULT  = 1.5      # Mover SL a BE cuando profit >= 1.5×ATR
TRAILING_ATR_MULT   = 2.5      # Trailing amplio para no cortar tendencias swing
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # En swing no acumular: 1 posición por dirección
                               # True  = exige al menos 0.5×ATR de distancia entre entradas

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 6.5      # Umbral más alto → señales más selectivas y de mayor calidad
ATR_VOLATILITY_MIN  = 2.0      # ATR H1 de XAUUSD ≈ $8–25; filtrar mercado plano
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia H1 (anti-contratendencia)
SCORE_WEIGHTS = {
    "ema":      1.2,   # Más peso: la alineación EMA es clave para confirmar tendencia swing
    "rsi":      0.8,   # Menos peso: RSI en H1 es menos preciso para timing exacto
    "macd":     1.0,   # Más peso: cruces MACD en H1 son señales de alta fiabilidad
    "patterns": 0.6,   # Menos peso: patrones de vela solos son menos determinantes en H1
    "bb":       0.5,   # Ligeramente menos relevante
    "sr":       0.8,   # Más peso: niveles S/R son fundamentales para entradas swing
    "vwap":     0.2,   # Menos relevante en H1 (VWAP es más herramienta intraday)
    "volume":   0.3,   # Más peso: el volumen confirma breakouts y continuaciones
    "trend_tf": 0.6,   # Más peso: la confirmación del H4 es crítica en swing
}

# ─── DATOS ─────────────────────────────────────────────────────────────────────
CANDLES_PRIMARY  = 500    # 500 velas H1 ≈ 20 días de historia
CANDLES_TREND    = 200    # 200 velas H4 ≈ 33 días
CANDLES_HIGHER   = 365    # 365 velas D1 ≈ 1 año de contexto macro

# ─── BOT ───────────────────────────────────────────────────────────────────────
LOOP_INTERVAL    = 300         # 5 minutos entre ciclos (suficiente para análisis H1)
MAX_SLIPPAGE     = 30          # Mayor tolerancia al slippage en swing
LOG_FILE         = "xauusd_bot.log"
