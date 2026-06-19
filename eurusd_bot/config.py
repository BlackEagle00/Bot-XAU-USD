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
BREAKEVEN_ATR_MULT  = 0.9      # Mover SL a BE cuando profit >= 0.9×ATR (escalado junto con el SL)
TRAILING_ATR_MULT   = 1.5      # Trailing más cercano (escalado junto con el SL)
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # En swing no acumular: 1 posición por dirección
                               # True  = exige al menos 0.5×ATR de distancia entre entradas

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 5.0      # Umbral optimizado → más operaciones sin sacrificar calidad (+30-40%)
ATR_VOLATILITY_MIN  = 0.0004   # ATR H1 de EURUSD ≈ 0.0005–0.0015; filtrar mercado plano
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia H1 (anti-contratendencia)
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
}

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
