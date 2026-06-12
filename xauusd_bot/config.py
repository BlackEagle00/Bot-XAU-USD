"""
╔══════════════════════════════════════════════════════════════╗
║        XAU/USD Scalping Bot — Configuración Central         ║
╚══════════════════════════════════════════════════════════════╝
Edita este archivo antes de ejecutar el bot.
"""

"""
Name     : Name     : 
Type     : Forex Hedged USD
Server   : MetaQuotes-Demo
Login    : 10011299165
Password : 1wZwC!Vw
Investor : OpNuQc_6
"""

import MetaTrader5 as mt5

# ─── CUENTA MT5 ────────────────────────────────────────────────────────────────
MT5_LOGIN    = 10011299165           # Número de cuenta (0 = usar cuenta activa en el terminal)
MT5_PASSWORD = "1wZwC!Vw"          # Contraseña de la cuenta
MT5_SERVER   = "MetaQuotes-Demo"          # Servidor del broker (ej: "ICMarkets-Demo02")

# ─── SÍMBOLO ───────────────────────────────────────────────────────────────────
SYMBOL       = "XAUUSD"    # Puede variar por broker: GOLD, XAUUSD.
MAGIC_NUMBER = 20250101    # ID único para identificar los trades del bot

# ─── TEMPORALIDADES ────────────────────────────────────────────────────────────
PRIMARY_TF   = mt5.TIMEFRAME_M5    # TF principal de scalping (M5)
TREND_TF     = mt5.TIMEFRAME_M15   # TF de confirmación de tendencia
HIGHER_TF    = mt5.TIMEFRAME_H1    # Contexto macro

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
VWAP_PERIOD  = 50          # VWAP rodante en N velas
SR_LOOKBACK  = 15          # Velas para detectar pivots S/R
SR_LEVELS    = 5           # Niveles S/R a mantener

# ─── GESTIÓN DE RIESGO ─────────────────────────────────────────────────────────
RISK_PER_TRADE      = 0.01     # 1% del balance por operación
MAX_OPEN_TRADES     = 3        # Trades simultáneos máximos
MAX_DAILY_LOSS_PCT  = 0.1     # 10% de pérdida diaria → detener bot
SL_ATR_MULT         = 1.5      # Stop Loss = SL_ATR_MULT × ATR
TP_ATR_MULT         = 2.5      # Take Profit = TP_ATR_MULT × ATR
MIN_RR              = 1.7      # Mínimo Risk/Reward requerido
MIN_LOT             = 0.01     # Lote mínimo absoluto
MAX_LOT             = 3.0      # Lote máximo absoluto
BREAKEVEN_ATR_MULT  = 1.5       # Mover SL a BE cuando profit >= X × ATR
TRAILING_ATR_MULT   = 1.5      # Trailing stop: seguir a precio con X × ATR de distancia
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = False    # Bloquear trades demasiado cercanos a una posición existente
                               # False = permite acumular posiciones en tendencias fuertes (recomendado)
                               # True  = exige al menos 0.5×ATR de distancia entre entradas

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 5.5      # Puntuación mínima para abrir trade (máx ≈ ±12)
ATR_VOLATILITY_MIN  = 0.4      # No operar si ATR < este valor (mercado plano)
SCORE_WEIGHTS = {
    "ema":      1.0,           # Peso de EMAs en el score total
    "rsi":      0.9,
    "macd":     0.9,
    "patterns": 0.8,
    "bb":       0.6,
    "sr":       0.5,
    "vwap":     0.3,
    "volume":   0.2,
    "trend_tf": 0.4,           # Confirmación del TF de tendencia
}

# ─── DATOS ─────────────────────────────────────────────────────────────────────
CANDLES_PRIMARY  = 300
CANDLES_TREND    = 150
CANDLES_HIGHER   = 100

# ─── BOT ───────────────────────────────────────────────────────────────────────
LOOP_INTERVAL    = 30          # Segundos entre cada ciclo de análisis
MAX_SLIPPAGE     = 20          # Slippage máximo permitido en puntos
LOG_FILE         = "xauusd_bot.log"