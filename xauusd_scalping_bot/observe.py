"""
Lanzador en MODO OBSERVACIÓN (pedido del usuario 2026-10-29: "lanza el bot con el envío de órdenes anulado (ninguna
orden real, mismo método que usa sim_parallel)"). Es el bot de Scalping completo (mismas señales, filtros, diario y
log), pero ninguna orden llega al bróker:
  - mt5.order_send / order_check / order_send_async lanzan error en este proceso (como sim_parallel);
  - core.open_trade se sustituye por un registro "👁 OBSERVACIÓN" + evento "observed" en el diario.
Por eso permite arrancar en la cuenta real sin ALLOW_LIVE_TRADING (solo lee datos).

Uso (desde la raíz):  python xauusd_scalping_bot/observe.py
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)                                  # LOG_FILE es relativo: mismo cwd que run.py
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import config                                   # noqa: E402
from bot_engine.symbols import resolve_symbol   # noqa: E402
config.SYMBOL = resolve_symbol(config.SYMBOL, getattr(config, "SYMBOL_ALIASES", ()))

import MetaTrader5 as mt5                       # noqa: E402
from bot_engine import core, connection, journal  # noqa: E402
from bot_engine.logger_config import logger     # noqa: E402


def _no_orders(*a, **k):
    raise RuntimeError("OBSERVACIÓN: órdenes anuladas en este proceso")


def _observe(action, sl, tp, lot, symbol_info, comment="", symbol=None):
    logger.warning(f"👁 OBSERVACIÓN: {action} {lot} lote(s) SL {sl} TP {tp} ({comment}) — orden NO enviada")
    journal.log("observed", action=action, lot=lot, sl=sl, tp=tp)
    return -1        # verdadero: core marca la vela como decidida (1 decisión por vela, como en real)


def _allowed():
    acc = mt5.account_info()
    if acc is None:
        return False
    logger.warning("👁 MODO OBSERVACIÓN: cuenta %s, órdenes anuladas — no se envía nada al bróker.",
                   "DEMO" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "REAL")
    return True


def arm():
    for name in ("order_send", "order_check", "order_send_async"):
        setattr(mt5, name, _no_orders)
    core.open_trade = _observe
    connection._account_allowed = _allowed
    for name in ("order_send", "order_check"):        # autocomprobación antes de conectar
        try:
            getattr(mt5, name)({})
        except RuntimeError:
            continue
        raise SystemExit(f"OBSERVACIÓN: {name} no quedó anulado; no arranco")
    assert core.open_trade is _observe


if __name__ == "__main__":
    arm()
    core.run()
