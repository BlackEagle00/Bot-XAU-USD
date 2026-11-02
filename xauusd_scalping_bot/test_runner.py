"""
Prueba en vivo (forward test) del circuito de órdenes de Scalping en una cuenta DEMO micro ($50-100).

Abre 0.01 lotes a mercado con SL 25 pips / TP 50 pips (1:2), prueba mover el SL a break-even,
cierra la posición y deja un reporte. Usa un MAGIC propio y su propio log para no mezclarse con
el bot en vivo; las órdenes pasan por las mismas funciones del bot (can_open_trade, open_trade).

Uso (desde la raíz):  python xauusd_scalping_bot/test_runner.py [--side BUY|SELL] [--max-spread 40] [--retries 12]
"""
import argparse
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))        # para 'import bot_engine'
sys.path.insert(0, str(HERE))               # 'import config' = el de este bot (carga .env con python-dotenv)

import MetaTrader5 as mt5
import config

PIP = 10                # puntos por pip en XAUUSD de 2 decimales: 2 pips = 20 puntos
SL_PIPS, TP_PIPS = 25, 50
LOT = 0.01
TEST_MAGIC = 20260699   # distinto al del bot (…621): la prueba no cuenta en su riesgo ni en sus resúmenes


def levels(side: str, price: float, point: float):
    """SL y TP a 25 y 50 pips del precio de entrada."""
    d = 1 if side == "BUY" else -1
    return price - d * SL_PIPS * PIP * point, price + d * TP_PIPS * PIP * point


def resolve_symbol(base: str):
    """XAUUSD tal cual, o la variante del broker (XAUUSD.pro, XAUUSDm, GOLD…)."""
    if mt5.symbol_info(base):
        return base
    names = [s.name for s in mt5.symbols_get() or [] if s.name.upper().startswith((base.upper(), "GOLD"))]
    return min(names, key=len) if names else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--side", choices=("BUY", "SELL"), default="BUY")
    ap.add_argument("--max-spread", type=float, default=40, help="spread máximo en puntos (40 = 4 pips, = MAX_SPREAD_POINTS del bot)")
    ap.add_argument("--retries", type=int, default=12, help="reintentos de 5 s si el spread está alto")
    a = ap.parse_args()

    rep = {"Conexión": "FALLÓ", "Balance": "-", "Margen 0.01 lotes": "-", "Latencia broker": "-",
           "Colocación": "no ejecutada", "Break-even": "no ejecutada", "Cuenta limpia": "-"}
    path = os.getenv("MT5_PATH")
    if not (mt5.initialize(path=path) if path else mt5.initialize()):
        print(f"❌ mt5.initialize() falló: {mt5.last_error()}")
        sys.exit(1)
    try:
        if config.MT5_LOGIN and not mt5.login(config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER):
            print(f"❌ Login fallido: {mt5.last_error()}")
            sys.exit(1)
        acc = mt5.account_info()
        if acc is None or acc.trade_mode != mt5.ACCOUNT_TRADE_MODE_DEMO:
            print("⛔ La cuenta no es DEMO (o no se pudo leer): prueba abortada por seguridad del capital.")
            sys.exit(1)
        rep["Conexión"] = f"OK · demo #{acc.login} @ {acc.server}"
        rep["Balance"] = f"${acc.balance:.2f} {acc.currency} (equity {acc.equity:.2f}, margen libre {acc.margin_free:.2f})"
        micro = 50 <= acc.balance <= 100
        print(f"Balance detectado: ${acc.balance:.2f} {acc.currency}"
              + (" · capital micro objetivo" if micro else " · ⚠ fuera del rango micro $50-100; la prueba sigue"))

        sym = resolve_symbol(config.SYMBOL)
        if sym is None or not mt5.symbol_select(sym, True):
            print(f"❌ No se encontró el oro ({config.SYMBOL}/GOLD) en el broker: {mt5.last_error()}")
            sys.exit(1)
        info = mt5.symbol_info(sym)
        # El motor lee símbolo, magic y log del config al importarse: se fijan antes
        config.SYMBOL, config.MAGIC_NUMBER, config.LOG_FILE = sym, TEST_MAGIC, str(HERE / "test_runner.log")
        from bot_engine.risk_manager import can_open_trade
        from bot_engine.trade_manager import open_trade, close_trade, _modify_sl

        for i in range(a.retries + 1):
            tick = mt5.symbol_info_tick(sym)
            spread = (tick.ask - tick.bid) / info.point if tick else float("inf")
            if tick:
                print(f"{sym} Bid {tick.bid:.{info.digits}f} | Ask {tick.ask:.{info.digits}f} | "
                      f"spread {spread:.0f} pts = {spread / PIP:.1f} pips")
            if spread <= a.max_spread:
                break
            if i < a.retries:
                print(f"⚠  Spread {spread:.0f} pts > {a.max_spread:.0f}: pausa 5 s y reintento ({i + 1}/{a.retries})")
                time.sleep(5)
        else:
            rep["Colocación"] = f"no ejecutada: spread {spread:.0f} pts > {a.max_spread:.0f} tras {a.retries} reintentos"
            sys.exit(2)

        buy = a.side == "BUY"
        price = tick.ask if buy else tick.bid
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL, sym, LOT, price)
        rep["Margen 0.01 lotes"] = f"${margin:.2f}" if margin is not None else f"no calculado: {mt5.last_error()}"
        ok, why = can_open_trade(a.side, sym)
        if not ok:
            rep["Colocación"] = f"bloqueada por el control de riesgo: {why}"
            sys.exit(3)

        sl, tp = levels(a.side, price, info.point)
        t0 = time.perf_counter()
        ticket = open_trade(a.side, sl, tp, LOT, info, "test_runner", sym)
        ms = (time.perf_counter() - t0) * 1000
        rep["Latencia broker"] = f"ping {mt5.terminal_info().ping_last / 1000:.0f} ms · ida y vuelta de la orden {ms:.0f} ms"
        if not ticket:
            rep["Colocación"] = "FALLÓ (retcode ≠ 10009, detalle en test_runner.log)"
            sys.exit(4)
        pos = next((p for p in mt5.positions_get(symbol=sym) or [] if p.magic == TEST_MAGIC), None)
        if pos is None:
            rep["Colocación"] = f"orden #{ticket} aceptada, pero la posición no aparece (¿cerró ya por SL/TP?)"
            sys.exit(4)
        rep["Colocación"] = (f"OK (retcode 10009) · #{pos.ticket} {a.side} {LOT} @ {pos.price_open:.{info.digits}f} "
                             f"SL {pos.sl:.{info.digits}f} TP {pos.tp:.{info.digits}f}")
        try:
            # Se envía tal cual lo pidió el usuario; recién abierta, el SL en la entrada suele quedar del lado
            # equivocado del precio (el spread ya está en contra) y MT5 lo rechaza con Invalid Stops.
            if _modify_sl(pos.ticket, pos.price_open, pos.tp, info.digits):
                rep["Break-even"] = f"OK: SL movido a la entrada {pos.price_open:.{info.digits}f}"
            else:
                tick = mt5.symbol_info_tick(sym)
                mid = (pos.sl + (tick.bid if buy else tick.ask)) / 2      # siempre del lado válido
                ok2 = _modify_sl(pos.ticket, mid, pos.tp, info.digits)
                rep["Break-even"] = (f"SL en la entrada RECHAZADO por MT5 (Invalid Stops: el precio aún no avanzó 1:1); "
                                     f"modificar el SL a {mid:.{info.digits}f}: {'OK' if ok2 else 'FALLÓ'}")
        finally:
            closed = close_trade(pos.ticket, info) or not mt5.positions_get(ticket=pos.ticket)
            rep["Cuenta limpia"] = "OK, posición de prueba cerrada" if closed else f"⚠ CERRAR A MANO la posición #{pos.ticket}"
    finally:
        print("\n══════ REPORTE test_runner ══════")
        for k, v in rep.items():
            print(f"  {k:<18} {v}")
        mt5.shutdown()


if __name__ == "__main__":
    main()
