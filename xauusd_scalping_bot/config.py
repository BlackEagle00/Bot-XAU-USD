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
BREAKEVEN_ATR_MULT  = 1.0      # (FALLBACK) Solo se usa si la posición NO tiene TP definido.
BE_TRIGGER_PCT      = 0.55     # Mover a BE+ cuando el precio recorra ≥ 55% del camino entrada→TP
                               # (regla 50-70%, calza bien en scalping). Baja para proteger antes.
BE_PLUS_POINTS      = 5        # "BE+": margen EXTRA (puntos) además del spread. SL queda en:
                               #   entrada ∓ (spread_actual + BE_PLUS_POINTS×point) → sale en positivo.
TRAILING_ATR_MULT   = 1.0      # Trailing ajustado: sigue de cerca al precio
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # Exige separación mínima entre entradas de la misma dirección
ANTI_DUP_ATR_MULT   = 0.75     # Distancia mínima (en ATR) entre entradas misma dirección. Antes 0.5
                               # fijo → apilaba demasiado en una caída. 0.75 separa más sin frenar
                               # tanto el ritmo del scalping. Sube a 1.0+ para separar aún más.

# ─── TRAILING PROGRESIVO (lock de ganancia) ────────────────────────────────────
# El trailing clásico (TRAILING_ATR_MULT) deja "respirar" al precio, pero cuando el
# trade ya va muy en ganancia devuelve demasiado en un retroceso: el SL queda lejos
# del precio y un "back" puede borrar casi todo el profit. El lock PROGRESIVO mueve
# el SL detrás del precio asegurando una FRACCIÓN CRECIENTE del profit abierto:
# arranca flojo (deja correr la tendencia) y se aprieta hacia ~1:1 conforme el trade
# avanza, para que un retroceso salga en POSITIVO en vez de en pérdida.
# En cada ciclo el trailing aplica el SL MÁS protector entre el ATR clásico y este lock.
USE_PROGRESSIVE_TRAIL = True    # Activar el lock progresivo de ganancia
TRAIL_LOCK_START_ATR  = 1.0     # Empezar a asegurar profit cuando éste supere 1.0×ATR (≈ 1/3 del TP)
TRAIL_LOCK_PCT_MIN    = 0.40    # Al arrancar asegura el 40% del profit (scalping → protege más rápido)
TRAIL_LOCK_PCT_MAX    = 0.90    # Tope: asegura hasta el 90% del profit (≈ 1:1) en trades maduros
TRAIL_LOCK_FULL_ATR   = 2.7     # Llega al MAX cuando el profit alcanza 2.7×ATR (≈ justo antes del TP 3.0×ATR).
                                # La fracción sube linealmente de _MIN a _MAX entre START y FULL.
                                # ¿Asegurar aún más rápido? Baja START y/o sube PCT_MIN.

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 5.5      # Umbral algo más alto: M5 genera más ruido, hay que filtrar más
ATR_VOLATILITY_MIN  = 0.8      # ATR M5 de oro ≈ $1-4; filtra mercado plano. Si NUNCA opera, bájalo;
                               # si entra en mercados muertos/laterales, súbelo (revisa el .log).
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia M5 (anti-contratendencia)
REQUIRE_MACRO_ALIGNMENT = False # En scalping NO vetamos por H1 (mataría demasiadas entradas).
                                # El H1 entra solo como SESGO suave del score (macro_tf), no como veto.
                                # Pon True si quieres que el H1 fuerte bloquee scalps en su contra.
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
    "trend_tf": 0.8,    # M15 confirma, pero pesa algo menos que en swing
    "macro_tf": 0.5,    # 🌐 Contexto H1: sesgo top-down suave (máx ±1.0, no dispara solo)
    "orderflow":   0.8, # 🟢 Presión compradora/vendedora por ticks (scalp: más peso)
    "intermarket": 0.4, # 🌐 Sesgo del índice dólar DXY (inverso; menos peso en scalp)
}

# ─── ADX — FILTRO DE FUERZA DE TENDENCIA ───────────────────────────────────────
# En mercado lateral (ADX bajo) los cruces son ruido; si ADX < umbral, no abrir.
USE_ADX_FILTER  = True
ADX_PERIOD      = 14
ADX_MIN_TREND   = 18      # scalping M5 es más ruidoso → umbral algo más bajo que swing.

# ─── ORDER-FLOW — PRESIÓN COMPRADORA/VENDEDORA POR TICKS ────────────────────────
# Proxy del "volumen de compra vs venta" con ticks recientes (en CFDs no hay volumen
# real): delta = (compras - ventas)/(compras+ventas) ∈ [-1,1]. Nudge al score.
USE_ORDERFLOW           = True
ORDERFLOW_LOOKBACK_SECS = 120     # ventana de ticks (scalping: 2 min, más reactivo)
ORDERFLOW_MIN_TICKS     = 50

# ─── INTER-MERCADO — ÍNDICE DÓLAR (DXY) ─────────────────────────────────────────
# El oro es INVERSO al dólar. ⚠ Verifica el símbolo del índice dólar en tu broker;
#    XM suele usar "USDX". Si no existe, el factor se desactiva solo (sin error).
USE_INTERMARKET     = True
INTERMARKET_SYMBOL  = "USDX-SEP26"  # Índice dólar (XM, futuro trimestral). Vence ~2026-09-11 → al
                                    # rolar, cambia el sufijo al siguiente contrato (p.ej. USDX-DEC26).
INTERMARKET_INVERSE = True
INTERMARKET_TF      = mt5.TIMEFRAME_H1   # TF del DXY (scalping: H1)
INTERMARKET_CANDLES = 200

# ─── FILTRO DE NOTICIAS — CALENDARIO ECONÓMICO ──────────────────────────────────
# Bloquea abrir trades alrededor de eventos de alto impacto (NFP, CPI, FOMC...).
# JSON semanal gratuito de ForexFactory; si no hay internet, NO bloquea (fail-open).
USE_NEWS_FILTER          = True
NEWS_CURRENCIES          = ["USD"]       # divisas que afectan al oro
NEWS_IMPACTS             = ["High"]
NEWS_BLACKOUT_BEFORE_MIN = 15            # scalping: ventana más corta
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
TELEGRAM_PREFIX    = "[GOLD scalp]"   # etiqueta para distinguir este bot en el chat

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

# ─── MOTOR COMPARTIDO (bot_engine) — claves añadidas al unificar el motor ───────
ORDER_COMMENT_PREFIX = "XAU"                          # prefijo del comentario de orden MT5 (≤31 chars)
BOT_LABEL            = "XAU/USD (Oro) Scalping Bot"   # texto del banner de arranque
# Contexto macro (en scalp el Oro lo usa como sesgo H1, sin veto — REQUIRE_MACRO_ALIGNMENT=False arriba):
USE_MACRO_CONTEXT    = True
MACRO_TF_LABEL       = "H1"
# S/R parametrizado (reproduce exactamente el comportamiento previo del Oro):
SR_CLUSTER_ATR_MULT  = 0.30   # tolerancia de agrupación = 0.30×ATR
SR_TOLERANCE_FLOOR   = 0.5    # piso en $ (solo Oro) → max(atr*0.30, 0.5)
PSYCH_LEVEL_STEP     = 5.0    # niveles psicológicos cada $5
PSYCH_LEVEL_COUNT    = 5      # nº de niveles psicológicos a cada lado del precio
