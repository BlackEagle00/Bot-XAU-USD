"""
Grid + cesta (basket) — motor compartido, usado solo por los configs con USE_GRID=True.

Cuando la señal del scalping da BUY/SELL se abre una CESTA:
  • nivel 0 a mercado + niveles 1..N-1 como órdenes LÍMITE pendientes en contra
    (BUY: entrada − k·espaciado), que solo se activan si el precio llega a ellas;
  • cada nivel tiene un TP corto propio (GRID_TRADE_TP_ATR) → muchas operaciones cortas;
    al cerrarse en TP, el nivel se re-arma mientras la cesta siga viva;
  • STOP de cesta = un SL real en el bróker, común a todas las órdenes, GRID_STOP_BEYOND_ATR × ATR
    más allá del último nivel. Protege aunque el bot se caiga.

Para que la cuenta NO se queme (lecciones del backtest 2026-10-23):
  • Tamaño por RIESGO: el lote se calcula para que la cesta COMPLETA (todos los niveles llenos y el
    stop tocado) pierda como máximo GRID_RISK_PCT del capital. Si ni el lote mínimo cabe, se usan
    MENOS niveles; con capital mayor vuelven los niveles y el lote sube solo (lote dinámico).
    Si ni 1 nivel con el lote mínimo cabe en GRID_MAX_RISK_MIN_LOT, no se abre la cesta.
  • TP de cesta proporcional al riesgo (GRID_BASKET_TP_R × riesgo): no se cambian ganancias de
    centavos por pérdidas de 10%.
  • Sin cestas sobre el fin de semana (cierre el viernes a GRID_FRIDAY_CLOSE_HOUR, hora servidor) ni
    en las horas de corte diario (GRID_BLOCK_HOURS): ahí estaban las pérdidas por hueco.
  • Corte por drawdown: si la equity cae GRID_MAX_DD_PCT desde su máximo, se cierra todo y el bot
    deja de abrir cestas (hay que revisarlo y reiniciarlo a mano).

Las funciones puras (build_basket, basket_pnl, basket_decision, entry_allowed, must_flatten, dd_halt)
las usan igual el bot en vivo, el panel y el backtest (backtesting/engine_backtest.simulate_grid).
"""
import math
import re
from typing import Optional

import config as _cfg

GRID_DEFAULTS = dict(
    GRID_LOT_MODE="fixed", GRID_LOT_MULT=1.3, GRID_LEVELS=5, GRID_SPACING_ATR=1.0,
    GRID_TRADE_TP_ATR=1.0, GRID_RISK_PCT=0.03, GRID_MAX_RISK_MIN_LOT=0.06, GRID_STOP_BEYOND_ATR=1.0,
    GRID_BASKET_TP_R=0.5, GRID_MAX_MINUTES=720, GRID_FRIDAY_CLOSE_HOUR=22, GRID_BLOCK_HOURS=(23, 0),
    GRID_MAX_DD_PCT=0.30, GRID_MAX_BASKETS=1, GRID_EXTRA_SCORE=6.0, GRID_EXTRA_MIN_GAP=1.0,
    GRID_MAX_SCORE=math.inf,
)
_COMMENT = re.compile(r"G(\d+) L(\d+)")


def p(key: str, cfg=None):
    """Parámetro del grid: el del config o su valor por defecto."""
    return getattr(cfg or _cfg, key, GRID_DEFAULTS[key])


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES PURAS (probadas en tests/test_engine.py)
# ═══════════════════════════════════════════════════════════════════════════════

def _floor_step(lot: float, sym) -> float:
    step = sym.volume_step or 0.01
    return round(math.floor(lot / step + 1e-9) * step, 8)


def build_basket(side: str, entry: float, atr: float, equity: float, sym, vpu: float, cfg=None) -> Optional[dict]:
    """
    Cesta dimensionada por riesgo: {levels: [{k, price, lot, tp}], sl, risk_usd, tp_usd} o None si no cabe.
    vpu = USD por 1.0 de precio y por lote. El riesgo cuenta TODOS los niveles llenos hasta el stop.
    """
    cfg = cfg or _cfg
    d = 1 if side == "BUY" else -1
    spacing, tp_dist = atr * p("GRID_SPACING_ATR", cfg), atr * p("GRID_TRADE_TP_ATR", cfg)
    mult = p("GRID_LOT_MULT", cfg) if p("GRID_LOT_MODE", cfg) == "martingale" else 1.0
    vmin = max(getattr(cfg, "MIN_LOT", 0.01), sym.volume_min)
    max_lot = min(getattr(cfg, "MAX_LOT", 100.0), sym.volume_max)
    if equity <= 0 or atr <= 0 or vpu <= 0:
        return None
    levels = int(p("GRID_LEVELS", cfg))
    passes = [(p("GRID_RISK_PCT", cfg), False, levels), (p("GRID_MAX_RISK_MIN_LOT", cfg), True, levels)]
    if not getattr(cfg, "ENFORCE_CAPITAL_LEVEL", True):              # nivel informativo: 1 nivel al lote mínimo
        passes.append((math.inf, True, 1))                           # aunque pase el tope (riesgo elevado)
    for cap, min_lot_only, top in passes:
        for n in range(top, 0, -1):                                  # menos niveles si el capital no alcanza
            prices = [round(entry - d * k * spacing, sym.digits) for k in range(n)]
            sl = round(prices[-1] - d * atr * p("GRID_STOP_BEYOND_ATR", cfg), sym.digits)
            loss_per_lot = sum(mult ** k * abs(px - sl) for k, px in enumerate(prices)) * vpu
            lot0 = vmin if min_lot_only else min(_floor_step(equity * cap / loss_per_lot, sym), max_lot)
            if lot0 < vmin:
                continue
            lots = [min(max(_floor_step(lot0 * mult ** k, sym), lot0), max_lot) for k in range(n)]
            risk = sum(lt * abs(px - sl) for lt, px in zip(lots, prices)) * vpu
            if risk <= equity * cap + 1e-9:
                return {"levels": [{"k": k, "price": px, "lot": lt, "tp": round(px + d * tp_dist, sym.digits)}
                                   for k, (px, lt) in enumerate(zip(prices, lots))],
                        "sl": sl, "risk_usd": risk, "tp_usd": p("GRID_BASKET_TP_R", cfg) * risk}
    return None


def min_capital(atr: float, sym, vpu: float, cfg=None) -> float:
    """Capital mínimo para una cesta de 1 nivel con el lote mínimo dentro de GRID_MAX_RISK_MIN_LOT."""
    cfg = cfg or _cfg
    vmin = max(getattr(cfg, "MIN_LOT", 0.01), sym.volume_min)
    return vmin * atr * p("GRID_STOP_BEYOND_ATR", cfg) * vpu / p("GRID_MAX_RISK_MIN_LOT", cfg)


def basket_pnl(positions, bid: float, ask: float, vpu: float) -> float:
    """Flotante en USD de posiciones {side, entry, lot}: BUY se cierra al bid, SELL al ask."""
    return sum(((bid - q["entry"]) if q["side"] == "BUY" else (q["entry"] - ask)) * q["lot"] * vpu
               for q in positions)


def basket_decision(pnl: float, risk_usd: float, minutes_open: float, cfg=None) -> Optional[str]:
    """Cierre de la cesta: "STOP" (≤ −riesgo, respaldo del SL del bróker), "TP", "TIME" o None."""
    if risk_usd > 0 and pnl <= -risk_usd:
        return "STOP"
    if risk_usd > 0 and pnl >= p("GRID_BASKET_TP_R", cfg) * risk_usd:
        return "TP"
    if minutes_open >= p("GRID_MAX_MINUTES", cfg):
        return "TIME"
    return None


def extra_basket_block(action: str, score, open_, price: float = None, spacing: float = None,
                       cfg=None) -> Optional[str]:
    """
    Con cestas abiertas (dicts con side, entry, id), otra solo si hay cupo (GRID_MAX_BASKETS), va en la MISMA
    dirección (nunca BUY y SELL a la vez), la señal es fuerte (|score| ≥ GRID_EXTRA_SCORE; score None =
    apertura manual del panel) y el precio está a ≥ GRID_EXTRA_MIN_GAP × espaciado de cada entrada abierta
    (escalonar, no apilar el mismo precio). Para toda cesta, también la 1.ª: |score| ≤ GRID_MAX_SCORE (un
    score disparado es un movimiento ya extendido). Devuelve el motivo del bloqueo o None.
    """
    if score is not None and abs(score) > p("GRID_MAX_SCORE", cfg):
        return f"Señal extendida (score {score:+.2f} > ±{p('GRID_MAX_SCORE', cfg)}): no se compra el techo."
    if not open_:
        return None
    if len(open_) >= p("GRID_MAX_BASKETS", cfg):
        return f"Máximo de {p('GRID_MAX_BASKETS', cfg)} cesta(s) abierta(s)."
    if any(b["side"] != action for b in open_):
        return "Señal contraria a las cestas abiertas: no se cruzan BUY y SELL."
    if score is not None and abs(score) < p("GRID_EXTRA_SCORE", cfg):
        return f"Señal {score:+.2f} por debajo de ±{p('GRID_EXTRA_SCORE', cfg)} para una cesta extra."
    gap = p("GRID_EXTRA_MIN_GAP", cfg) * (spacing or 0)
    near = next((b for b in open_ if price is not None and abs(price - b["entry"]) < gap), None)
    if near:
        return f"Precio a {abs(price - near['entry']):.2f} de la cesta G{near.get('id')} (< {gap:.2f}): falta separación."
    return None


def must_flatten(server_dt, cfg=None) -> bool:
    """Viernes desde GRID_FRIDAY_CLOSE_HOUR (hora servidor) y fin de semana: nada abierto sobre el hueco."""
    return server_dt.weekday() >= 5 or (server_dt.weekday() == 4 and server_dt.hour >= p("GRID_FRIDAY_CLOSE_HOUR", cfg))


def entry_allowed(server_dt, cfg=None) -> bool:
    """Se puede abrir una cesta: fuera del cierre de viernes y de las horas de corte diario."""
    return not must_flatten(server_dt, cfg) and server_dt.hour not in tuple(p("GRID_BLOCK_HOURS", cfg))


def dd_halt(equity: float, peak: float, cfg=None) -> bool:
    """Corte por drawdown: la equity cayó GRID_MAX_DD_PCT desde su máximo."""
    return peak > 0 and equity <= peak * (1 - p("GRID_MAX_DD_PCT", cfg))


def parse_comment(comment: str):
    """'XAU G1792153800 L3' → (1792153800, 3) o None."""
    m = _COMMENT.search(comment or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


# ═══════════════════════════════════════════════════════════════════════════════
# EJECUCIÓN EN VIVO (MT5)
# ═══════════════════════════════════════════════════════════════════════════════
# Hasta GRID_MAX_BASKETS cestas por MAGIC_NUMBER, todas del mismo lado (extra_basket_block). Cada orden
# lleva "G<id> L<nivel>" en el comentario (id = hora de apertura del servidor), así cada cesta se reconoce
# aunque el bot se reinicie. Su riesgo se reconstruye de sus órdenes (lote × distancia al SL común). Lo
# único que se pierde al reiniciar es el re-armado de niveles. El máximo de equity del corte por drawdown
# se cuenta desde el arranque del proceso.

_baskets = {}                      # id → {side, levels, sl}: las cestas abiertas por este proceso
_state = {"peak": 0.0, "halted": False}


def exec_atr(atr: float, symbol: str = None, cfg=None) -> Optional[float]:
    """ATR (velas cerradas) del TF de ejecución GRID_EXEC_TF ("M1"/"M5"); sin él, el `atr` del TF de análisis."""
    tf = getattr(cfg or _cfg, "GRID_EXEC_TF", None)
    if not tf:
        return atr
    import MetaTrader5 as mt5
    from .data_handler import fetch_ohlcv
    from .indicators import calc_atr
    df = fetch_ohlcv(symbol or _cfg.SYMBOL, getattr(mt5, f"TIMEFRAME_{tf}"), 200)
    return float(calc_atr(df["high"], df["low"], df["close"]).iloc[-1]) if df is not None and len(df) > 20 else None


def _vpu(symbol_info) -> float:
    from .risk_manager import _tick_value
    return _tick_value(symbol_info) / symbol_info.trade_tick_size


def baskets(symbol: str = None, symbol_info=None) -> list:
    """Cestas abiertas (posiciones + pendientes de este MAGIC, agrupadas por G<id>) con su P&L y su riesgo, por id."""
    from .data_handler import get_open_positions, get_pending_orders, server_now
    positions, orders = get_open_positions(symbol), get_pending_orders(symbol)
    tag = lambda x: (parse_comment(x.comment) or (None, None))
    now, vpu = server_now(), (_vpu(symbol_info) if symbol_info else 0.0)
    out = []
    for bid in sorted({tag(x)[0] for x in list(positions) + list(orders)} - {None}):
        pos = [q for q in positions if tag(q)[0] == bid]
        ords = [o for o in orders if tag(o)[0] == bid]
        floating = sum(q.profit + q.swap for q in pos)
        realized = _realized_since(bid)
        risk = sum(x.volume * abs(x.price_open - x.sl) for x in pos if x.sl) * vpu \
            + sum(o.volume_current * abs(o.price_open - o.sl) for o in ords if o.sl) * vpu
        out.append({"id": bid, "side": "BUY" if (pos + ords)[0].type % 2 == 0 else "SELL",   # BUY y BUY_LIMIT son pares
                    "entry": (pos + ords)[0].price_open,
                    "positions": len(pos), "pending": len(ords),
                    "lots": round(sum(q.volume for q in pos), 2), "floating": round(floating, 2),
                    "realized": round(realized, 2), "pnl": round(floating + realized, 2), "risk_usd": round(risk, 2),
                    "tp_usd": round(p("GRID_BASKET_TP_R") * risk, 2),
                    "minutes": round(((now.timestamp() if now else bid) - bid) / 60, 1),
                    "levels_used": sorted({tag(q)[1] for q in pos}), "levels_pending": sorted({tag(o)[1] for o in ords}),
                    "tickets": [q.ticket for q in pos], "orders": [o.ticket for o in ords]})
    return out


def basket_status(symbol: str = None, symbol_info=None) -> Optional[dict]:
    """La cesta abierta más reciente (la que muestra el panel), o None."""
    open_ = baskets(symbol, symbol_info)
    return open_[-1] if open_ else None


def _realized_since(ts: int) -> float:
    """P&L cerrado de la cesta G<ts>: solo las posiciones que abrió ella (por el comentario de su entrada)."""
    from datetime import datetime, timedelta, timezone
    import MetaTrader5 as mt5
    from config import MAGIC_NUMBER
    # Ventana amplia (hora servidor ≠ UTC); el filtro por id evita sumar el stop de la cesta anterior.
    start = datetime.fromtimestamp(ts - 86400, tz=timezone.utc)
    deals = mt5.history_deals_get(start, datetime.now(timezone.utc) + timedelta(days=1)) or []
    mine = {d.position_id for d in deals if d.magic == MAGIC_NUMBER and d.entry == mt5.DEAL_ENTRY_IN
            and (parse_comment(d.comment) or (None,))[0] == ts}
    return sum(d.profit + d.swap + d.commission for d in deals
               if d.entry == mt5.DEAL_ENTRY_OUT and d.position_id in mine)


def close_basket(reason: str, symbol_info, symbol: str = None, st: dict = None) -> None:
    """Cierra las posiciones de la cesta `st` (por defecto la más reciente) y cancela sus pendientes."""
    from .trade_manager import close_trade, cancel_pending_orders
    from .telegram_notifier import notify
    from .logger_config import logger
    st = st or basket_status(symbol, symbol_info)
    if not st:
        return
    cancel_pending_orders(symbol, st["orders"])
    for t in st["tickets"]:
        close_trade(t, symbol_info)
    logger.info(f"🧺 Cesta G{st['id']} cerrada por {reason} | P&L {st['pnl']:+.2f} USD | "
                f"{st['positions']} abiertas, niveles {st['levels_used']}, {st['minutes']:.0f} min")
    notify(f"🧺 Cesta {st['side']} cerrada por {reason} | P&L {st['pnl']:+.2f} USD")
    _baskets.pop(st["id"], None)


def manage_basket(symbol_info, symbol: str = None) -> Optional[str]:
    """Cada ciclo (aunque el spread esté alto): corte por drawdown, cierre de viernes, TP/STOP/tiempo y re-armado."""
    from .data_handler import get_account_info, get_tick, server_now
    from .telegram_notifier import notify
    from .logger_config import logger
    acc = get_account_info()
    if acc:
        _state["peak"] = max(_state["peak"], acc.equity)
        if not _state["halted"] and dd_halt(acc.equity, _state["peak"]):
            _state["halted"] = True
            logger.warning(f"⛔ Corte por drawdown del grid: equity {acc.equity:,.2f} ≤ "
                           f"{(1 - p('GRID_MAX_DD_PCT')) * 100:.0f}% del máximo {_state['peak']:,.2f}. "
                           f"Se cierra todo y no se abren más cestas hasta reiniciar el bot.")
    open_ = baskets(symbol, symbol_info)
    for gone in set(_baskets) - {st["id"] for st in open_}:     # cerradas por el SL del bróker
        # shortcut: solo las cestas de este proceso; tras un reinicio las cuenta el resumen por deals
        pnl = _realized_since(gone)
        logger.info(f"🧺 Cesta G{gone} cerrada por SL_BROKER | P&L {pnl:+.2f} USD")
        notify(f"🧺 Cesta {_baskets.pop(gone)['side']} cerrada por SL del bróker | P&L {pnl:+.2f} USD")
    now, tick, closed = server_now(), get_tick(symbol), None
    for st in open_:
        reason = ("DD" if _state["halted"] else "FINDE" if now and must_flatten(now)
                  else basket_decision(st["pnl"], st["risk_usd"], st["minutes"]))
        if reason:
            close_basket(reason, symbol_info, symbol, st)
            closed = closed or reason
            continue
        b = _baskets.get(st["id"])
        if b and tick:
            busy = set(st["levels_used"]) | set(st["levels_pending"])
            for lv in b["levels"]:
                if lv["k"] not in busy:
                    _place_level(b["side"], lv, b["sl"], tick, symbol_info, st["id"], symbol)
    return closed


def _place_level(side, lv, sl, tick, symbol_info, basket_id, symbol=None) -> None:
    """Límite del nivel, solo si el precio aún no lo cruzó (un límite del lado equivocado lo rechaza MT5)."""
    from .trade_manager import place_pending
    gap = max(symbol_info.trade_stops_level, 1) * symbol_info.point
    if (side == "BUY" and tick.ask - gap > lv["price"]) or (side == "SELL" and tick.bid + gap < lv["price"]):
        place_pending(side, lv["price"], lv["lot"], sl, lv["tp"], symbol_info,
                      comment=f"G{basket_id} L{lv['k']}", symbol=symbol)


def try_open_basket(action: str, tick, atr: float, symbol_info, symbol: str = None, score: float = None) -> dict:
    """Abre una cesta (mercado + límites) si extra_basket_block la permite y pasan las compuertas del motor."""
    from .data_handler import get_account_info, server_now
    from .risk_manager import can_open_trade, spread_ok
    from .news_filter import in_news_blackout
    from .trade_manager import open_trade
    from .logger_config import logger
    if _state["halted"]:
        return {"ok": False, "reason": "Corte por drawdown activo: reinicia el bot tras revisarlo."}
    why = extra_basket_block(action, score, baskets(symbol, symbol_info),
                             tick.ask if action == "BUY" else tick.bid, atr * p("GRID_SPACING_ATR"))
    if why:
        return {"ok": False, "reason": why}
    now = server_now()
    if now and not entry_allowed(now):
        return {"ok": False, "reason": "Horario sin cestas nuevas (cierre del viernes o corte diario)."}
    if getattr(_cfg, "USE_NEWS_FILTER", False):
        blocked, ev = in_news_blackout()
        if blocked:
            return {"ok": False, "reason": f"Noticia de alto impacto: {ev}"}
    ok, why = can_open_trade(action, symbol)
    if not ok:
        return {"ok": False, "reason": why}
    spread, step = tick.ask - tick.bid, atr * min(p("GRID_SPACING_ATR"), p("GRID_TRADE_TP_ATR"))
    if not spread_ok(spread, step):
        return {"ok": False, "reason": f"Spread {spread:.2f} demasiado alto frente al espaciado {step:.2f}."}
    acc = get_account_info()
    if acc is None:
        return {"ok": False, "reason": "Sin datos de la cuenta."}
    vpu = _vpu(symbol_info)
    b = build_basket(action, tick.ask if action == "BUY" else tick.bid, atr, min(acc.balance, acc.equity),
                     symbol_info, vpu)
    if b is None:
        need = min_capital(atr, symbol_info, vpu)
        return {"ok": False, "reason": f"Ni una cesta de 1 nivel con el lote mínimo cabe en el "
                                       f"{p('GRID_MAX_RISK_MIN_LOT') * 100:.0f}%: necesitas ≥ {need:,.2f}."}
    levels, sl = b["levels"], b["sl"]
    basket_id = int(now.timestamp()) if now else int(tick.time)
    ticket = open_trade(action, sl, levels[0]["tp"], levels[0]["lot"], symbol_info,
                        comment=f"G{basket_id} L0", symbol=symbol)
    if not ticket:
        return {"ok": False, "reason": "MT5 rechazó la orden del nivel 0."}
    _baskets[basket_id] = {"side": action, "levels": levels, "sl": sl}
    for lv in levels[1:]:
        _place_level(action, lv, sl, tick, symbol_info, basket_id, symbol)
    logger.info(f"🧺 Cesta {action} G{basket_id} | {len(levels)} niveles cada {atr * p('GRID_SPACING_ATR'):.2f} | "
                f"lotes {[lv['lot'] for lv in levels]} | SL {sl} | riesgo {b['risk_usd']:.2f} USD "
                f"| TP cesta {b['tp_usd']:.2f} USD")
    return {"ok": True, "ticket": ticket, "basket": basket_id, **b}


def plan(action: str, tick, atr: float, symbol_info, equity: float) -> dict:
    """Vista previa de la cesta para el panel (no envía nada)."""
    vpu = _vpu(symbol_info)
    b = build_basket(action, tick.ask if action == "BUY" else tick.bid, atr, equity, symbol_info, vpu)
    base = {"side": action, "mode": p("GRID_LOT_MODE"), "max_minutes": p("GRID_MAX_MINUTES"),
            "halted": _state["halted"], "exec_tf": getattr(_cfg, "GRID_EXEC_TF", None), "atr": atr,
            "spacing": atr * p("GRID_SPACING_ATR")}
    if b is None:
        return {**base, "levels": [], "capital_needed": round(min_capital(atr, symbol_info, vpu), 2),
                "cap_pct": p("GRID_MAX_RISK_MIN_LOT") * 100}
    elevated = b["risk_usd"] > equity * p("GRID_RISK_PCT") + 1e-9
    return {**base, **b, "risk_pct": round(b["risk_usd"] / equity * 100, 2) if equity else None, "elevated": elevated,
            "capital_needed": round(min_capital(atr, symbol_info, vpu), 2) if elevated else None}
