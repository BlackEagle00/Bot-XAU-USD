"""
Nombre del símbolo según el bróker: cada uno llama distinto al oro (XAUUSD, XAUUSD-ECN, XAUUSDm, #XAUUSD, GOLD.pro…).

Se resuelve en los puntos de entrada (main.py de cada bot y dashboard/worker.py) ANTES de importar el motor, porque
sus módulos hacen `from config import SYMBOL` al importarse. Por eso este módulo no importa `config`.
"""
import re

import MetaTrader5 as mt5

# shortcut: lista fija de divisas para descartar cruces (GOLDEUR…); ampliarla si un bróker usa otro código
_CCY = {"EUR", "AUD", "JPY", "GBP", "CHF", "CAD", "USD", "NZD", "CNH", "SGD", "HKD", "TRY", "ZAR", "MXN"}


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def pick_symbol(base: str, aliases, infos) -> tuple:
    """Elige entre `infos` (objetos con name/trade_mode/spread) el símbolo de `base`. Pura → probada en tests.
    Exacto operable > candidatos operables que contienen base o alias (sin cruces), por menor spread y nombre más corto.
    Devuelve (nombre, candidatos); sin candidatos, (base, [])."""
    ok = [i for i in infos if i.trade_mode != mt5.SYMBOL_TRADE_MODE_DISABLED]
    if any(i.name == base for i in ok):
        return base, [base]
    keys = [_norm(k) for k in (base, *aliases) if k]
    cands = []
    for i in ok:
        n = _norm(i.name)
        for k in keys:
            pos = n.find(k)
            if pos < 0:
                continue
            before, after = n[:pos], n[pos + len(k):]
            if after[:3] in _CCY or (len(before) >= 3 and before.isalpha()):   # GOLDEUR, BTCXAUUSD: otro activo
                continue
            cands.append(i)
            break
    if not cands:
        return base, []
    cands.sort(key=lambda i: (i.spread, len(i.name), i.name))
    return cands[0].name, [i.name for i in cands]


def resolve_symbol(base: str, aliases=()) -> str:
    """Nombre real del oro en el bróker conectado. Si MT5 no responde, devuelve `base` (connect() informa el error)."""
    if not mt5.initialize():
        return base
    name, cands = pick_symbol(base, aliases, mt5.symbols_get() or ())
    if name != base:
        mt5.symbol_select(name, True)
        from .logger_config import logger
        logger.info(f"🔎 Símbolo {base} → {name} (candidatos por spread: {', '.join(cands)})")
    return name
