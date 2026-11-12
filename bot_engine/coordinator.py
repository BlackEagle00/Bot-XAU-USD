"""
Coordinador de motores, estado persistente y cortacircuitos (2026-10-27).

Estados (los decide el bróker, no la memoria del proceso):
  IDLE              sin posiciones ni órdenes en el símbolo → este motor puede abrir
  <MOTOR>_ACTIVE    solo hay posiciones/órdenes de este motor → puede abrir (sus límites los pone risk_manager)
  DRAINING          hay posiciones/órdenes AJENAS en el símbolo (otro bot, el panel o manuales) → no abre
  SAFE_MODE         cortacircuitos activo, configuración inválida o no se pudo leer el bróker → no abre
Las posiciones abiertas se siguen gestionando en todos los estados.

Una sola instancia por bot (bloqueo de archivo del SO). El estado (última vela operada, pico de equity,
cortes, fallos de orden, cortacircuitos) vive en <carpeta del config>/state/state.json: reiniciar no lo borra.
Un cortacircuitos automático solo se suelta al reiniciar si la conciliación pasa (posiciones legibles y
todas las propias con SL); el de estado corrupto, solo cuando el operador borra state.json.corrupt.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5

import config as _cfg
from .logger_config import logger
from . import journal

STATE_DIR = Path(_cfg.__file__).resolve().parent / "state"
ENGINE = "SCALPING" if "scalp" in STATE_DIR.parent.name.lower() else "SWING"
ORDER_FAIL_LIMIT = getattr(_cfg, "ORDER_FAIL_LIMIT", 3)        # fallos de orden seguidos → SAFE_MODE
STALE_TICK_SEC = getattr(_cfg, "STALE_TICK_SEC", 120)          # precio sin cambiar tanto tiempo → sin entradas

IDLE, DRAINING, SAFE = "IDLE", "DRAINING", "SAFE_MODE"

_DEFAULT = {"last_trade_bar": None, "peak": 0.0, "dd_stopped": False, "cash_ts": 0, "halt_day": None,
            "order_fails": 0, "breaker": None}
state = dict(_DEFAULT)
_saved = None
_lock_fh = None
_login = None                 # cuenta con la que arrancó el bot
_config_errors = []           # validate_config(): no se persisten, se corrigen editando el config
_tick_seen = (None, 0.0)      # (tick.time, reloj monotónico cuando cambió por última vez)


def _path() -> Path:
    return STATE_DIR / "state.json"


def _corrupt() -> Path:
    return STATE_DIR / "state.json.corrupt"


# ─── Instancia única ──────────────────────────────────────────────────────────

def acquire_instance_lock() -> bool:
    """True si esta es la única instancia del bot; el bloqueo dura lo que viva el proceso."""
    global _lock_fh
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(STATE_DIR / "instance.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _lock_fh = fh
    return True


# ─── Estado persistente ───────────────────────────────────────────────────────

def load_state() -> dict:
    global _saved
    state.clear()
    state.update(_DEFAULT)
    p = _path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("no es un objeto JSON")
            state.update({k: data[k] for k in _DEFAULT if k in data})
        except (ValueError, OSError) as exc:
            os.replace(p, _corrupt())
            trip(f"estado corrupto ({exc}); revisa y borra {_corrupt().name} para reanudar", manual=True)
    _saved = None
    return state


def save_state(**changes) -> None:
    """Guarda (atómico) solo si algo cambió."""
    global _saved
    state.update(changes)
    if state == _saved:
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    os.replace(tmp, _path())
    _saved = json.loads(json.dumps(state, default=str))


# ─── Cortacircuitos ───────────────────────────────────────────────────────────

def trip(reason: str, manual: bool = False) -> None:
    """SAFE_MODE: sin entradas nuevas hasta reiniciar y conciliar. Se queda el primer motivo."""
    if state.get("breaker"):
        return
    state["breaker"] = {"reason": reason, "manual": manual,
                        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    logger.critical(f"⛔ SAFE_MODE: {reason}. Sin entradas nuevas; las posiciones abiertas se siguen gestionando.")
    journal.log("breaker", reason=reason, manual=manual)
    try:
        from .telegram_notifier import notify
        notify(f"⛔ SAFE_MODE: {reason}")
    except Exception:
        pass
    save_state()


def record_order(ok: bool) -> None:
    """Cuenta fallos de orden seguidos; al llegar a ORDER_FAIL_LIMIT activa SAFE_MODE."""
    state["order_fails"] = 0 if ok else state.get("order_fails", 0) + 1
    if state["order_fails"] >= ORDER_FAIL_LIMIT:
        trip(f"{state['order_fails']} fallos de orden seguidos")
    save_state()


def reconcile(symbol: str, own_magic: int) -> bool:
    """Al arrancar: posiciones legibles y todas las propias con SL. Suelta un cortacircuitos si procede."""
    pos = mt5.positions_get(symbol=symbol)
    if pos is None:
        logger.error(f"Conciliación: no se pudieron leer las posiciones ({mt5.last_error()})")
        return False
    mine = [p for p in pos if p.magic == own_magic]
    unprotected = [p.ticket for p in mine if not p.sl]
    b = state.get("breaker")
    if b and (b.get("manual") and not _corrupt().exists() or not b.get("manual") and not unprotected):
        logger.warning(f"🔓 Cortacircuitos liberado tras conciliar al reiniciar (era: {b['reason']})")
        journal.log("breaker_cleared", reason=b["reason"], own_positions=len(mine))
        state.update(breaker=None, order_fails=0)
    if unprotected:
        trip(f"posición(es) propia(s) sin stop-loss: {unprotected}")
    logger.info(f"🔎 Conciliación: {len(mine)} posición(es) propia(s), {len(pos) - len(mine)} ajena(s) en {symbol}")
    save_state()
    return not unprotected


# ─── Configuración ────────────────────────────────────────────────────────────

def validate_config(cfg=_cfg) -> list:
    """Errores de configuración que impiden abrir entradas (vacío = válida)."""
    g = lambda k, d=None: getattr(cfg, k, d)
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    checks = [
        (isinstance(g("SYMBOL"), str) and g("SYMBOL"), "SYMBOL vacío"),
        (isinstance(g("MAGIC_NUMBER"), int) and g("MAGIC_NUMBER") > 0, "MAGIC_NUMBER debe ser un entero > 0"),
        (num(g("RISK_PER_TRADE")) and 0 < g("RISK_PER_TRADE") <= 0.05, "RISK_PER_TRADE fuera de (0, 5 %]"),
        (num(g("MAX_DAILY_LOSS_PCT")) and 0 < g("MAX_DAILY_LOSS_PCT") <= 0.5, "MAX_DAILY_LOSS_PCT fuera de (0, 50 %]"),
        (isinstance(g("MAX_OPEN_TRADES"), int) and g("MAX_OPEN_TRADES") >= 1, "MAX_OPEN_TRADES debe ser ≥ 1"),
        (num(g("SL_ATR_MULT")) and g("SL_ATR_MULT") > 0, "SL_ATR_MULT debe ser > 0"),
        (num(g("TP_ATR_MULT")) and g("TP_ATR_MULT") > 0, "TP_ATR_MULT debe ser > 0"),
        (num(g("MIN_SIGNAL_SCORE")) and g("MIN_SIGNAL_SCORE") > 0, "MIN_SIGNAL_SCORE debe ser > 0"),
        (num(g("MAX_SPREAD_POINTS")) and g("MAX_SPREAD_POINTS") > 0, "MAX_SPREAD_POINTS debe ser > 0"),
        (num(g("LOOP_INTERVAL")) and g("LOOP_INTERVAL") > 0, "LOOP_INTERVAL debe ser > 0"),
        (g("MAX_DD_PCT") is None or num(g("MAX_DD_PCT")) and 0 < g("MAX_DD_PCT") < 1, "MAX_DD_PCT fuera de (0, 1)"),
        (g("LATE_ENTRY_SCORE") is None or num(g("LATE_ENTRY_SCORE")) and g("LATE_ENTRY_SCORE") >= (g("MIN_SIGNAL_SCORE") or 0),
         "LATE_ENTRY_SCORE menor que MIN_SIGNAL_SCORE"),
    ]
    return [msg for ok, msg in checks if not ok]


def start(acc) -> None:
    """Arranque: registra cuenta (tipo y margin mode), versión y hash; valida config; concilia."""
    global _login, _config_errors
    _login = acc.login if acc else None
    margin = {getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_NETTING", 0): "netting",
              getattr(mt5, "ACCOUNT_MARGIN_MODE_EXCHANGE", 1): "exchange",
              getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2): "hedging"}.get(getattr(acc, "margin_mode", None), "?")
    real = acc is not None and acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO
    logger.info(f"🧭 Motor {ENGINE} | cuenta {'REAL' if real else 'demo'} ({margin}) | "
                f"versión {journal.VERSION} | config {journal.CONFIG_HASH}")
    _config_errors = validate_config()
    for e in _config_errors:
        logger.critical(f"⛔ Configuración inválida: {e}. Sin entradas hasta corregirla y reiniciar.")
    journal.log("start", engine=ENGINE, account="REAL" if real else "demo", margin_mode=margin,
                config_errors=_config_errors, breaker=state.get("breaker"))
    reconcile(_cfg.SYMBOL, _cfg.MAGIC_NUMBER)


# ─── Autorización de entradas ─────────────────────────────────────────────────

def mode_state(symbol: str, own_magic: int):
    """(estado, motivo) según el bróker. Solo IDLE y <ENGINE>_ACTIVE autorizan entradas."""
    if state.get("breaker"):
        return SAFE, state["breaker"]["reason"]
    if _config_errors:
        return SAFE, f"configuración inválida: {'; '.join(_config_errors)}"
    pos, orders = mt5.positions_get(symbol=symbol), mt5.orders_get(symbol=symbol)
    if pos is None or orders is None:
        return SAFE, f"no se pudieron leer posiciones/órdenes: {mt5.last_error()}"
    foreign = [x for x in (*pos, *orders) if x.magic != own_magic]
    if foreign:
        return DRAINING, (f"{len(foreign)} posición(es)/orden(es) ajena(s) en {symbol} "
                          f"(magic {sorted({x.magic for x in foreign})}); solo un motor opera a la vez")
    return (f"{ENGINE}_ACTIVE", "") if (pos or orders) else (IDLE, "")


def entry_gate(symbol: str, own_magic: int, tick):
    """(puede_abrir, motivo, estado). Comprueba coordinador, terminal, cuenta y frescura del precio."""
    global _tick_seen
    mode, why = mode_state(symbol, own_magic)
    if mode not in (IDLE, f"{ENGINE}_ACTIVE"):
        return False, why, mode
    ti = mt5.terminal_info()
    if ti is None or not getattr(ti, "connected", False):
        return False, "terminal desconectado del servidor", mode
    if not getattr(ti, "trade_allowed", False):
        return False, "Algo Trading desactivado en el terminal", mode
    acc = mt5.account_info()
    if acc is None:
        return False, "no se pudo leer la cuenta", mode
    if _login is not None and acc.login != _login:
        trip("la cuenta del terminal cambió durante la ejecución")
        return False, state["breaker"]["reason"], SAFE
    if acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO and os.getenv("ALLOW_LIVE_TRADING") != "1":
        trip("cuenta REAL sin ALLOW_LIVE_TRADING=1")
        return False, state["breaker"]["reason"], SAFE
    now = time.monotonic()
    if tick.time != _tick_seen[0]:
        _tick_seen = (tick.time, now)
    elif now - _tick_seen[1] > STALE_TICK_SEC:
        return False, f"precio sin cambios hace {now - _tick_seen[1]:.0f} s (mercado pausado o feed caído)", mode
    return True, "", mode
