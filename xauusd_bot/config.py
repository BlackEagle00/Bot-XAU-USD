"""
╔══════════════════════════════════════════════════════════════╗
║        XAU/USD Scalping Bot — Configuración Central         ║
╚══════════════════════════════════════════════════════════════╝
Edita este archivo antes de ejecutar el bot.
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
MAX_OPEN_TRADES     = 5        # Trades simultáneos máximos
MAX_DAILY_LOSS_PCT  = 0.05     # 5% de pérdida diaria → detener bot
SL_ATR_MULT         = 1.5      # Stop Loss = SL_ATR_MULT × ATR
TP_ATR_MULT         = 2.5      # Take Profit = TP_ATR_MULT × ATR
MIN_RR              = 1.5      # Mínimo Risk/Reward requerido
MIN_LOT             = 0.01     # Lote mínimo absoluto
MAX_LOT             = 5.0      # Lote máximo absoluto
BREAKEVEN_MODE      = "pct_tp" # "pct_tp"     → Regla matemática: dispara según % recorrido al TP
                               # "structure"  → Regla técnica: vela de ruptura + micro-fractal en M1
BREAKEVEN_TRIGGER_PCT_OF_TP = 0.60
                               # Mover a BE cuando el profit alcance este % de la distancia
                               # entre la entrada y el TP de la posición (regla 50-70%).
                               # 0.60 = espera el 60% del camino antes de proteger capital.
                               # Usa el TP REAL guardado en la posición (no el ATR actual),
                               # así el disparo no varía si la volatilidad cambia después de abrir.
BREAKEVEN_ATR_MULT  = 1.0      # Fallback: solo se usa si la posición no tiene TP definido
                               # (ej. trade abierto manualmente sin TP)
BREAKEVEN_BUFFER_USD = 0.50    # "BE+": margen en USD que se SUMA/RESTA al precio de entrada
                               # para no salir exactamente en 0 — cubre spread + comisión.
                               # En XAUUSD con cotización a 2 decimales, 1 "pip" = $0.01,
                               # así que 0.50 equivale a 50 pips de margen.
                               # Ajusta según el spread+comisión real de tu broker:
                               #   Spread bajo (ECN):        0.10 – 0.30  (10–30 pips)
                               #   Spread/comisión estándar: 0.30 – 0.60  (30–60 pips)
                               #   Swing (H1+):               1.50 – 3.00
ESTIMATED_COMMISSION_USD = 7.0 # Comisión estimada round-trip por lote completo (ajusta a tu broker)
                               # Se usa para advertir si el buffer no cubre el costo real
# ── Regla técnica (BREAKEVEN_MODE = "structure") ───────────────────────────────
MICRO_TF                     = mt5.TIMEFRAME_M1
                               # Temporalidad usada para detectar velas de ruptura y micro-fractales
MICRO_FRACTAL_LOOKBACK       = 2
                               # Velas a cada lado para confirmar un micro-fractal en M1
                               # (mínimo/máximo rodeado de 2 velas más altas/bajas a cada lado)
BREAKOUT_CANDLE_BODY_ATR_MULT = 0.4
                               # Cuerpo mínimo de la vela de confirmación, en múltiplos de ATR(M1)
                               # Una vela con cuerpo < 0.4×ATR(M1) se considera indecisión, no ruptura
TRAILING_ATR_MULT   = 0.8      # Trailing stop: seguir a precio con X × ATR de distancia
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
SWING_MODE          = False    # False = scalping (M5, 30s, sin filtro de sesión)
                               # True  = swing/posicional (H1, 900s, solo Londres+NY)
 
# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 4.5      # Puntuación mínima para abrir trade (máx ≈ ±12)
ATR_VOLATILITY_MIN  = 0.3      # No operar si ATR < este valor (mercado plano)
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