"""
╔══════════════════════════════════════════════════════════════╗
║       XAU/USD Swing Trading Bot — Configuración Central     ║
╚══════════════════════════════════════════════════════════════╝
Modo: Swing real (H4/D1/W1) — operaciones de días. Restaurado 2026-10-25 (auditoría): el bot llevaba
desde el 2026-10-23 una copia del scalping en H1 (operaciones de horas), que no es swing.
Capital mínimo: con 0.01 lote cada $1 del oro vale $1, y el SL de 2×ATR H4 (ATR ≈ $32 hoy) cuesta ≈ $64.
Con menos capital del que permite MAX_RISK_MIN_LOT el bot NO abre y avisa "siguiente lote con capital ≥ X"
(el apalancamiento 1:500 solo baja el margen —≈ $8 por 0.01 lote—, no lo que se pierde en el stop).
Para cuentas desde 50 USD están el scalping y el grid.
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
SYMBOL       = "XAUUSD"    # Puede variar por broker: GOLD, XAUUSD.
MAGIC_NUMBER = 20260618    # ID único para identificar los trades del bot

# ─── TEMPORALIDADES ────────────────────────────────────────────────────────────
PRIMARY_TF   = mt5.TIMEFRAME_H4    # TF principal (H4). Backtest 2023-26: H4 PF 1.78 vs H1 PF 1.17
TREND_TF     = mt5.TIMEFRAME_D1    # TF de confirmación de tendencia (D1)
HIGHER_TF    = mt5.TIMEFRAME_W1    # Contexto macro semanal (W1)
TF_LABELS    = "H4/D1/W1"         # Etiqueta legible para logs

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
VWAP_PERIOD  = 6           # 6 velas H4 = VWAP rodante de 24 horas
SR_LOOKBACK  = 20          # Mayor lookback para pivots S/R en H1
SR_LEVELS    = 7           # Más niveles S/R para análisis swing
SR_24H_CANDLES = 6         # 6 velas H4 = 24h (rango del día en indicators.py)

# ─── GESTIÓN DE RIESGO ─────────────────────────────────────────────────────────
RISK_PER_TRADE      = 0.01     # 1% del balance por operación
MAX_OPEN_TRADES     = 5        # Máx 5 simultáneos: con REQUIRE_TREND_ALIGNMENT todos van en la misma
                               # dirección → 5% de riesgo correlacionado en vez de 4% (más balanceado)
MAX_DAILY_LOSS_PCT  = 0.1     # 10% pérdida diaria → detener
SL_ATR_MULT         = 2.0      # SL más amplio para tolerar movimientos normales de H1
TP_ATR_MULT         = 4.5      # TP amplio → R:R de 2.25:1
MIN_RR              = 2.0      # R:R mínimo más exigente en swing
MIN_LOT             = 0.01     # Lote mínimo absoluto
MAX_LOT             = 3.0      # Lote máximo absoluto
BREAKEVEN_ATR_MULT  = 1.5      # (FALLBACK) Solo se usa si la posición NO tiene TP definido.
BE_TRIGGER_PCT      = 0.40     # Mover a BE+ cuando el precio recorra ≥ 40% del camino entrada→TP.
                               # En swing el TP es amplio, así que 40% protege la ganancia a tiempo
                               # sin blindar tan pronto que un retroceso normal te saque. Baja a 0.35
                               # para proteger aún antes (~$85); sube hacia 0.5-0.6 para dejar correr más.
BE_PLUS_POINTS      = 5        # "BE+": margen EXTRA (en puntos) ADEMÁS del spread, para salir en
                               # positivo y cubrir costos. El SL de BE se coloca en:
                               #   entrada ∓ (spread_actual + BE_PLUS_POINTS×point)  → nunca en la
                               # entrada exacta, siempre 1 poco a tu favor (cubre el spread del oro).
TRAILING_ATR_MULT   = 2.5      # Trailing amplio para no cortar tendencias swing
USE_TRAILING_STOP   = True     # Activar trailing stop
USE_BREAKEVEN       = True     # Activar break-even automático
USE_ANTI_DUPLICATE  = True     # Exige separación mínima entre entradas de la misma dirección
ANTI_DUP_ATR_MULT   = 1.0      # Distancia mínima (en ATR) entre entradas de la misma dirección.
                               # Antes era 0.5 fijo → apilaba demasiadas ventas pegadas en una caída,
                               # y todas morían juntas en el rebote. 1.0 = entradas más separadas,
                               # menos operaciones agolpadas. Sube a 1.5-2.0 para separar aún más.

# ─── TRAILING PROGRESIVO (lock de ganancia) ────────────────────────────────────
# El trailing clásico (TRAILING_ATR_MULT) deja "respirar" al precio, pero cuando el
# trade ya va muy en ganancia devuelve demasiado en un retroceso: el SL queda lejos
# del precio y un "back" puede borrar casi todo el profit. El lock PROGRESIVO mueve
# el SL detrás del precio asegurando una FRACCIÓN CRECIENTE del profit abierto:
# arranca flojo (deja correr la tendencia) y se aprieta hacia ~1:1 conforme el trade
# avanza, para que un retroceso salga en POSITIVO en vez de en pérdida.
# En cada ciclo el trailing aplica el SL MÁS protector entre el ATR clásico y este lock.
USE_PROGRESSIVE_TRAIL = True    # Activar el lock progresivo de ganancia
TRAIL_LOCK_START_ATR  = 1.5     # Empezar a asegurar profit cuando éste supere 1.5×ATR (antes deja correr)
TRAIL_LOCK_PCT_MIN    = 0.35    # Al arrancar asegura el 35% del profit abierto (aún deja respirar)
TRAIL_LOCK_PCT_MAX    = 0.90    # Tope: asegura hasta el 90% del profit (≈ 1:1) en trades maduros
TRAIL_LOCK_FULL_ATR   = 4.0     # El lock alcanza el MAX cuando el profit llega a 4.0×ATR (≈ justo
                                # antes del TP de 4.5×ATR → blinda ~90% pegado al objetivo).
                                # La fracción sube linealmente de _MIN a _MAX entre START y FULL.
                                # ¿Quieres asegurar MÁS rápido? Baja START y/o sube PCT_MIN.
                                # ¿1:1 estricto siempre? Sube PCT_MIN y PCT_MAX hacia 0.90-0.95.

# ─── SEÑALES ───────────────────────────────────────────────────────────────────
MIN_SIGNAL_SCORE    = 5.0      # Umbral optimizado → más operaciones sin sacrificar calidad (+30-40%)
ATR_VOLATILITY_MIN  = 2.0      # ATR H4 de XAUUSD ≈ $20–40; filtrar mercado plano
REQUIRE_TREND_ALIGNMENT = True  # Solo operar a favor de la tendencia H4 (anti-contratendencia)
REQUIRE_MACRO_ALIGNMENT = True  # Filtro W1: si el semanal marca tendencia FUERTE (EMAs en cascada),
                                # no abrir operaciones en su contra (evita trampas de pullback).
# Anti-agotamiento: no abrir NUEVAS entradas en extremos de RSI (donde el movimiento
# suele agotarse y revertir). Evita "vender en el suelo" / "comprar en el techo" —
# justo lo que castiga al apilar ventas de tendencia hasta el fondo antes de un rebote.
RSI_NO_SELL_BELOW   = 32      # No abrir SELL si el RSI H4 ≤ 32 (sobrevendido → posible suelo)
RSI_NO_BUY_ABOVE    = 68      # No abrir BUY  si el RSI H4 ≥ 68 (sobrecomprado → posible techo)
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
    "macro_tf": 0.8,    # 🌐 Contexto macro D1: sesga el score a favor del diario
                        #    (nudge, no dispara solo; máx ±1.6 < umbral 5.0)
    "orderflow":   0.5, # 🟢 Presión compradora/vendedora por ticks (nudge, máx ±0.5)
    "intermarket": 0.8, # 🌐 Sesgo del índice dólar DXY (inverso; nudge, máx ±1.2)
}

# ─── ADX — FILTRO DE FUERZA DE TENDENCIA ───────────────────────────────────────
# El bot es seguidor de tendencia. En mercado lateral (ADX bajo) los cruces de EMA
# son ruido y terminan en SL. Si ADX < umbral, no se abren NUEVAS operaciones.
USE_ADX_FILTER  = True
ADX_PERIOD      = 14
ADX_MIN_TREND   = 20      # < 20 = lateral/chop (swing). Sube a 25 para exigir tendencia más clara.

# ─── ORDER-FLOW — PRESIÓN COMPRADORA/VENDEDORA POR TICKS ────────────────────────
# Aproxima el "volumen de compra vs venta" con los ticks recientes (en CFDs no hay
# volumen real): delta = (compras - ventas)/(compras+ventas) ∈ [-1,1]. Nudge al score.
USE_ORDERFLOW           = True
ORDERFLOW_LOOKBACK_SECS = 300     # ventana de ticks a analizar (swing: 5 min)
ORDERFLOW_MIN_TICKS     = 50      # mínimo de ticks para fiarse del cálculo

# ─── INTER-MERCADO — ÍNDICE DÓLAR (DXY) ─────────────────────────────────────────
# El oro es INVERSO al dólar: DXY bajando = viento de cola alcista para el oro.
# ⚠ Verifica el nombre del símbolo del índice dólar en tu broker (Market Watch).
#    XM suele usar "USDX". Si no existe, el factor se desactiva solo (sin error).
USE_INTERMARKET     = False         # Apagado: "USDX-SEP26" venció y ya era un no-op en vivo; el backtest no
INTERMARKET_SYMBOL  = "USDX"        # lo simula. Este bróker lista "USDX": encenderlo exige medirlo antes.
INTERMARKET_INVERSE = True              # oro/EUR son inversos al USD
INTERMARKET_TF      = mt5.TIMEFRAME_H4  # TF para medir la tendencia del DXY (swing)
INTERMARKET_CANDLES = 200

# ─── FILTRO DE NOTICIAS — CALENDARIO ECONÓMICO ──────────────────────────────────
# Bloquea abrir trades alrededor de eventos de alto impacto (NFP, CPI, FOMC...).
# Usa el JSON semanal gratuito de ForexFactory; si no hay internet, NO bloquea
# (fail-open) para no congelar el bot. Pon NEWS_FAIL_OPEN=False para ser estricto.
USE_NEWS_FILTER          = True
NEWS_CURRENCIES          = ["USD"]      # divisas que afectan al oro (USD). EURUSD: ["USD","EUR"]
NEWS_IMPACTS             = ["High"]     # niveles a vetar. Añade "Medium" para más cautela.
NEWS_BLACKOUT_BEFORE_MIN = 30           # no abrir desde 30 min ANTES del evento
NEWS_BLACKOUT_AFTER_MIN  = 30           # ni hasta 30 min DESPUÉS
NEWS_FAIL_OPEN           = True         # si el calendario no carga, permitir operar (solo avisa)

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
TELEGRAM_PREFIX    = "[GOLD swing]"   # etiqueta para distinguir este bot en el chat

# ─── DATOS ─────────────────────────────────────────────────────────────────────
CANDLES_PRIMARY  = 500    # 500 velas H4 ≈ 4 meses de historia
CANDLES_TREND    = 200    # 200 velas D1 ≈ 9 meses
CANDLES_HIGHER   = 365    # 365 velas W1 ≈ 7 años de contexto macro

# ─── BOT ───────────────────────────────────────────────────────────────────────
LOOP_INTERVAL    = 60          # 1 minuto entre ciclos (más reactividad, mejor capturas de entrada)
ENTRY_WINDOW_MIN = 15           # entrar solo en los 15 min tras el cierre de la vela H4 de la señal, 1 vez por vela (= backtest)
ENTRY_RETRY_MIN  = 60           # pedido del usuario 2026-10-26: y en los 15 min tras cada cierre H1 mientras la señal H4 siga vigente (sin backtest)
LATE_ENTRY_SCORE = 7.5          # pedido del usuario: señal muy fuerte (1.5× el mínimo de 5.0) entra aunque la vela ya arrancó (sin backtest)
MAX_SLIPPAGE     = 30          # Mayor tolerancia al slippage en swing
MAX_SPREAD_POINTS = 80         # Spread máx permitido (en puntos) para operar. Gold XM ≈ 30-50 normal;
                               # antes estaba fijo en 50 → bloqueaba TODOS los ciclos. Sube si tu broker
                               # tiene spread mayor; baja para ser más exigente con los costos.
LOG_FILE         = "xauusd_bot.log"

# ─── MOTOR COMPARTIDO (bot_engine) — claves añadidas al unificar el motor ───────
# Identidad / banner de esta variante:
ORDER_COMMENT_PREFIX = "XAU"                         # prefijo del comentario de orden MT5 (≤31 chars)
BOT_LABEL            = "XAU/USD Swing Trading Bot"    # texto del banner de arranque
# Contexto macro (el Oro SÍ lo usa; MACRO_TF_LABEL = etiqueta del TF superior en logs):
USE_MACRO_CONTEXT    = True
MACRO_TF_LABEL       = "W1"
# Ajustes del backtest de 3 años (backtesting/engine_backtest.py, fuera de muestra):
REQUIRE_MACRO_FOR_SELL = True   # ventas solo con W1 bajista: PF 1.69 → 1.78 (las ventas contra el macro perdían)
USE_ML_FILTER          = True   # HGB walk-forward 2026-10-25: OOS 1 000 USD PF 1.03 → 1.31, acierto 82 %, DD 24 % (τ 0.675, SL 2.0 / TP 1.5)
ML_FILTER_MAX_CAPITAL  = 500    # pedido del usuario 2026-10-26: con capital ≥ 500 USD sin filtro ML (backtest _bal: 500 PF 0.97 con ML vs 1.31 sin; 50/100 mejor con ML)
# S/R parametrizado (reproduce exactamente el comportamiento previo del Oro):
SR_CLUSTER_ATR_MULT  = 0.30   # tolerancia de agrupación = 0.30×ATR
SR_TOLERANCE_FLOOR   = 0.5    # piso en $ (solo Oro) → max(atr*0.30, 0.5)
PSYCH_LEVEL_STEP     = 5.0    # niveles psicológicos cada $5 (2040, 2045, …)
PSYCH_LEVEL_COUNT    = 5      # nº de niveles psicológicos a cada lado del precio

# ─── CAPITAL MÍNIMO (cuentas pequeñas) ──────────────────────────────────────────
# Sin ajuste micro: acercar el SL lo mete en el ruido (lo midieron todas las suites). El lote mínimo se
# permite mientras arriesgue ≤ MAX_RISK_MIN_LOT; si no, el bot no abre e informa el capital necesario.
MICRO_SL_FIT      = False
MICRO_MIN_SL_ATR  = 0.5
MAX_RISK_MIN_LOT  = 0.10
ENFORCE_CAPITAL_LEVEL = False   # 2026-10-26, pedido del usuario: nivel de cuenta y capital mínimo solo informan (log + panel);
                                # con poco capital opera al lote mínimo marcado "riesgo elevado". Hoy 0.01 lote ≈ 64 USD de stop.
MAX_DD_PCT        = 0.30     # equity −30 % desde su máximo → no abre más (corte total)
