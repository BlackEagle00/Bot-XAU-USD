"""
Gestión de conexión con MetaTrader 5.
Maneja inicialización, login, validación de símbolo y reconexión.
"""
import time
import MetaTrader5 as mt5
from logger_config import logger
from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, SYMBOL, MAX_SPREAD_POINTS


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

    logger.info(f"✅ Información del símbolo {SYMBOL}:")
    logger.info(f"   • Dígitos: {info.digits}")
    logger.info(f"   • Punto: {info.point}")
    logger.info(f"   • Tamaño contrato: {info.trade_contract_size} oz")
    logger.info(f"   • Tick size: {info.trade_tick_size}")
    logger.info(f"   • Tick value: {info.trade_tick_value}")
    logger.info(f"   • Volumen mín: {info.volume_min}")
    logger.info(f"   • Volumen step: {info.volume_step}")
    logger.info(f"   • Volumen máx: {info.volume_max}")
    logger.info(f"   • Stops level (mín distancia SL/TP): {info.trade_stops_level}")
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
    info = mt5.symbol_info(SYMBOL)
    if info is None or info.point <= 0:
        return False
    # Spread actual en puntos (independiente de la escala del instrumento)
    spread_points = (tick.ask - tick.bid) / info.point
    if spread_points >= MAX_SPREAD_POINTS:
        logger.debug(
            f"Spread alto: {spread_points:.0f} pts ≥ máx {MAX_SPREAD_POINTS}. "
            f"Saltando ciclo (ajusta MAX_SPREAD_POINTS si tu broker tiene spread mayor)."
        )
        return False
    return True


def _retry_wait(attempt: int, retries: int, delay: int):
    if attempt < retries:
        logger.info(f"Reintentando en {delay}s...")
        time.sleep(delay)