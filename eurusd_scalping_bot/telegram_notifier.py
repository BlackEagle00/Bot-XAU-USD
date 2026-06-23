"""
Notificaciones por Telegram — avisa al celular de la actividad del bot.

Envía un mensaje cuando el bot:
  • arranca / se detiene
  • abre una operación
  • cierra una operación (SL / TP / manual) — detectado al desaparecer el ticket
  • pierde / recupera la conexión con MT5

Diseño (igual que news_filter.py): solo stdlib (urllib), nunca lanza excepción
hacia el loop (fail-open), y el envío va en un hilo aparte para NO frenar el ciclo
de trading. Si falta el token o el chat_id, las notificaciones se desactivan solas.

Token y chat_id se cargan desde .env (ver config.py):
    TELEGRAM_BOT_TOKEN   ← te lo da @BotFather al crear el bot
    TELEGRAM_CHAT_ID     ← tu id numérico (háblale a @userinfobot)
"""
import threading
import urllib.parse
import urllib.request

import MetaTrader5 as mt5

from logger_config import logger
from config import (
    USE_TELEGRAM, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PREFIX, SYMBOL,
)

_API = "https://api.telegram.org/bot{token}/sendMessage"

# El factor se activa solo si está encendido Y hay credenciales completas.
_enabled = bool(USE_TELEGRAM and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
_warned  = False        # para avisar una sola vez que faltan credenciales

# Estado interno
_seen         = None    # {ticket: (dir, volumen, precio_entrada)} del ciclo anterior
_conn_alerted = False   # ya avisamos de la caída de conexión (evita spam por ciclo)


def _send(text: str) -> None:
    """Envía el mensaje a la API de Telegram. Silencioso ante cualquier fallo."""
    try:
        url  = _API.format(token=TELEGRAM_BOT_TOKEN)
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text":    text,
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as exc:
        logger.debug(f"Telegram: no se pudo enviar el mensaje: {exc}")


def notify(text: str, block: bool = False) -> None:
    """
    Envía un mensaje a Telegram (con el prefijo del bot, p.ej. "[GOLD swing]").

    block=False (por defecto): envía en un hilo daemon → no frena el loop.
    block=True: envío síncrono (úsalo en el cierre, para que el último mensaje
                alcance a salir antes de que el proceso termine).
    """
    global _warned
    if not _enabled:
        if USE_TELEGRAM and not _warned:
            logger.info(
                "📨 Telegram activado pero falta TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
                "en .env — notificaciones desactivadas."
            )
            _warned = True
        return

    msg = f"{TELEGRAM_PREFIX} {text}" if TELEGRAM_PREFIX else text
    if block:
        _send(msg)
    else:
        threading.Thread(target=_send, args=(msg,), daemon=True).start()


def notify_connection_lost() -> None:
    """Avisa UNA sola vez que se perdió la conexión (se rearma al recuperarla)."""
    global _conn_alerted
    if not _conn_alerted:
        notify("⚠ Conexión a MT5 perdida; no se pudo reconectar. Reintentando cada ciclo...")
        _conn_alerted = True


def notify_connection_restored() -> None:
    """Avisa que la conexión volvió (solo si antes se había caído)."""
    global _conn_alerted
    if _conn_alerted:
        notify("✅ Conexión a MT5 restablecida.")
        _conn_alerted = False


def _realized_pnl(ticket: int):
    """Suma el P&L neto (profit+swap+comisión) de los deals de la posición cerrada."""
    try:
        deals = mt5.history_deals_get(position=ticket)
        if not deals:
            return None
        return sum(d.profit + d.swap + d.commission for d in deals)
    except Exception:
        return None


def check_closed_positions(open_positions) -> None:
    """
    Detecta posiciones cerradas entre ciclos (SL / TP / manual) comparando los
    tickets abiertos con los del ciclo anterior, y avisa con el P&L realizado.

    Llamar una vez por ciclo con la lista actual de posiciones del bot
    (get_open_positions(), ya filtrada por MAGIC_NUMBER).
    """
    global _seen
    if not _enabled:
        return

    current = {
        p.ticket: ("BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL", p.volume, p.price_open)
        for p in (open_positions or [])
    }

    if _seen is None:               # primer ciclo: solo inicializa, sin avisar
        _seen = current
        return

    for ticket, (direction, _vol, _entry) in _seen.items():
        if ticket not in current:   # el ticket desapareció → se cerró
            pnl     = _realized_pnl(ticket)
            win     = pnl is None or pnl >= 0
            emoji   = "✅" if win else "🔴"
            pnl_str = f"{pnl:+.2f} USD" if pnl is not None else "n/d"
            notify(f"{emoji} Cerrado {direction} #{ticket} {SYMBOL} | P&L: {pnl_str}")

    _seen = current
