"""
╔══════════════════════════════════════════════════════════════╗
║       XAU/USD (Oro) Scalping Bot — Configuración Central     ║
╚══════════════════════════════════════════════════════════════╝
Edita este archivo antes de ejecutar el bot.
Modo: Scalping (M5/M15/H1) — operaciones de minutos a 1-2 horas.

⚠ REALIDAD DEL ORO EN SCALPING:
  El oro tiene un spread estructuralmente ALTO (~$0.30-0.60 en XM). En scalping,
  con TP pequeños, ese spread se come una parte importante de cada operación.
  Por eso el SL/TP aquí es AJUSTADO (no los rangos amplios del swing) pero el TP
  no es tan corto como en EUR/USD: se deja un R:R sólido para que el spread no
  destruya la estadística. Ajusta MAX_SPREAD_POINTS si tu broker tiene más spread.
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
SYMBOL       = "GOLD"      # Puede variar por broker: GOLD, XAUUSD, XAUUSDm.
MAGIC_NUMBER = 20260621    # ID único — distinto a Oro swing (…618) y a los EUR/USD (…619/620)

# ─── TEMPORALIDADES ────────────────────────────────────────────────────────────
PRIMARY_TF   = mt5.TIMEFRAME_M5     # TF principal de análisis (M5)
TREND_TF     = mt5.TIMEFRAME_M15    # TF de confirmación de tendencia (M15)
HIGHER_TF    = mt5.TIMEFRAME_H1     # Contexto de tendencia mayor (H1) — sesgo top-down
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
VWAP_PERIOD  = 288         # 288 velas M5 = VWAP rodante de 24 horas
SR_LOOKBACK  = 14          # Lookback más corto para pivots S/R locales en M5
SR_LEVELS    = 5           # Menos niveles, más cercanos al precio (scalping)
SR_24H_CANDLES = 288       # 288 velas M5 = 24h (rango del día en indicators.py)

# ─── GESTIÓN DE RIESGO ─────────────────────────────────────────────────────────
RISK_PER_TRADE      = 0.01     # 1% del balance por operación
MAX_OPEN_TRADES     = 3        # Con REQUIRE_TREND_ALIGNMENT todas van en la misma dirección
MAX_DAILY_LOSS_PCT  = 0.05     # 5% pérdida diaria → detener
# ── SL/TP realistas para scalping de ORO ──────────────────────────────────────
# El ATR de M5 en oro es pequeño ($1-4). SL ajustado, pero TP con R:R sólido (2:1)
# para que el spread del oro no destruya la estadística (a diferencia de EUR/USD,
# donde el TP puede ser más corto porque el spread es ínfimo).
SL_ATR_MULT         = 1.5      # SL = 1.5×ATR (≈ $1.5-6 según volatilidad)
TP_ATR_MULT         = 3.0      # TP = 3.0×ATR → R:R teórico 2.0:1
MIN_RR              = 1.8      # R:R real mínimo (permite leve deformación del broker)
MIN_LOT             = 0.01     # Lote mínimo absoluto
MAX_LOT             = 3.0      # Lote máximo absoluto
BREAKEVEN_ATR_MULT  = 1.0      # Mover SL a BE rápido (proteger capital antes en scalping)
TRAILING_ATR_MULT   = 1.0      # Trailing ajustado: sigue de cerca al precio
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # No acumular en el mismo nivel de precio
                               # True  = exige al menos 0.5×ATR de distancia entre entradas

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 5.5      # Umbral algo más alto: M5 genera más ruido, hay que filtrar más
ATR_VOLATILITY_MIN  = 0.8      # ATR M5 de oro ≈ $1-4; filtra mercado plano. Si NUNCA opera, bájalo;
                               # si entra en mercados muertos/laterales, súbelo (revisa el .log).
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia M5 (anti-contratendencia)
REQUIRE_MACRO_ALIGNMENT = False # En scalping NO vetamos por H1 (mataría demasiadas entradas).
                                # El H1 entra solo como SESGO suave del score (macro_tf), no como veto.
                                # Pon True si quieres que el H1 fuerte bloquee scalps en su contra.
SCORE_WEIGHTS = {
    "ema":      1.3,    # ↑ Alineación EMA sigue siendo lo más importante
    "rsi":      1.0,    # ↑ RSI en M5 es clave para timing de entrada
    "macd":     1.1,    # ↑ Cruces MACD confiables como confirmación de momentum
    "patterns": 0.8,    # ↑ Patrones de vela en M5 (más ruidosos, pero útiles)
    "bb":       0.7,    # ↑ Squeeze indica volatilidad baja
    "sr":       0.9,    # = Soportes/Resistencias fundamentales
    "vwap":     0.3,    # ↑ Más relevante en scalping (precio justo intradía)
    "volume":   0.4,    # ↑ Volumen confirma breakouts
    "trend_tf": 0.8,    # M15 confirma, pero pesa algo menos que en swing
    "macro_tf": 0.5,    # 🌐 Contexto H1: sesgo top-down suave (máx ±1.0, no dispara solo)
}

# ─── DATOS ─────────────────────────────────────────────────────────────────────
CANDLES_PRIMARY  = 1500   # 1500 velas M5 ≈ 5.2 días (suficiente para EMA200 estable)
CANDLES_TREND    = 500    # 500 velas M15 ≈ 5.2 días
CANDLES_HIGHER   = 500    # 500 velas H1 ≈ 20 días de contexto

# ─── BOT ───────────────────────────────────────────────────────────────────────
LOOP_INTERVAL    = 15           # 15s entre ciclos: reaccionar rápido dentro de la vela M5
MAX_SLIPPAGE     = 15            # Menor tolerancia: en scalping el slippage pesa más sobre el TP
MAX_SPREAD_POINTS = 70          # Spread máx (en puntos). El oro en XM ≈ 50-70 normal; antes el swing
                                # necesitó 80 para operar. 70 es algo más exigente (protege el TP corto)
                                # sin bloquear todo. Si NUNCA opera, súbelo; si quieres entradas más
                                # baratas, bájalo (pero el oro rara vez baja de ~50).
LOG_FILE         = "xauusd_scalping_bot.log"
