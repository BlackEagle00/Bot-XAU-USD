"""
Gestión de conexión con MetaTrader 5.
Maneja inicialización, login, validación de símbolo y reconexión.
"""
import time
import MetaTrader5 as mt5
from logger_config import logger
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL


def connect(retries: int = 3, delay: int = 5) -> bool:
    """
    Inicializa el terminal MT5 y realiza login.
    Soporta hasta `retries` intentos con `delay` segundos entre ellos.
    """
    for attempt in range(1, retries + 1):
        logger.info(f"🔌 Intento de conexión {attempt}/{retries} a MT5...")

        if not mt5.initialize():
            logger.error(f"mt5.initialize() falló: {mt5.last_error()}")
            _retry_wait(attempt, retries, delay)
            continue

        # Si se proporcionaron credenciales, hacer login explícito
        if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
            if not mt5.login(MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
                logger.error(f"Login fallido: {mt5.last_error()}")
                mt5.shutdown()
                _retry_wait(attempt, retries, delay)
                continue
            logger.info(f"✅ Conectado. Cuenta: #{MT5_LOGIN} @ {MT5_SERVER}")
        else:
            info = mt5.account_info()
            if info is None:
                logger.error("No hay cuenta activa en el terminal MT5.")
                mt5.shutdown()
                _retry_wait(attempt, retries, delay)
                continue
            logger.info(f"✅ Cuenta activa detectada: #{info.login} @ {info.server}")

        if _validate_symbol():
            _log_account_summary()
            return True

        mt5.shutdown()

    logger.critical("❌ No se pudo establecer conexión con MT5.")
    return False


def _validate_symbol() -> bool:
    """Verifica que XAUUSD esté disponible y lo habilita en Market Watch."""
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        logger.error(f"Símbolo '{SYMBOL}' no encontrado. Verifica el nombre exacto en tu broker.")
        return False

    if not info.visible:
        logger.info(f"Activando {SYMBOL} en Market Watch...")
        if not mt5.symbol_select(SYMBOL, True):
            logger.error(f"No se pudo activar {SYMBOL}: {mt5.last_error()}")
            return False

    logger.info(
        f"✅ {SYMBOL} | Dígitos: {info.digits} | Punto: {info.point} "
        f"| Contrato: {info.trade_contract_size} oz | "
        f"Tick value: {info.trade_tick_value}"
    )
    return True


def _log_account_summary():
    """Registra un resumen del estado de la cuenta."""
    acc = mt5.account_info()
    if acc:
        logger.info(
            f"💰 Cuenta: Balance={acc.balance:.2f} {acc.currency} | "
            f"Equity={acc.equity:.2f} | Margen libre={acc.margin_free:.2f} | "
            f"Apalancamiento=1:{acc.leverage}"
        )


def disconnect():
    """Desconecta del terminal MT5."""
    mt5.shutdown()
    logger.info("🔌 Desconectado de MT5.")


def is_market_open() -> bool:
    """Verifica si hay liquidez disponible (spread razonable)."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False
    spread = (tick.ask - tick.bid)
    info   = mt5.symbol_info(SYMBOL)
    if info is None:
        return False
    # Si el spread supera 50 puntos, el mercado puede estar cerrado o ilíquido
    max_spread = info.point * 50
    return spread < max_spread


def is_trading_session(swing_mode: bool = False) -> bool:
    """
    Verifica si se está dentro de una sesión de alta liquidez para XAU/USD.

    Scalping (swing_mode=False):
      Opera en cualquier hora del domingo 22:00 al viernes 21:00 UTC.
      Gold tiene liquidez 24/5 en scalping.

    Swing (swing_mode=True):
      Solo opera en las sesiones de Londres y Nueva York (máxima liquidez):
        • Londres:    08:00 – 17:00 UTC
        • Nueva York: 13:00 – 21:00 UTC
        • Solape:     13:00 – 17:00 UTC (más volumen)
      Evita:
        • Sesión asiática (00:00-07:00 UTC) — spread alto, movimientos erráticos
        • Viernes después de las 20:00 UTC — riesgo de gap de fin de semana
        • Sábado y domingo — mercado cerrado

    Returns:
        True si se puede operar en el modo configurado.
    """
    from datetime import datetime, timezone
    now     = datetime.now(timezone.utc)
    hour    = now.hour
    weekday = now.weekday()  # 0=lunes, 4=viernes, 5=sábado, 6=domingo

    # Fin de semana: mercado cerrado para todos los modos
    if weekday == 5:
        return False
    if weekday == 6 and hour < 22:
        return False

    # Viernes tarde: riesgo de gap de fin de semana (aplica a ambos modos)
    if weekday == 4 and hour >= 20:
        return False

    # En scalping: operar cualquier hora hábil
    if not swing_mode:
        return True

    # En swing: solo sesiones de alta liquidez (Londres + Nueva York)
    london_open    = 7 <= hour < 17    # 07:00-17:00 UTC (London)
    newyork_open   = 13 <= hour < 21   # 13:00-21:00 UTC (New York)
    active_session = london_open or newyork_open

    return active_session


def _retry_wait(attempt: int, retries: int, delay: int):
    if attempt < retries:
        logger.info(f"Reintentando en {delay}s...")
        time.sleep(delay)