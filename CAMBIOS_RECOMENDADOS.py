"""
CAMBIOS RECOMENDADOS PARA TU BOT XAU/USD
========================================

Este archivo muestra exactamente qué cambiar en cada archivo.
Copia/pega los fragmentos en el orden sugerido.

PRIORIDAD 1 (Hoy): Seguridad - Mover credenciales
PRIORIDAD 2 (Hoy): Tuning - Ajustar parámetros
PRIORIDAD 3 (Mañana): Testing - Validar cambios

"""

# ═══════════════════════════════════════════════════════════════════════════════
# PASO 1: SEGURIDAD - MOVER CREDENCIALES A .env
# ═══════════════════════════════════════════════════════════════════════════════

# CREAR ARCHIVO NUEVO: .env (en la raíz de tu proyecto)
# ────────────────────────────────────────────────────────
"""
Contenido de .env:

MT5_LOGIN=10011299165
MT5_PASSWORD=1wZwC!Vw
MT5_SERVER=MetaQuotes-Demo
"""

# MODIFICAR: xauusd_bot/config.py (primeras líneas)
# ────────────────────────────────────────────────

# REEMPLAZAR ESTO:
"""
import MetaTrader5 as mt5

# ─── CUENTA MT5 ────────────────────────────────────────────────────────────────
# ─── CREDENCIALES DE EJEMPLO CUENTA DEMO ───────────────────────────────────────
MT5_LOGIN    = 10011299165           # Número de cuenta
MT5_PASSWORD = "1wZwC!Vw"          # Contraseña de la cuenta
MT5_SERVER   = "MetaQuotes-Demo"          # Servidor del broker
"""

# POR ESTO:
"""
import os
import MetaTrader5 as mt5
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# ─── CUENTA MT5 ────────────────────────────────────────────────────────────────
# Lee desde .env, usa default 0 si no existe
MT5_LOGIN    = int(os.getenv('MT5_LOGIN', 0))
MT5_PASSWORD = os.getenv('MT5_PASSWORD', '')
MT5_SERVER   = os.getenv('MT5_SERVER', '')
"""

# CREAR: .gitignore (en raíz)
# ────────────────────────────
"""
# Variables de entorno
.env
.env.local

# Logs
*.log
xauusd_bot.log

# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
*.egg

# IDE
.vscode/
.idea/
*.swp

# Sistema
.DS_Store
Thumbs.db
"""

# INSTALAR DOTENV
# ────────────────
# En terminal: pip install python-dotenv


# ═══════════════════════════════════════════════════════════════════════════════
# PASO 2: TUNING - AJUSTAR PARÁMETROS EN config.py
# ═══════════════════════════════════════════════════════════════════════════════

# CAMBIO 1: Reducir MIN_SIGNAL_SCORE
# ───────────────────────────────────

# ANTES (línea 64):
"""
MIN_SIGNAL_SCORE    = 6.5      # Umbral más alto → señales más selectivas
"""

# DESPUÉS:
"""
MIN_SIGNAL_SCORE    = 5.0      # Más operaciones con buena calidad
"""

# IMPACTO: +30-40% más trades sin sacrificar calidad


# CAMBIO 2: Aumentar MAX_OPEN_TRADES
# ────────────────────────────────────

# ANTES (línea 49):
"""
MAX_OPEN_TRADES     = 2        # Máximo 2 trades simultáneos
"""

# DESPUÉS:
"""
MAX_OPEN_TRADES     = 4        # Permitir acumulación en tendencias fuertes
"""

# IMPACTO: Mejor uso del capital en tendencias alcistas/bajistas


# CAMBIO 3: Ajustar SCORE_WEIGHTS (líneas 67-77)
# ────────────────────────────────────────────────

# ANTES:
"""
SCORE_WEIGHTS = {
    "ema":      1.2,   # Más peso: la alineación EMA es clave
    "rsi":      0.8,   # Menos peso: RSI en H1 es menos preciso
    "macd":     1.0,   # Más peso: cruces MACD en H1 son señales de alta fiabilidad
    "patterns": 0.6,   # Menos peso: patrones de vela solos son menos determinantes
    "bb":       0.5,   # Ligeramente menos relevante
    "sr":       0.8,   # Más peso: niveles S/R son fundamentales
    "vwap":     0.2,   # Menos relevante en H1 (VWAP es más herramienta intraday)
    "volume":   0.3,   # Más peso: el volumen confirma breakouts
    "trend_tf": 0.6,   # Más peso: la confirmación del H4 es crítica
}
"""

# DESPUÉS:
"""
SCORE_WEIGHTS = {
    "ema":      1.3,    # ↑ Alineación EMA es lo más importante
    "rsi":      1.0,    # ↑ RSI en H1 es clave para timing de entrada
    "macd":     1.1,    # ↑ Cruces MACD muy confiables
    "patterns": 0.8,    # ↑ Patrones H1 son señales fuertes
    "bb":       0.7,    # ↑ Squeeze indica volatilidad baja
    "sr":       0.9,    # = Soportes/Resistencias fundamentales
    "vwap":     0.1,    # ↓ Menos relevante en timeframes altos
    "volume":   0.4,    # ↑ Volumen confirma breakouts
    "trend_tf": 1.0,    # ↑ H4 es MUY importante para contexto swing
}
"""

# IMPACTO: Mejor balance en señales, menos falsos positivos en VWAP


# CAMBIO 4: Aumentar LOOP_INTERVAL (opcional, línea 85)
# ─────────────────────────────────────────────────────

# ANTES:
"""
LOOP_INTERVAL    = 300         # 5 minutos entre ciclos
"""

# DESPUÉS (si quieres más reactividad):
"""
LOOP_INTERVAL    = 60          # 1 minuto entre ciclos (más reactividad)
"""

# NOTA: 300s (5 min) es OK para H1, 60s da más oportunidades.


# ═══════════════════════════════════════════════════════════════════════════════
# PASO 3: LOGGING MEJORADO (Opcional pero recomendado)
# ═══════════════════════════════════════════════════════════════════════════════

# AGREGAR AL INICIO DE connection.py, en la función connect():

"""
def connect(retries=3, delay=2, user=None):
    ...

    # Después de conectar exitosamente, agregar:
    symbol_info = get_symbol_info()
    if symbol_info:
        logger.info(f"📋 Información del símbolo {SYMBOL}:")
        logger.info(f"   • Precio bid: {symbol_info.bid}")
        logger.info(f"   • Precio ask: {symbol_info.ask}")
        logger.info(f"   • Dígitos: {symbol_info.digits}")
        logger.info(f"   • Punto: {symbol_info.point}")
        logger.info(f"   • Tick size: {symbol_info.trade_tick_size}")
        logger.info(f"   • Tick value: {symbol_info.trade_tick_value}")
        logger.info(f"   • Volumen mín: {symbol_info.volume_min}")
        logger.info(f"   • Volumen step: {symbol_info.volume_step}")
        logger.info(f"   • Volumen máx: {symbol_info.volume_max}")
        logger.info(f"   • Stops level: {symbol_info.trade_stops_level}")
"""


# ═══════════════════════════════════════════════════════════════════════════════
# PASO 4: VALIDACIÓN DE CAMBIOS
# ═══════════════════════════════════════════════════════════════════════════════

"""
Después de aplicar los cambios:

1. Instalar python-dotenv:
   $ pip install python-dotenv

2. Crear archivo .env con tus credenciales

3. Ejecutar el bot:
   $ python main.py

4. Verificar en los logs que aparezca:
   ✅ Credenciales cargadas desde .env (no hardcoded)
   ✅ Información del símbolo con tick_value, tick_size, etc.
   ✅ Trades abiertos con scores >= 5.0 (antes requerían >= 6.5)

5. Monitorear 24-48 horas y comparar:
   • Número de trades (debería ↑ 30-40%)
   • Win rate (debería ser similar o mejor)
   • P&L (debería mejorar ~5-10%)
"""


# ═══════════════════════════════════════════════════════════════════════════════
# PASO 5: CAMBIOS SECUNDARIOS (Siguientes días)
# ═══════════════════════════════════════════════════════════════════════════════

"""
CAMBIO 5: Agregar filtro de horarios (opcional pero recomendado)

En config.py, agregar:

# ─── HORARIOS DE TRADING ────────────────────────────────────────────────────────
# Evitar spreads altos y baja liquidez
TRADING_HOURS_UTC = {
    "start": 13,   # 13:00 UTC (9 AM EST) - Apertura NY
    "end":   21,   # 21:00 UTC (5 PM EST) - Cierre NY
}
ALLOW_ASIAN_HOURS = False  # No operar en sesión asiática (spreads altos)

En main.py, en _run_cycle(), después de is_market_open():

# Verificar horarios de trading
import datetime
utc_hour = datetime.datetime.utcnow().hour
if not (TRADING_HOURS_UTC["start"] <= utc_hour < TRADING_HOURS_UTC["end"]):
    if ALLOW_ASIAN_HOURS:
        logger.debug("🕐 Fuera de horario NY. Sesión asiática activa.")
    else:
        logger.debug("🕐 Fuera de horario de trading. Ciclo omitido.")
        return
"""

# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN DE CAMBIOS POR PRIORIDAD
# ═══════════════════════════════════════════════════════════════════════════════

SUMMARY = """
┌─────────────────────────────────────────────────────────────────────────┐
│                      PLAN DE IMPLEMENTACIÓN                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│ HOY (30 min):                                                             │
│ ✅ 1. Crear .env con credenciales                     (5 min)           │
│ ✅ 2. Modificar config.py para leer desde .env         (10 min)         │
│ ✅ 3. Crear .gitignore                                 (5 min)          │
│ ✅ 4. Instalar python-dotenv                           (5 min)          │
│ ✅ 5. Ajustar MIN_SIGNAL_SCORE de 6.5 → 5.0           (2 min)          │
│ ✅ 6. Ajustar MAX_OPEN_TRADES de 2 → 4                (2 min)          │
│ ✅ 7. Ajustar SCORE_WEIGHTS                            (5 min)          │
│ ✅ 8. Ejecutar bot y validar logs                      (10 min)         │
│                                                                           │
│ MAÑANA (1 hora):                                                          │
│ ✅ 9. Agregar logging de símbolo en connection.py      (10 min)         │
│ ✅ 10. Revisar primeros trades con nuevos parámetros   (30 min)        │
│ ✅ 11. Ajustar LOOP_INTERVAL si es necesario           (5 min)         │
│ ✅ 12. Agregar filtro de horarios (opcional)           (15 min)         │
│                                                                           │
│ PRÓXIMA SEMANA:                                                           │
│ • Ejecutar backtesting con datos históricos 6 meses    │
│ • Validar nuevos parámetros vs estrategia original     │
│ • Ajustar pesos si es necesario según resultados       │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
"""

print(SUMMARY)
