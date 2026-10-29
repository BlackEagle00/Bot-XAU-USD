"""
Pruebas del motor (riesgo, límite diario, trailing, hora del servidor).
No necesita el terminal MT5 abierto: usa objetos falsos.

Uso (desde la raíz del repo):  python tests/test_engine.py
"""
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "xauusd_scalping_bot"))   # config del oro scalping
os.chdir(tempfile.gettempdir())                          # el logger crea su .log aquí, no en el repo

import MetaTrader5 as mt5
from bot_engine import data_handler as dh, risk_manager as rm, trade_manager as tm
from bot_engine import coordinator as co, journal

_TMP = Path(tempfile.mkdtemp(prefix="bot_test_"))
co.STATE_DIR, journal.PATH = _TMP / "state", _TMP / "journal.jsonl"   # el estado y el diario de prueba no tocan los del bot

rm._cfg.ENFORCE_CAPITAL_LEVEL = True   # las pruebas miden el bloqueo; el modo informativo tiene su propia prueba
rm._cfg.DAILY_LOSS_ALERT_ONLY = False  # ídem: el corte diario; el modo alerta (scalping) tiene su propia prueba
rm.MAX_OPEN_TRADES = 3                 # las pruebas de niveles asumen 3; la cuenta real usa 1 (config 2026-10-27)

SYM = NS(trade_tick_size=0.01, trade_tick_value=1.0, volume_step=0.01,
         volume_min=0.01, volume_max=100.0, digits=2, point=0.01, trade_stops_level=0)


def test_lot_uses_real_sl_and_rounds_down():
    acc = NS(balance=10_000, equity=10_000)                    # riesgo 1% = $100
    assert rm.calculate_lot(acc, SYM, 4.39) == 0.22            # 0.2278 → abajo, no 0.23
    assert rm.calculate_lot(acc, SYM, 8.78) == 0.11            # SL más ancho → lote menor


def test_small_account_trades_min_lot_up_to_5pct_risk():
    real = getattr(rm._cfg, "MAX_RISK_MIN_LOT", None)
    rm._cfg.MAX_RISK_MIN_LOT = 0.05                             # el mecanismo con un tope del 5%
    try:
        _small_account_checks()
    finally:
        rm._cfg.MAX_RISK_MIN_LOT = real


def test_micro_account_fits_sl_to_trade_from_50_usd():
    keys = {"MICRO_SL_FIT": True, "MAX_RISK_MIN_LOT": 0.10, "MICRO_MIN_SL_ATR": 0.5,   # el mecanismo, no el config
            "MIN_LOT_CAP_HARD": False}
    real = {k: getattr(rm._cfg, k, None) for k in keys}
    vars(rm._cfg).update(keys)
    try:
        _micro_checks()
    finally:
        vars(rm._cfg).update(real)


def _micro_checks():
    acc = NS(balance=50, equity=50)                            # $50, tope 10%, SL mínimo 0.5×ATR
    assert rm.lot_plan(acc, SYM, 9.0)[0] == 0.0                # SL normal 1.5×ATR(6) = $9 → no cabe
    sl, tp = rm.fit_sl_to_capital("BUY", 4000.0, 3991.0, 4018.0, acc, SYM, 6.0)
    assert 4.9 < 4000.0 - sl <= 4.975 and abs((tp - 4000.0) / (4000.0 - sl) - 2.0) < 0.01   # mismo R:R 2:1
    assert rm.lot_plan(acc, SYM, 4000.0 - sl)[0] == 0.01       # ahora el lote mínimo cabe (≤ 10%)
    assert rm.fit_sl_to_capital("BUY", 4000.0, 3982.0, 4036.0, acc, SYM, 12.0) is None   # SL < 0.5×ATR: no
    rm._cfg.ENFORCE_CAPITAL_LEVEL = False                        # informativo: el mínimo pasa, pero el SL igual se acerca
    try:
        assert rm.lot_plan(acc, SYM, 9.0)[0] == 0.01 and rm.over_min_lot_cap(acc, SYM, 9.0)   # 0.01 arriesga 18 % > 10 %
        assert not rm.over_min_lot_cap(NS(balance=10_000, equity=10_000), SYM, 9.0)        # cuenta grande: 1 %, no se toca
        assert rm.fit_sl_to_capital("BUY", 4000.0, 3991.0, 4018.0, acc, SYM, 6.0) == (sl, tp)
    finally:
        rm._cfg.ENFORCE_CAPITAL_LEVEL = True


def _small_account_checks():
    acc = NS(balance=100, equity=100)
    lot, need = rm.lot_plan(acc, SYM, 4.39)                    # 0.01 lote arriesga $4.39 = 4.4%
    assert lot == 0.01 and abs(need - 439) < 1e-6              # con $439 vuelve al 1%
    assert abs(rm.lot_risk_pct(acc, SYM, 4.39, lot) - 0.0439) < 1e-9
    lot, need = rm.lot_plan(acc, SYM, 8.78)                    # 8.8% > 5% → no opera
    assert lot == 0.0 and abs(need - 175.6) < 1e-6             # capital mínimo para operarlo al 5%
    assert rm.calculate_lot(acc, SYM, 8.78) == 0.0


def test_capital_level_informative_trades_min_lot_without_tier_limits():
    rm._cfg.ENFORCE_CAPITAL_LEVEL = False
    hard = getattr(rm._cfg, "MIN_LOT_CAP_HARD", False)
    rm._cfg.MIN_LOT_CAP_HARD = False
    try:
        lot, need = rm.lot_plan(NS(balance=50, equity=50), SYM, 64.0)    # stop swing ≈ 64 USD con 50 USD
        assert lot == 0.01 and abs(need - 6400) < 1e-6                  # opera al mínimo; 1 % con ≥ 6 400
        tier = rm.capital_tier(50)
        assert tier["name"] == "Micro" and tier["max_open"] == rm.MAX_OPEN_TRADES             and tier["daily_loss"] == rm.MAX_DAILY_LOSS_PCT             # el nombre informa, no limita
        from bot_engine import grid
        cfg = NS(GRID_LEVELS=5, GRID_SPACING_ATR=1.0, GRID_TRADE_TP_ATR=1.0, GRID_STOP_BEYOND_ATR=1.0,
                 GRID_LOT_MODE="fixed", GRID_LOT_MULT=1.0, GRID_RISK_PCT=0.02, GRID_MAX_RISK_MIN_LOT=0.06,
                 GRID_BASKET_TP_R=0.5, ENFORCE_CAPITAL_LEVEL=False)
        b = grid.build_basket("BUY", 4000.0, 20.0, 50.0, SYM, 100.0, cfg)  # 1 nivel arriesga 20 USD = 40 %
        assert b and len(b["levels"]) == 1 and b["levels"][0]["lot"] == 0.01
        cfg.ENFORCE_CAPITAL_LEVEL = True
        assert grid.build_basket("BUY", 4000.0, 20.0, 50.0, SYM, 100.0, cfg) is None
    finally:
        rm._cfg.ENFORCE_CAPITAL_LEVEL = True
        rm._cfg.MIN_LOT_CAP_HARD = hard


def test_min_lot_hard_cap_rejects_without_tier_limits():
    saved = rm._cfg.ENFORCE_CAPITAL_LEVEL, getattr(rm._cfg, "MIN_LOT_CAP_HARD", False), rm._cfg.MAX_RISK_MIN_LOT
    rm._cfg.ENFORCE_CAPITAL_LEVEL, rm._cfg.MIN_LOT_CAP_HARD, rm._cfg.MAX_RISK_MIN_LOT = False, True, 0.15
    try:
        acc = NS(balance=57.72, equity=57.72)
        assert rm.lot_plan(acc, SYM, 17.7)[0] == 0.0          # SL 17.7 USD = 31 % > 15 % → TRADE_REJECTED
        assert rm.lot_plan(acc, SYM, 7.5)[0] == 0.01          # SL 7.5 USD = 13 % → entra al mínimo
        assert rm.capital_tier(57.72)["daily_loss"] == rm.MAX_DAILY_LOSS_PCT   # sin niveles de cuenta
    finally:
        rm._cfg.ENFORCE_CAPITAL_LEVEL, rm._cfg.MIN_LOT_CAP_HARD, rm._cfg.MAX_RISK_MIN_LOT = saved


def test_open_trade_blocks_spread_abuse_at_send():
    saved = mt5.order_send, tm.get_tick
    sent = []
    mt5.order_send = lambda req: sent.append(req)
    tm.get_tick = lambda *a, **k: NS(ask=4000.45, bid=4000.0)                # 45 pts ≥ MAX_SPREAD_POINTS (40)
    try:
        assert tm.open_trade("BUY", 3990.0, 4020.0, 0.01, SYM) is None and not sent
    finally:
        mt5.order_send, tm.get_tick = saved


def test_anomalous_m1_bar_uses_only_past_bars():
    import numpy as np
    from bot_engine.indicators import anomalous_bars
    h, l = np.full(40, 1.0), np.zeros(40)
    h[30], h[35] = 4.0, 2.0                                                  # 4× y 2× la media de 20
    f = anomalous_bars(h, l, 3.0, 20)
    assert list(np.where(f)[0]) == [30]
    h2 = h.copy(); h2[38] = 50.0                                             # cambiar el futuro…
    assert (anomalous_bars(h2, l, 3.0, 20)[:38] == f[:38]).all()             # …no cambia el pasado


def test_sim_parallel_never_sends_orders_and_sizes_per_balance():
    import importlib
    keep = {f: getattr(mt5, f, None) for f in ("order_send", "order_check", "order_send_async", "positions_get")}
    hard = getattr(rm._cfg, "MIN_LOT_CAP_HARD", False)
    sys.path.insert(0, str(ROOT / "sim_parallel"))
    try:
        sp = importlib.import_module("sim_parallel")
        for f in keep:                                                       # el módulo anula las órdenes al importarse
            try:
                getattr(mt5, f)()
                raise AssertionError(f"{f} no está anulada")
            except RuntimeError:
                pass
        rm._cfg.MIN_LOT_CAP_HARD = True
        vt = {"spread_multiplier": 1.0, "fixed_spread_offset_points": 0}
        d = sp.decide(100, vt, "BUY", 4000.0, 4000.10, 11.8, SYM)            # SL 17.7 > 15 % de 100
        assert d["estado"] == "TRADE_REJECTED" and d["lot"] == 0
        d = sp.decide(5000, vt, "SELL", 4000.0, 4000.10, 20 / 3, SYM)        # SL 10 → 1 % de 5 000 = 0.05 lote
        assert d["estado"] == "EJECUTADA" and d["lot"] == 0.05 and d["entry"] == 4000.0
        d = sp.decide(5000, {"spread_multiplier": 5.0}, "BUY", 4000.0, 4000.10, 10, SYM)   # 10 pts × 5 = 50 ≥ 40
        assert d["estado"] == "SIGNAL_BLOCKED"
        pos = {"side": "BUY", "entry": 100.0, "sl": 99.0, "tp": 102.0, "t0": 0}
        assert sp.walk(pos, [(0, 100.5, 99.5, 100, 10), (60, 103, 98.5, 101, 10)], 0.01, vt, 7200)[:2] == (99.0, "SL")
        assert sp.walk(pos, [(0, 100.5, 99.5, 100.2, 10)], 0.01, vt, 60)[:2] == (100.2, "TIEMPO")
        sell = {"side": "SELL", "entry": 100.0, "sl": 101.0, "tp": 98.0, "t0": 0}
        assert sp.walk(sell, [(0, 100.95, 99.5, 100, 10)], 0.01, vt, 7200)[:2] == (101.0, "SL")   # ASK = high + spread
    finally:
        for f, v in keep.items():
            setattr(mt5, f, v) if v else delattr(mt5, f)
        rm._cfg.MIN_LOT_CAP_HARD = hard


def test_account_daily_loss_blocks_all_bots():
    day = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    rm._halt_day = None
    rm.server_now = lambda: day
    rm.get_account_info = lambda: NS(balance=1_000, equity=1_000)
    rm.get_total_daily_pnl = lambda: -50.0                      # este bot: −5% (< su límite)
    rm.get_account_daily_pnl = lambda: -120.0                   # toda la cuenta: −12% ≥ 10%
    assert rm.is_daily_loss_exceeded()
    rm._halt_day = None
    rm.get_account_daily_pnl = lambda: -60.0
    assert not rm.is_daily_loss_exceeded()


def test_model_manifest_rejects_tampered_file():
    from bot_engine import ml_filter as ml
    tmp = Path(tempfile.mkdtemp())
    real_manifest, ml.MANIFEST = ml.MANIFEST, tmp / "manifest.json"
    try:
        f = tmp / "m.joblib"
        f.write_bytes(b"modelo de confianza")
        ml.register(f)
        assert ml._trusted(f)
        f.write_bytes(b"modelo alterado")                       # mismo nombre, otro contenido
        assert not ml._trusted(f) and ml.load(f) is None        # no se abre (ni se des-picklea)
        assert not ml._trusted(tmp / "otro.joblib")
    finally:
        ml.MANIFEST = real_manifest


def test_lot_is_dynamic_with_capital():
    lot, need = rm.lot_plan(NS(balance=10_000, equity=10_000), SYM, 4.39)
    assert lot == 0.22 and abs(need - 10_097) < 1e-6           # 0.23 lote necesita $10,097
    assert rm.lot_plan(NS(balance=10_100, equity=10_100), SYM, 4.39)[0] == 0.23   # creció → sube
    assert rm.lot_plan(NS(balance=10_000, equity=5_000), SYM, 4.39)[0] == 0.11    # pérdida abierta → baja
    big = NS(balance=10**9, equity=10**9)
    assert rm.lot_plan(big, SYM, 4.39) == (3.0, None)          # tope MAX_LOT, sin siguiente escalón


def test_lot_uses_real_tick_value_not_declared():
    # Oro en MetaQuotes-Demo: declara tick_value 0.1 pero paga 1.0 por tick y lote
    gold = NS(name="XAUUSD", bid=4000.0, trade_tick_size=0.01, trade_tick_value=0.1,
              volume_step=0.01, volume_min=0.01, volume_max=100.0)
    real = rm.mt5
    rm.mt5 = NS(ORDER_TYPE_BUY=0, order_calc_profit=lambda *a: 1.0)
    try:
        lot, need = rm.lot_plan(NS(balance=10_000, equity=10_000), gold, 4.39)
        assert lot == 0.22                                     # con 0.1 habría dado 2.27 (10× el riesgo)
        cap = rm._cfg.MAX_RISK_MIN_LOT                         # riesgo real 0.01 × dist × 1.0 USD sobre 100 USD
        assert rm.lot_plan(NS(balance=100, equity=100), gold, cap * 100 + 2.11)[0] == 0.0   # por encima del tope
    finally:
        rm.mt5 = real


def test_daily_loss_latches_until_next_day():
    day1 = datetime(2026, 10, 14, 15, tzinfo=timezone.utc)
    limit = rm.MAX_DAILY_LOSS_PCT * 10_000                      # límite en $ según el config
    pnl = {"v": -(limit + 100)}
    rm._halt_day = None
    rm.server_now = lambda: day1
    rm.get_account_info = lambda: NS(balance=10_000)
    rm.get_total_daily_pnl = lambda: pnl["v"]
    assert rm.is_daily_loss_exceeded()                          # pasó el límite
    pnl["v"] = -(limit - 100)
    assert rm.is_daily_loss_exceeded()                          # mejoró, pero sigue bloqueado hoy
    rm.server_now = lambda: day1.replace(day=15)
    assert not rm.is_daily_loss_exceeded()                      # día nuevo → libera


def test_daily_loss_alert_only_warns_without_blocking():
    day, sent = datetime(2026, 10, 20, 15, tzinfo=timezone.utc), []
    limit = rm.MAX_DAILY_LOSS_PCT * 10_000
    pnl = {"v": -limit * 0.85}
    saved = (rm.server_now, rm.get_account_info, rm.get_total_daily_pnl, rm.get_account_daily_pnl, rm.notify)
    rm._halt_day, rm._alerted = None, set()
    rm.server_now, rm.get_account_info = (lambda: day), (lambda: NS(balance=10_000))
    rm.get_total_daily_pnl, rm.get_account_daily_pnl = (lambda: pnl["v"]), (lambda: 0.0)
    rm.notify = lambda m, **k: sent.append(m)
    rm._cfg.DAILY_LOSS_ALERT_ONLY = True
    try:
        assert not rm.is_daily_loss_exceeded() and len(sent) == 1 and "cerca" in sent[0]       # 85 % del límite
        assert not rm.is_daily_loss_exceeded() and len(sent) == 1                              # una vez por umbral
        pnl["v"] = -limit * 1.2
        assert not rm.is_daily_loss_exceeded() and len(sent) == 2 and "SUPERADO" in sent[1]   # no corta: decide el usuario
    finally:
        rm.server_now, rm.get_account_info, rm.get_total_daily_pnl, rm.get_account_daily_pnl, rm.notify = saved
        rm._cfg.DAILY_LOSS_ALERT_ONLY = False


def test_positions_close_after_max_hold_minutes():
    closed, now = [], 1_800_000_000
    old, new = NS(ticket=1, time=now - 3600, profit=-1.0), NS(ticket=2, time=now - 600, profit=0.5)
    saved = (tm.get_open_positions, tm.server_now, tm.close_trade, tm.update_breakeven, tm.update_trailing_stop,
             getattr(tm._cfg, "MAX_HOLD_MINUTES", None))
    tm.get_open_positions = lambda *a, **k: [old, new]
    tm.server_now = lambda: datetime.fromtimestamp(now, tz=timezone.utc)
    tm.close_trade = lambda t, info: closed.append(t) or True
    tm.update_breakeven = tm.update_trailing_stop = lambda *a: False
    tm._cfg.MAX_HOLD_MINUTES = 30
    try:
        tm.manage_open_trades(1.0, SYM)
        assert closed == [1]                                       # 60 min ≥ 30: se cierra; la de 10 min sigue
    finally:
        (tm.get_open_positions, tm.server_now, tm.close_trade, tm.update_breakeven, tm.update_trailing_stop,
         tm._cfg.MAX_HOLD_MINUTES) = saved


def test_backtest_time_stop_exits_by_time():
    import numpy as np
    bt = _backtest_module()
    n = 10
    arr = (np.full(n, 100.0), np.full(n, 100.05), np.full(n, 99.95), np.full(n, 100.0), np.zeros(n))
    out = bt.make_outcome(arr, np.full(n, 1.0), SYM, rm, tm, max_bars=2)(0, bt.BUY, 1.5, 3.0)
    assert out[4] == "TIEMPO" and out[1] == 2                      # entra en la vela 1, sale al cierre de la 2



def test_backtest_skips_entry_when_spread_at_or_over_max():
    import numpy as np
    bt = _backtest_module()
    n, saved = 10, getattr(rm._cfg, "MAX_SPREAD_POINTS", None)
    try:
        rm._cfg.MAX_SPREAD_POINTS = 40
        for spread, blocked in ((0.40, True), (0.39, False)):            # 40 / 39 puntos, como is_market_open (>=)
            arr = (np.full(n, 100.0), np.full(n, 100.05), np.full(n, 99.95), np.full(n, 100.0), np.full(n, spread))
            out = bt.make_outcome(arr, np.full(n, 10.0), SYM, rm, tm, max_bars=2)(0, bt.BUY, 1.5, 3.0)
            assert (out == "spread") == blocked
    finally:
        rm._cfg.MAX_SPREAD_POINTS = saved


def test_open_trade_plays_sound_only_on_success():
    import winsound
    played, saved = [], (winsound.PlaySound, mt5.order_send, tm.get_tick, tm.notify)
    winsound.PlaySound = lambda *a: played.append(a)
    tm.get_tick = lambda *a, **k: NS(ask=4000.1, bid=4000.0)
    tm.notify = lambda *a, **k: None
    _fresh_co()
    restore = _mt5(order_check=lambda r: NS(retcode=0, comment="Done"),
                   positions_get=lambda **k: [_pos(7, sl=3990.0)])
    try:
        mt5.order_send = lambda req: NS(retcode=mt5.TRADE_RETCODE_DONE, order=7, comment="")
        assert tm.open_trade("BUY", 3990.0, 4020.0, 0.01, SYM) == 7 and len(played) == 1
        mt5.order_send = lambda req: NS(retcode=10016, order=0, comment="Invalid stops")
        assert tm.open_trade("SELL", 4010.0, 3980.0, 0.01, SYM) is None and len(played) == 1
    finally:
        winsound.PlaySound, mt5.order_send, tm.get_tick, tm.notify = saved
        restore()
        _fresh_co()


def test_closed_position_plays_sound_even_without_telegram():
    import winsound
    from bot_engine import telegram_notifier as tn
    played, saved = [], (winsound.PlaySound, tn._seen, tn._enabled)
    winsound.PlaySound = lambda *a: played.append(a)
    tn._seen, tn._enabled = None, False
    try:
        pos = NS(ticket=5, type=mt5.ORDER_TYPE_BUY, volume=0.01, price_open=4000.0)
        tn.check_closed_positions([pos])                  # primer ciclo: solo memoriza
        tn.check_closed_positions([pos])                  # sigue abierta: nada
        assert not played
        tn.check_closed_positions([])                     # desapareció → cerrada
        assert len(played) == 1 and ("alert2.wav" in str(played[0][0]) or played[0][0] == "SystemExclamation")
    finally:
        winsound.PlaySound, tn._seen, tn._enabled = saved

def test_trailing_does_not_tighten_while_losing():
    moves = []
    tm._modify_sl = lambda ticket, sl, tp, digits: moves.append(sl) or True
    atr = 4.623
    sell = NS(ticket=1, type=mt5.ORDER_TYPE_SELL, price_open=4138.84, sl=4145.42,
              tp=4124.62, price_current=4138.00)
    assert not tm.update_trailing_stop(sell, atr, SYM) and not moves   # caso real del log
    sell.price_current = 4130.00                                       # ya en ganancia
    assert tm.update_trailing_stop(sell, atr, SYM)
    assert moves[-1] <= sell.price_open

    buy = NS(ticket=2, type=mt5.ORDER_TYPE_BUY, price_open=4000.0, sl=3993.0,
             tp=4014.0, price_current=4000.5)
    assert not tm.update_trailing_stop(buy, atr, SYM)


def _backtest_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("engine_backtest", ROOT / "backtesting" / "engine_backtest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backtest_never_sees_forming_candles():
    bt = _backtest_module()
    import numpy as np
    h1_open = np.array([0, 3600, 7200, 10800], dtype=np.int64)
    closes = bt.close_times(h1_open, "H1")                    # 3600, 7200, 10800, 14400
    assert bt.closed_upto(closes, 7200) == 2                    # al cierre de las 02:00 → 2 velas cerradas
    assert bt.closed_upto(closes, 7199) == 1                    # 1 s antes, la 2.ª aún se forma
    weekend = bt.close_times(np.array([0, 4 * 86400], dtype=np.int64), "D1")
    assert weekend[0] == 86400                                  # el hueco del finde no alarga la vela


def test_backtest_exits_are_conservative():
    bt = _backtest_module()
    # vela que toca SL y TP → SL
    assert bt.exit_price(bt.BUY, 100, 110, 90, 0.0, sl=95, tp=105) == 95
    assert bt.exit_price(bt.SELL, 100, 110, 90, 0.0, sl=105, tp=95) == 105
    # SELL cierra en ASK: con spread 1, un high de 104.5 ya toca un SL de 105
    assert bt.exit_price(bt.SELL, 100, 104.5, 99, 1.0, sl=105, tp=90) == 105
    # hueco de apertura más allá del SL → sale al precio de apertura (peor que el SL)
    assert bt.exit_price(bt.BUY, 93, 94, 92, 0.0, sl=95, tp=105) == 93
    # entrada con spread: BUY paga el ask
    assert bt.entry_price(bt.BUY, 100.0, 0.3) == 100.3 and bt.entry_price(bt.SELL, 100.0, 0.3) == 100.0


def test_dashboard_rejects_forged_orders():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dash_server", ROOT / "dashboard" / "server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    wl, tok, host = {"scalping": {"XAUUSD"}}, "secreto", f"127.0.0.1:{srv.PORT}"
    ok_body = b'{"symbol":"XAUUSD","action":"BUY","mode":"scalping"}'
    good = {"Host": host, "Origin": f"http://{host}", "X-Token": tok}
    check = lambda h, b=ok_body, last=None: srv.validate_trade_request(h, b, tok, wl, last or {}, 1000.0)[0]
    assert check(good) == 200
    assert check({**good, "X-Token": "otro"}) == 403                       # sin el token de la sesión
    assert check({**good, "Origin": "https://evil.example"}) == 403       # POST desde otra web
    assert check({**good, "Host": "evil.example:8765"}) == 403            # DNS rebinding
    assert check(good, b'{"symbol":"EURUSD","action":"BUY","mode":"scalping"}') == 400   # fuera de la lista
    assert check(good, b'{"symbol":"XAUUSD","action":"CLOSE_ALL","mode":"scalping"}') == 400
    assert check(good, b'[1,2]') == 400
    assert check(good, last={"XAUUSD": 998.0}) == 429                      # doble clic


def test_capital_tiers_change_behavior():
    names = [rm.capital_tier(c)["name"] for c in (0, 106, 499.99, 500, 1999, 2000, 50_000)]
    assert names == ["Micro", "Micro", "Micro", "Pequeño", "Pequeño", "Estándar", "Estándar"]
    assert rm.capital_tier(106)["max_open"] == 1 and rm.capital_tier(106)["daily_loss"] == 0.05
    assert rm.capital_tier(1000)["max_open"] == 2
    std = rm.capital_tier(10_000)                                # Estándar = valores del config
    assert std["max_open"] == rm.MAX_OPEN_TRADES and std["daily_loss"] == rm.MAX_DAILY_LOSS_PCT


def test_spread_must_be_small_vs_stop():
    assert rm.spread_ok(0.50, 4.0)                               # 12.5% del stop
    assert not rm.spread_ok(0.80, 2.0)                           # 40% del stop: se come la ventaja
    assert not rm.spread_ok(0.10, 0.0)


def test_ml_features_are_side_symmetric():
    from bot_engine import ml_filter as ml
    ip = dict(atr=2.0, rsi=55, adx=25, bb_pct=0.6, bb_width=0.01, macd_hist=0.4, ema50=99.0, ema200=95.0,
              volume=120, volume_ma=100)
    it = dict(atr=4.0, ema21=101.0, ema50=100.0)
    sig = {"score": 6.0, "breakdown": {"ema": 1.3, "rsi": 0.5}}
    buy = ml.features(1, 100.0, ip, it, None, sig, 0.3, 1_760_000_000)
    sell = ml.features(-1, 100.0, ip, it, None, sig, 0.3, 1_760_000_000)
    assert len(buy) == len(ml.FEATURE_NAMES)
    k = ml.FEATURE_NAMES.index
    assert buy[k("dist_ema50_atr")] == 0.5 and sell[k("dist_ema50_atr")] == -0.5   # a favor = positivo
    assert buy[k("rsi")] == sell[k("rsi")] and buy[k("side")] == 1 and sell[k("side")] == -1


def test_ml_filter_blocks_below_threshold():
    from bot_engine import ml_filter as ml
    bundle = {"tau": 0.8, "model": NS(predict_proba=lambda X: [[0.3, 0.7]])}
    assert ml.allows(bundle, [0.0]) == (False, 0.7)
    bundle["model"] = NS(predict_proba=lambda X: [[0.1, 0.9]])
    assert ml.allows(bundle, [0.0]) == (True, 0.9)
    assert ml.allows(None, [0.0]) == (True, None)                 # sin modelo, opera como siempre


def test_total_drawdown_cut_stops_new_trades():
    assert rm.dd_halted(70, 100, 0.30) and not rm.dd_halted(71, 100, 0.30)
    assert not rm.dd_halted(10, 100, None)                        # apagado por defecto
    bt = _backtest_module()
    import pandas as pd
    p = pd.DataFrame({"open": [100.0] * 6, "close": [100.0] * 6, "spread": [0] * 6, "time": [i * 3600 for i in range(6)]})
    fake = NS(capital_tier=lambda c: {"max_open": 5, "daily_loss": 99.0, "name": "T"}, lot_plan=lambda *a: (0.1, None),
              micro_sl_distance=lambda *a: None, dd_halted=rm.dd_halted)
    loss = lambda k: (bt.BUY, -1.0, k, 100.0, 80.0, "SL", 10.0)    # cada una pierde 20 × 0.1 × 100 = 200 USD
    cands = {1: loss(1), 2: loss(2), 3: loss(3), 4: loss(4)}
    run = lambda cut: bt.simulate(cands, p, NS(point=0.01), 100.0, NS(USE_ANTI_DUPLICATE=False, MAX_DD_PCT=cut), fake, 1000.0, 0)
    trades, _, blocked = run(0.30)
    assert len(trades) == 2 and blocked["dd_halt"] == 2            # 1000 → 600 (−40%): no abre más
    assert len(run(None)[0]) == 4                                  # sin corte, sigue operando


def test_small_account_rule_rejects_burning_caps():
    import importlib.util
    spec = importlib.util.spec_from_file_location("small_account", ROOT / "backtesting" / "small_account.py")
    sa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sa)
    s = sa.stats([(10.0, 80.0, 5), (150.0, 20.0, 5)], 100)        # un arranque se quema, otro gana
    assert s["p_burn"] == 0.5 and s["p_loss"] == 0.5 and s["traded"] == 1.0
    safe = {"p_burn": 0.1, "ret_p50": 20.0, "traded": 1.0}
    hot = {"p_burn": 0.4, "ret_p50": 90.0, "traded": 1.0}
    assert sa.choose({"0.1|None": {"50": safe, "100": safe}, "0.5|None": {"50": hot, "100": hot}}) == ("0.1|None", True)
    assert sa.choose({"0.5|None": {"50": hot, "100": hot}}) == ("0.5|None", False)   # el menos malo, marcado


def test_walk_forward_never_trains_on_the_future():
    bt = _backtest_module()
    import numpy as np
    t_dec = np.array([100, 200, 300, 400])
    t_exit = np.array([150, 450, 350, 500])                      # la 2.ª se decidió antes pero termina después
    assert bt.train_mask(t_dec, t_exit, 400).tolist() == [True, False, True, False]
    folds = list(bt.wf_folds(0, 1000 * 86400))
    assert folds[0][0] == int(1000 * 86400 * bt.FIRST_TEST)      # la prueba empieza tras el 40%
    assert all(a < b for a, b in folds) and folds[-1][1] == 1000 * 86400


def test_pick_tau_requires_high_win_rate_and_profit():
    bt = _backtest_module()
    import numpy as np
    p = np.linspace(0.4, 0.99, 200)
    r = np.where(p > 0.7, 0.5, -1.0)                              # solo las de alta P ganan
    tau, total = bt.pick_tau(p, r)
    sel = p >= tau
    assert (r[sel] > 0).mean() >= bt.VAL_WIN and total > 0
    assert bt.pick_tau(p, np.full(200, -1.0)) is None             # nada gana → sin umbral


def test_threshold_applied_later_matches_engine():
    """calibrate.py corre el motor una vez con umbral ≈ 0 y aplica el umbral después: debe coincidir."""
    import numpy as np
    import pandas as pd
    from bot_engine import signals as sg, indicators as ind
    from bot_engine.patterns import analyze_patterns
    rng = np.random.default_rng(1)
    close = 2000 + np.cumsum(rng.normal(0, 2, 900))
    df = pd.DataFrame({"open": close + rng.normal(0, .5, 900), "high": close + 3, "low": close - 3,
                       "close": close, "volume": rng.integers(100, 1000, 900).astype(float)})
    real, checked = sg.MIN_SIGNAL_SCORE, 0
    try:
        for end in range(400, 900, 20):
            w = df.iloc[end - 400:end]
            price = float(w["close"].iloc[-1])
            ip, it = ind.calculate_all(w, price), ind.calculate_all(w.iloc[::3], price)
            pats = analyze_patterns(w, "neutral")
            sg.MIN_SIGNAL_SCORE = 0.01
            s0 = sg.generate_signal(price, ip, it, pats, ip["atr"], it)
            for thr in (3.0, 5.0, 7.0):
                sg.MIN_SIGNAL_SCORE = thr
                st = sg.generate_signal(price, ip, it, pats, ip["atr"], it)
                expected = s0["action"] if abs(s0["score"]) >= thr else "HOLD"
                assert st["action"] == expected, (end, thr, s0["score"], s0["action"], st["action"])
                checked += 1
    finally:
        sg.MIN_SIGNAL_SCORE = real
    assert checked == 75


def test_calibration_writes_profile_config():
    import importlib.util
    spec = importlib.util.spec_from_file_location("calibrate", ROOT / "backtesting" / "calibrate.py")
    cal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cal)
    text = (ROOT / "dashboard" / "profiles" / "xauusd_swing" / "config.py").read_text(encoding="utf-8")
    out = cal.apply_params(text, {"tf": "H4", "MIN_SIGNAL_SCORE": 6.0, "SL_ATR_MULT": 2.0}, "prueba")
    assert 'tf="H4"' in out and "    MIN_SIGNAL_SCORE=6.0,\n" in out and out.rstrip().endswith("))")
    again = cal.apply_params(out, {"tf": "H1", "MIN_SIGNAL_SCORE": 4.0}, "otra")
    assert again.count("MIN_SIGNAL_SCORE") == 1 and "SL_ATR_MULT" not in again and 'tf="H1"' in again
    ns = {}
    exec(compile(again.replace('Path(__file__)', f'Path(r"{ROOT / "dashboard" / "profiles" / "xauusd_swing" / "config.py"}")'),
                 "perfil", "exec"), ns)
    assert ns["MIN_SIGNAL_SCORE"] == 4.0 and ns["MODE"] == "swing"   # el config resultante es válido


def test_news_parser_rejects_unsafe_feeds():
    import importlib.util
    spec = importlib.util.spec_from_file_location("dash_server2", ROOT / "dashboard" / "server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    ok = (b"<rss><channel><item><title>Oro sube</title><link>https://ej.com/a</link>"
          b"<pubDate>Thu, 15 Oct 2026 12:00:00 GMT</pubDate><source>Reuters</source></item>"
          b"<item><title>Malo</title><link>javascript:alert(1)</link></item></channel></rss>")
    items = srv.parse_rss(ok, "Prueba")
    assert len(items) == 1 and items[0]["source"] == "Reuters" and items[0]["ts"] == 1792065600
    for bad in (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><rss/>', b"<rss>" + b"x" * 2_000_001):
        try:
            srv.parse_rss(bad, "Prueba")
            raise AssertionError("debía rechazarse")
        except ValueError:
            pass
    cal = srv.parse_calendar(b'[{"title":"NFP","country":"USD","impact":"High","date":"2026-10-16T08:30:00-04:00"},'
                             b'{"title":"x","impact":"Low","date":"2026-10-16T08:30:00-04:00"}]')
    assert [e["title"] for e in cal] == ["NFP"] and cal[0]["ts"] == 1792153800


# ── Grid + cesta (bot_engine/grid.py y engine_backtest.simulate_grid) ──────────
GCFG = dict(MIN_SIGNAL_SCORE=1.0, MIN_LOT=0.01, MAX_LOT=3.0, GRID_LOT_MODE="fixed", GRID_LOT_MULT=2.0,
            GRID_LEVELS=3, GRID_SPACING_ATR=1.0, GRID_TRADE_TP_ATR=1.0, GRID_STOP_BEYOND_ATR=1.0,
            GRID_RISK_PCT=0.03, GRID_MAX_RISK_MIN_LOT=0.06, GRID_BASKET_TP_R=0.5, GRID_MAX_MINUTES=10_000,
            GRID_FRIDAY_CLOSE_HOUR=22, GRID_BLOCK_HOURS=(), GRID_MAX_DD_PCT=0.9, ACCOUNT_MAX_DAILY_LOSS_PCT=0.5)
THU = 0                                    # 1970-01-01 00:00 fue jueves (hora del servidor en las velas)


def _grid_run(bars, sigs=((0, "BUY"),), balance=1000.0, t0=THU, **over):
    """Señales [(vela, lado)] → cesta en la apertura siguiente. bars = [(o, h, l, c)] tras una vela 100.
    Spread 0, $100 por 1.0 de precio y lote (oro), ATR 1."""
    import pandas as pd
    bt = _backtest_module()
    p = pd.DataFrame([(t0 + i * 60, *b, 0, 0) for i, b in enumerate([(100, 100, 100, 100)] + bars)],
                     columns=["time", "open", "high", "low", "close", "volume", "spread"])
    sig = pd.DataFrame([(i, side, 5.0, 1.0) for i, side in sigs], columns=["i", "action", "score", "atr"])
    return bt.simulate_grid(sig, p, SYM, 100.0, NS(**{**GCFG, **over}), rm, balance, 1, 1)


def test_grid_risk_sizing_grows_with_capital():
    from bot_engine import grid
    cfg = NS(**GCFG)
    b = grid.build_basket("BUY", 100.0, 1.0, 1000, SYM, 100.0, cfg)
    assert [x["price"] for x in b["levels"]] == [100.0, 99.0, 98.0] and b["sl"] == 97.0
    assert [x["lot"] for x in b["levels"]] == [0.05] * 3 and abs(b["risk_usd"] - 30) < 1e-9   # cesta llena = 3%
    assert abs(b["tp_usd"] - 15) < 1e-9 and [x["tp"] for x in b["levels"]] == [101.0, 100.0, 99.0]
    assert len(grid.build_basket("BUY", 100.0, 1.0, 100, SYM, 100.0, cfg)["levels"]) == 2      # menos niveles
    small = grid.build_basket("BUY", 100.0, 1.0, 50, SYM, 100.0, cfg)
    assert len(small["levels"]) == 1 and small["risk_usd"] <= 50 * 0.03                         # 1 nivel, 2%
    assert grid.build_basket("BUY", 100.0, 1.0, 10, SYM, 100.0, cfg) is None                    # ni 1 nivel cabe
    assert abs(grid.min_capital(1.0, SYM, 100.0, cfg) - 16.67) < 0.01
    assert grid.build_basket("BUY", 100.0, 1.0, 10_000, SYM, 100.0, cfg)["levels"][0]["lot"] == 0.5


def test_grid_martingale_keeps_total_risk():
    from bot_engine import grid
    b = grid.build_basket("SELL", 100.0, 2.0, 10_000, SYM, 100.0, NS(**{**GCFG, "GRID_LOT_MODE": "martingale"}))
    assert [x["price"] for x in b["levels"]] == [100.0, 102.0, 104.0] and b["sl"] == 106.0
    assert [x["lot"] for x in b["levels"]] == [0.13, 0.26, 0.52] and b["risk_usd"] <= 300 + 1e-9


def test_basket_decision_and_pnl():
    from bot_engine import grid
    cfg = NS(**GCFG)
    assert grid.basket_decision(15.0, 30, 5, cfg) == "TP" and grid.basket_decision(-30.0, 30, 5, cfg) == "STOP"
    assert grid.basket_decision(1.0, 30, 10_000, cfg) == "TIME" and grid.basket_decision(1.0, 30, 5, cfg) is None
    pos = [{"side": "BUY", "entry": 100.0, "lot": 0.1}, {"side": "SELL", "entry": 101.0, "lot": 0.1}]
    assert abs(grid.basket_pnl(pos, 100.5, 100.8, 100.0) - (5.0 + 2.0)) < 1e-9   # BUY al bid, SELL al ask
    assert grid.parse_comment("XAUg G1792153800 L3") == (1792153800, 3) and grid.parse_comment("XAU s+5.1") is None


def test_basket_realized_ignores_previous_basket_stop():
    from bot_engine import grid
    from config import MAGIC_NUMBER as M
    d = lambda pos, entry, profit, c="[sl]": NS(magic=M, entry=entry, position_id=pos, comment=c,
                                               profit=profit, swap=0.0, commission=0.0)
    deals = [d(1, 0, 0.0, "XAU G1793031942 L0"), d(1, 1, -2.79),                 # cesta anterior: su stop
             d(2, 0, 0.0, "XAU G1793031972 L0"), d(3, 0, 0.0, "XAU G1793031972 L1"), d(3, 1, 0.80)]   # cesta actual
    real = mt5.history_deals_get
    mt5.history_deals_get = lambda *a: deals
    try:
        assert abs(grid._realized_since(1793031972) - 0.80) < 1e-9 and abs(grid._realized_since(1793031942) + 2.79) < 1e-9
    finally:
        mt5.history_deals_get = real


def test_extra_basket_same_side_strong_signal_and_cap():
    from bot_engine import grid
    cfg = NS(GRID_MAX_BASKETS=3, GRID_EXTRA_SCORE=6.0, GRID_EXTRA_MIN_GAP=1.0)
    buy = [{"id": 1, "side": "BUY", "entry": 100.0}]
    assert grid.extra_basket_block("BUY", 4.1, [], cfg=cfg) is None                    # la 1.ª: sin exigencia extra
    assert grid.extra_basket_block("BUY", 6.5, buy, cfg=cfg) is None                   # misma dirección y fuerte
    assert "contraria" in grid.extra_basket_block("SELL", -9.0, buy, cfg=cfg)          # nunca BUY y SELL a la vez
    assert "debajo" in grid.extra_basket_block("BUY", 5.0, buy, cfg=cfg)               # extra con señal floja
    assert "Máximo" in grid.extra_basket_block("BUY", 9.0, buy * 3, cfg=cfg)
    assert grid.extra_basket_block("BUY", None, buy, cfg=cfg) is None                  # manual (panel)
    assert "separación" in grid.extra_basket_block("BUY", 7.0, buy, 102.0, 4.0, cfg)   # a 2 de la entrada: apilaría
    assert grid.extra_basket_block("BUY", 7.0, buy, 95.0, 4.0, cfg) is None            # a 5 (≥ 1 espaciado): escalona
    capped = NS(GRID_MAX_BASKETS=3, GRID_EXTRA_SCORE=4.0, GRID_MAX_SCORE=6.0)
    assert "extendida" in grid.extra_basket_block("BUY", 8.4, [], cfg=capped)           # también la 1.ª: no el techo
    assert "extendida" in grid.extra_basket_block("SELL", -6.5, [], cfg=capped)
    assert grid.extra_basket_block("BUY", 5.5, [], cfg=capped) is None


def test_baskets_are_tracked_and_closed_separately():
    from bot_engine import grid, data_handler as gdh, telegram_notifier as tn
    pos = lambda t, c, profit, sl: NS(ticket=t, comment=c, type=0, volume=0.01, price_open=100.0, sl=sl,
                                      profit=profit, swap=0.0)
    positions = [pos(1, "XAUg G1000 L0", -2.0, 98.0), pos(2, "XAUg G2000 L0", 0.1, 99.0)]
    closed, sent = [], []
    saved = (gdh.get_open_positions, gdh.get_pending_orders, gdh.server_now, grid._realized_since,
             grid.close_basket, gdh.get_account_info, gdh.get_tick, tn.notify)
    gdh.get_open_positions, gdh.get_pending_orders = (lambda *a: positions), (lambda *a: [])
    gdh.server_now, grid._realized_since = (lambda: datetime.fromtimestamp(2060, tz=timezone.utc)), (lambda ts: -4.6 if ts == 500 else 0.0)
    gdh.get_account_info, gdh.get_tick, tn.notify = (lambda: None), (lambda *a: None), (lambda m, **k: sent.append(m))
    grid.close_basket = lambda reason, info, sym, st: closed.append((st["id"], reason))
    grid._baskets[500] = {"side": "BUY", "levels": [], "sl": 95.0}                     # ya la cerró el SL del bróker
    try:
        b = grid.baskets(None, SYM)
        assert [(x["id"], x["side"], x["tickets"], round(x["risk_usd"], 2)) for x in b] == \
            [(1000, "BUY", [1], 2.0), (2000, "BUY", [2], 1.0)]                         # riesgo de cada una, no sumado
        grid.manage_basket(SYM)
        assert closed == [(1000, "STOP")]                                               # solo la que tocó su riesgo
        assert 500 not in grid._baskets and sent and "-4.60" in sent[0]                 # stop del bróker: se avisa
    finally:
        (gdh.get_open_positions, gdh.get_pending_orders, gdh.server_now, grid._realized_since,
         grid.close_basket, gdh.get_account_info, gdh.get_tick, tn.notify) = saved
        grid._baskets.clear()


def test_grid_calendar_and_drawdown_guards():
    from datetime import datetime
    from bot_engine import grid
    cfg = NS(**{**GCFG, "GRID_BLOCK_HOURS": (23, 0), "GRID_MAX_DD_PCT": 0.30})
    friday_22 = datetime(2026, 10, 23, 22, 0)
    assert not grid.entry_allowed(friday_22, cfg) and grid.must_flatten(friday_22, cfg)
    assert not grid.entry_allowed(datetime(2026, 10, 24, 10, 0), cfg)          # sábado
    assert not grid.entry_allowed(datetime(2026, 10, 21, 23, 30), cfg)         # corte diario
    assert grid.entry_allowed(datetime(2026, 10, 21, 10, 0), cfg)
    assert grid.dd_halt(700, 1000, cfg) and not grid.dd_halt(701, 1000, cfg)


def test_grid_range_closes_basket_in_profit():
    # entra 100; baja a 98.9 (llena el límite de 99), en la vela siguiente su TP (100) y luego el del nivel 0
    trades, _, _, baskets = _grid_run([(100, 100.5, 99.5, 100), (100, 100, 98.9, 100), (100, 101.2, 99.8, 101)],
                                      GRID_BASKET_TP_R=0.3)
    assert [b["reason"] for b in baskets] == ["CESTA_TP"] and abs(baskets[0]["pnl"] - 10.0) < 1e-6
    assert len(trades) == 2 and all(t["pnl"] > 0 for t in trades)


def test_grid_trend_against_loses_only_the_planned_risk():
    bars = [(100 - k, 100 - k, 99 - k, 99 - k) for k in range(8)]          # cae 1.0 por vela
    trades, _, _, baskets = _grid_run(bars)
    assert [b["reason"] for b in baskets] == ["CESTA_STOP"]
    assert abs(baskets[0]["pnl"] + 30.0) < 1e-6                             # exactamente el 3% planificado
    assert len(trades) == 3 and all(t["reason"] == "CESTA_STOP" for t in trades)


def test_grid_flash_crash_loses_only_the_planned_risk():
    _, _, _, baskets = _grid_run([(100, 100, 85, 99)])                      # una vela cae 15
    assert baskets[0]["reason"] == "CESTA_STOP" and abs(baskets[0]["pnl"] + 30.0) < 1e-6


def test_grid_pending_fills_only_when_touched():
    trades, _, _, baskets = _grid_run([(100, 100.2, 99.01, 100)] * 3 + [(100, 101, 100, 101)])
    assert baskets[0]["max_levels"] == 1 and len(trades) == 1               # 99.01 no toca el límite de 99


def test_grid_bar_touching_stop_and_tp_counts_as_stop():
    _, _, _, baskets = _grid_run([(100, 103, 97, 100)], GRID_LEVELS=1)
    assert baskets[0]["reason"] == "CESTA_STOP" and abs(baskets[0]["pnl"] + 30.0) < 1e-6


def test_grid_does_not_buy_the_low_and_sell_the_high_of_one_bar():
    # la vela toca 99 (llena el límite) y 100 (su TP): con OHLC no se sabe el orden → no cuenta esa ganancia
    trades, _, _, baskets = _grid_run([(100, 100, 98.9, 99.5)], GRID_BASKET_TP_R=0.1)
    assert not [t for t in trades if t["reason"] == "TP"]
    assert baskets[0]["reason"] == "TIEMPO" and abs(baskets[0]["pnl"]) < 1e-6   # con el sesgo: +5 y CESTA_TP


def test_grid_closes_before_the_weekend():
    friday_2158 = 86400 + 21 * 3600 + 58 * 60                              # 1970-01-02 (viernes) 21:58
    _, _, _, baskets = _grid_run([(100, 100.2, 99.8, 100)] * 3, t0=friday_2158)
    assert baskets[0]["reason"] == "FINDE"


def test_grid_drawdown_breaker_stops_new_baskets():
    bars = [(100 - k, 100 - k, 99 - k, 99 - k) for k in range(4)] + [(96, 96, 96, 96)] * 3
    _, _, blocked, baskets = _grid_run(bars, sigs=((0, "BUY"), (5, "BUY")), GRID_MAX_DD_PCT=0.02)
    assert [b["reason"] for b in baskets] == ["CESTA_STOP"] and blocked["halted"] == 1 and blocked["halted_at"]


def test_m1_and_grid_mode_supported():
    bt = _backtest_module()
    import numpy as np
    assert list(bt.close_times(np.array([0, 60], dtype=np.int64), "M1")) == [60, 120] and bt.TF_MAP["M1"] == ("M5", "M15")
    import importlib.util
    spec = importlib.util.spec_from_file_location("dash_server", ROOT / "dashboard" / "server.py")
    srv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(srv)
    host = f"127.0.0.1:{srv.PORT}"
    body = b'{"symbol":"XAUUSD","action":"SELL","mode":"swing"}'
    assert "grid" not in srv.MODES                                         # grid retirado del panel el 2026-10-26
    assert srv.validate_trade_request({"Host": host, "X-Token": "t"}, body, "t", {"swing": {"XAUUSD"}}, {}, 1000.0)[0] == 200


def test_grid_exec_tf_maps_signal_to_next_short_bar():
    """Grid "analiza H1, opera M1": la señal de la vela H1 entra en la 1.ª vela M1 tras su cierre, con el ATR M1."""
    import numpy as np
    import pandas as pd
    bt = _backtest_module()
    sig = pd.DataFrame([(0, "BUY", 5.0, 9.9), (1, "HOLD", 0.0, 9.9)], columns=["i", "action", "score", "atr"])
    x = pd.DataFrame({"time": np.arange(0, 7200, 60), "high": 101.0, "low": 99.0, "close": 100.0})
    out = bt.exec_signals(sig, np.array([3600, 7200]), x)
    assert list(out["i"]) == [59] and out["action"].iat[0] == "BUY"      # simulate_grid entra en la vela 60 (01:00)
    assert abs(out["atr"].iat[0] - 2.0) < 1e-9                             # ATR de ejecución, no el 9.9 del H1


def test_ml_filter_off_from_capital_threshold():
    from bot_engine import core
    saved = (core.ml_filter.bundle_for, core.get_account_info, getattr(core._cfg, "ML_FILTER_MAX_CAPITAL", None),
             getattr(core._cfg, "USE_ML_FILTER", False))
    core.ml_filter.bundle_for = lambda s: {"tau": 0.6}
    core._cfg.ML_FILTER_MAX_CAPITAL, core._cfg.USE_ML_FILTER = 500, True
    try:
        core.get_account_info = lambda: NS(balance=100, equity=100)
        assert core._ml_bundle() == {"tau": 0.6}                          # cuenta chica: con filtro
        core.get_account_info = lambda: NS(balance=800, equity=450)
        assert core._ml_bundle() == {"tau": 0.6}                          # capital = min(balance, equity) < 500
        core.get_account_info = lambda: NS(balance=600, equity=600)
        assert core._ml_bundle() is None                                  # ≥ 500: sin filtro
        core.ml_filter.bundle_for = lambda s: None                        # modelo ausente o inválido
        assert core._ml_bundle() is None                                  # ≥ 500 no lo necesita
        core.get_account_info = lambda: NS(balance=100, equity=100)
        assert core._ml_bundle() is False                                 # lo necesita y falta: bloquea (fail-closed)
        core._cfg.USE_ML_FILTER = False
        assert core._ml_bundle() is None                                  # filtro apagado: opera sin él
    finally:
        (core.ml_filter.bundle_for, core.get_account_info, core._cfg.ML_FILTER_MAX_CAPITAL,
         core._cfg.USE_ML_FILTER) = saved


def test_trade_entry_once_per_signal_bar_inside_window():
    from bot_engine import core
    close = 1_800_000_000                                                  # cierre de una vela M15 (config scalping)
    saved = (core.server_now, core.ENTRY_WINDOW_MIN, core._last_trade_bar)
    try:
        core.ENTRY_WINDOW_MIN, core._last_trade_bar = 5, None
        ok = lambda t: (setattr(core, "server_now", lambda: datetime.fromtimestamp(t, tz=timezone.utc))
                        or core._entry_bar_ok(close - 900))
        assert not ok(close - 1) and ok(close + 60) and not ok(close + 300)   # antes / a tiempo / tarde
        core._last_trade_bar = close - 900                                  # ya entró con esta vela (y salió por SL)
        assert not ok(close + 60)
        core.ENTRY_WINDOW_MIN, core._last_trade_bar = None, None            # sin ventana: solo 1 por vela
        assert ok(close + 600)
    finally:
        core.server_now, core.ENTRY_WINDOW_MIN, core._last_trade_bar = saved



def test_entry_retries_each_hour_and_strong_signal_enters_late():
    from bot_engine import core
    close = 1_800_000_000                                                  # cierre de la vela de señal
    bar = close - core._tf_minutes(core._cfg.PRIMARY_TF) * 60
    saved = (core.server_now, core.ENTRY_WINDOW_MIN, core._last_trade_bar,
             getattr(core._cfg, "ENTRY_RETRY_MIN", None), getattr(core._cfg, "LATE_ENTRY_SCORE", None))
    try:
        core.ENTRY_WINDOW_MIN, core._last_trade_bar, core._cfg.LATE_ENTRY_SCORE = 15, None, 8.25
        core._cfg.ENTRY_RETRY_MIN = 60
        ok = lambda t, sc=6.0: (setattr(core, "server_now", lambda: datetime.fromtimestamp(t, tz=timezone.utc))
                                or core._entry_bar_ok(bar, sc))
        assert ok(close + 60) and not ok(close + 1800) and ok(close + 3600 + 60) and not ok(close - 1)
        assert ok(close + 1800, 8.3) and ok(close + 1800, -9.0)               # muy fuerte: entra tarde
        core._last_trade_bar = bar                                          # pero solo una vez por señal
        assert not ok(close + 1800, 9.0)
    finally:
        (core.server_now, core.ENTRY_WINDOW_MIN, core._last_trade_bar,
         core._cfg.ENTRY_RETRY_MIN, core._cfg.LATE_ENTRY_SCORE) = saved

def test_grid_opens_one_basket_per_signal_bar_like_backtest():
    from bot_engine import core
    calls, close = [], 1_800_000_000                                       # cierre de una vela M15 (config scalping)
    saved = (core.server_now, core.grid.try_open_basket, core.GRID_EXEC_TF, core._last_basket_bar, core.grid.baskets)
    core.grid.try_open_basket, core.GRID_EXEC_TF = (lambda *a, **k: calls.append(a) or {"ok": True}), "M1"
    open_now = []
    core.grid.baskets = lambda *a, **k: open_now
    try:
        for t in (close - 1, close + 60, close + 30):                     # antes del cierre / tarde / a tiempo ×2
            core.server_now = lambda t=t: datetime.fromtimestamp(t, tz=timezone.utc)
            core._try_open_basket("BUY", None, close - 900, 1.0)
        core._try_open_basket("BUY", None, close - 900, 1.0)
        assert len(calls) == 1                                             # una sola cesta, en el 1.er minuto
        core.GRID_ONE_PER_BAR = False                                      # grid M1: varias por vela
        core._try_open_basket("BUY", None, close - 900, 1.0)
        assert len(calls) == 1                                             # la cesta anterior ya cerró: no reabre
        open_now.append({"id": 1})
        core._try_open_basket("BUY", None, close - 900, 1.0)
        assert len(calls) == 2                                             # extra con una abierta: la separación la decide grid
    finally:
        core.server_now, core.grid.try_open_basket, core.GRID_EXEC_TF, core._last_basket_bar, core.grid.baskets = saved
        core.GRID_ONE_PER_BAR = True


def test_grid_range_regime_inverts_adx_and_rsi_gates():
    import numpy as np
    import pandas as pd
    import config
    from bot_engine import signals as sg, indicators as ind
    from bot_engine.patterns import analyze_patterns
    rng = np.random.default_rng(3)
    close = 2000 + np.cumsum(rng.normal(0.3, 2, 900))
    df = pd.DataFrame({"open": close, "high": close + 3, "low": close - 3, "close": close,
                       "volume": rng.integers(100, 1000, 900).astype(float)})
    real = sg.MIN_SIGNAL_SCORE
    sg.MIN_SIGNAL_SCORE = 0.01

    def act(ip, it, pats, price, regime, adx, rsi):
        config.GRID_REGIME = regime
        return sg.generate_signal(price, {**ip, "adx": adx, "rsi": rsi}, it, pats, ip["atr"], it)["action"]
    try:
        for end in range(400, 900, 10):
            w = df.iloc[end - 400:end]
            price = float(w["close"].iloc[-1])
            ip, it, pats = ind.calculate_all(w, price), ind.calculate_all(w.iloc[::3], price), analyze_patterns(w, "up")
            if act(ip, it, pats, price, "trend", 40, 50) == "BUY":
                break
        else:
            raise AssertionError("sin ventana BUY")
        assert act(ip, it, pats, price, "trend", 10, 50) == "HOLD"           # tendencia: ADX bajo bloquea
        assert act(ip, it, pats, price, "trend", 40, 80) == "HOLD"           # tendencia: RSI extremo bloquea
        assert act(ip, it, pats, price, "range", 40, 50) == "HOLD"           # rango: ADX alto bloquea
        assert act(ip, it, pats, price, "range", 10, 80) == "BUY"            # rango: ADX bajo y RSI extremo pasan
    finally:
        sg.MIN_SIGNAL_SCORE = real
        del config.GRID_REGIME



def test_test_runner_levels_25_50_pips():
    import importlib.util
    spec = importlib.util.spec_from_file_location("test_runner", ROOT / "xauusd_scalping_bot" / "test_runner.py")
    tr = importlib.util.module_from_spec(spec); spec.loader.exec_module(tr)
    sl, tp = tr.levels("BUY", 2000.00, 0.01)
    assert (round(sl, 2), round(tp, 2)) == (1997.50, 2005.00)                 # 250 / 500 puntos
    sl, tp = tr.levels("SELL", 2000.00, 0.01)
    assert (round(sl, 2), round(tp, 2)) == (2002.50, 1995.00)


def test_get_tick_rejects_zero_price():
    real = dh.mt5
    try:
        dh.mt5 = NS(symbol_info_tick=lambda s: NS(bid=0.0, ask=0.0, time=0))
        assert dh.get_tick("XAUUSD") is None
        dh.mt5 = NS(symbol_info_tick=lambda s: NS(bid=4000.0, ask=4000.3, time=1))
        assert dh.get_tick("XAUUSD").ask == 4000.3
    finally:
        dh.mt5 = real

def test_server_now_is_utc_aware():
    real = dh.mt5
    dh.mt5 = NS(symbol_info_tick=lambda s: NS(time=1_760_000_000))
    try:
        assert dh.server_now() == datetime.fromtimestamp(1_760_000_000, tz=timezone.utc)
    finally:
        dh.mt5 = real


# ─── Coordinador, estado persistente y envío verificado (2026-10-27) ──────────
# Los mocks reproducen lo que documenta la API de MT5; no equivalen al servidor real del bróker.

def _mt5(**fns):
    """Sustituye funciones de mt5; devuelve la función que las restaura."""
    saved = {k: getattr(mt5, k) for k in fns}
    vars(mt5).update(fns)
    return lambda: vars(mt5).update(saved)


def _pos(ticket, magic=None, sl=0.0, tp=0.0, price=4000.5, volume=0.01):
    return NS(ticket=ticket, identifier=ticket, magic=co._cfg.MAGIC_NUMBER if magic is None else magic,
              sl=sl, tp=tp, price_open=price, volume=volume, time_msc=ticket, comment="")


def _fresh_co():
    for f in ("state.json", "state.json.corrupt"):
        (co.STATE_DIR / f).unlink(missing_ok=True)
    co.load_state()
    co._config_errors, co._login, co._tick_seen = [], None, (None, 0.0)


def test_single_instance_lock():
    assert co.acquire_instance_lock()
    first = co._lock_fh
    try:
        assert not co.acquire_instance_lock()                 # segunda copia del mismo bot: aborta
    finally:
        first.close()


def test_mode_state_blocks_foreign_positions_and_read_errors():
    _fresh_co()
    own = co._cfg.MAGIC_NUMBER
    restore = _mt5(positions_get=lambda **k: [], orders_get=lambda **k: [])
    try:
        assert co.mode_state("X", own)[0] == co.IDLE
        mt5.positions_get = lambda **k: [_pos(1)]
        assert co.mode_state("X", own)[0] == f"{co.ENGINE}_ACTIVE"
        mt5.positions_get = lambda **k: [_pos(1), _pos(2, magic=20260618)]     # Swing abierto
        assert co.mode_state("X", own)[0] == co.DRAINING
        mt5.positions_get, mt5.orders_get = (lambda **k: []), (lambda **k: [_pos(3, magic=0)])   # orden manual
        assert co.mode_state("X", own)[0] == co.DRAINING
        mt5.positions_get = lambda **k: None                                   # no se pudo leer
        assert co.mode_state("X", own)[0] == co.SAFE
        mt5.positions_get = lambda **k: []
        co._config_errors = ["RISK_PER_TRADE fuera de (0, 5 %]"]
        assert co.mode_state("X", own)[0] == co.SAFE
    finally:
        restore()
        _fresh_co()


def test_state_survives_restart_and_corrupt_file_blocks():
    _fresh_co()
    co.save_state(last_trade_bar=123.0, peak=60.5, dd_stopped=True, halt_day="2026-10-27")
    co.state.clear()
    st = co.load_state()
    assert (st["last_trade_bar"], st["peak"], st["dd_stopped"], st["halt_day"]) == (123.0, 60.5, True, "2026-10-27")
    (co.STATE_DIR / "state.json").write_text("{roto", encoding="utf-8")
    co.load_state()
    assert co.state["breaker"]["manual"] and (co.STATE_DIR / "state.json.corrupt").exists()
    restore = _mt5(positions_get=lambda **k: [])
    try:
        co.reconcile("X", co._cfg.MAGIC_NUMBER)
        assert co.state["breaker"]                            # sigue bloqueado mientras exista el respaldo
        (co.STATE_DIR / "state.json.corrupt").unlink()
        co.reconcile("X", co._cfg.MAGIC_NUMBER)
        assert co.state["breaker"] is None                    # el operador lo revisó y borró: se reanuda
    finally:
        restore()
        _fresh_co()


def test_auto_breaker_clears_only_when_own_positions_protected():
    _fresh_co()
    co.trip("3 fallos de orden seguidos")
    restore = _mt5(positions_get=lambda **k: [_pos(5, sl=0.0)])
    try:
        co.reconcile("X", co._cfg.MAGIC_NUMBER)
        assert co.state["breaker"]                            # hay una posición propia sin SL: no se suelta
        mt5.positions_get = lambda **k: [_pos(5, sl=3990.0)]
        co.reconcile("X", co._cfg.MAGIC_NUMBER)
        assert co.state["breaker"] is None and co.state["order_fails"] == 0
    finally:
        restore()
        _fresh_co()


def test_consecutive_order_failures_trip_breaker():
    _fresh_co()
    co.record_order(False); co.record_order(False); co.record_order(True)
    assert co.state["order_fails"] == 0 and not co.state["breaker"]     # un éxito reinicia la cuenta
    for _ in range(co.ORDER_FAIL_LIMIT):
        co.record_order(False)
    assert co.state["breaker"] and co.mode_state.__name__               # SAFE_MODE
    _fresh_co()


def test_entry_gate_terminal_account_and_stale_tick():
    _fresh_co()
    own, tick = co._cfg.MAGIC_NUMBER, NS(time=1000)
    demo = mt5.ACCOUNT_TRADE_MODE_DEMO
    restore = _mt5(positions_get=lambda **k: [], orders_get=lambda **k: [],
                   terminal_info=lambda: NS(connected=True, trade_allowed=True),
                   account_info=lambda: NS(login=1, trade_mode=demo))
    live = os.environ.pop("ALLOW_LIVE_TRADING", None)
    try:
        co._login = 1
        assert co.entry_gate("X", own, tick)[0]
        mt5.terminal_info = lambda: NS(connected=True, trade_allowed=False)
        assert "Algo Trading" in co.entry_gate("X", own, tick)[1]
        mt5.terminal_info = lambda: NS(connected=False, trade_allowed=True)
        assert not co.entry_gate("X", own, tick)[0]
        mt5.terminal_info = lambda: NS(connected=True, trade_allowed=True)
        co._tick_seen = (1000, co.time.monotonic() - co.STALE_TICK_SEC - 1)
        assert "precio sin cambios" in co.entry_gate("X", own, tick)[1]   # mismo tick hace demasiado
        assert co.entry_gate("X", own, NS(time=1001))[0]                   # llega un tick nuevo: sigue
        mt5.account_info = lambda: NS(login=1, trade_mode=demo + 2)        # la misma cuenta pasó a real
        assert co.entry_gate("X", own, NS(time=1002))[2] == co.SAFE and co.state["breaker"]
        _fresh_co(); co._login = 1
        mt5.account_info = lambda: NS(login=2, trade_mode=demo)            # cambiaron la cuenta del terminal
        assert co.entry_gate("X", own, NS(time=1003))[2] == co.SAFE
    finally:
        restore()
        if live is not None:
            os.environ["ALLOW_LIVE_TRADING"] = live
        _fresh_co()


def test_validate_config_flags_bad_values():
    assert co.validate_config(co._cfg) == []                               # el config vigente es válido
    bad = NS(**{k: getattr(co._cfg, k) for k in dir(co._cfg) if k.isupper()})
    bad.RISK_PER_TRADE, bad.MAX_OPEN_TRADES, bad.LATE_ENTRY_SCORE = 0.5, 0, 1.0
    errs = co.validate_config(bad)
    assert len(errs) == 3 and any("RISK_PER_TRADE" in e for e in errs)


def _send_env(**fns):
    tm_saved = (tm.get_tick, tm.notify, tm.play_trade_sound)
    tm.get_tick = lambda *a, **k: NS(ask=4000.1, bid=4000.0)
    tm.notify = tm.play_trade_sound = lambda *a, **k: None
    restore = _mt5(**{"order_check": lambda r: NS(retcode=0, comment="Done"), **fns})

    def undo():
        tm.get_tick, tm.notify, tm.play_trade_sound = tm_saved
        restore()
    return undo


def test_open_trade_order_check_rejects_without_sending():
    _fresh_co()
    sent = []
    undo = _send_env(order_check=lambda r: NS(retcode=10019, comment="No money"),
                     order_send=lambda r: sent.append(r), positions_get=lambda **k: [])
    try:
        assert tm.open_trade("BUY", 3990.0, 4020.0, 0.01, SYM) is None
        assert sent == [] and co.state["order_fails"] == 1
    finally:
        undo()
        _fresh_co()


def test_open_trade_no_response_reconciles_without_resending():
    _fresh_co()
    sent, book = [], []
    undo = _send_env(order_send=lambda r: sent.append(r) or book.append(_pos(42, sl=3990.0)) or None,
                     positions_get=lambda **k: list(book))
    try:
        assert tm.open_trade("BUY", 3990.0, 4020.0, 0.01, SYM) == 42      # el servidor sí la ejecutó
        assert len(sent) == 1 and not co.state["breaker"]
        _fresh_co(); sent.clear()
        mt5.order_send = lambda r: sent.append(r) or None                  # sin respuesta y sin posición nueva
        assert tm.open_trade("BUY", 3990.0, 4020.0, 0.01, SYM) is None
        assert len(sent) == 1 and "desconocido" in co.state["breaker"]["reason"]   # no reenvía: SAFE_MODE
    finally:
        undo()
        _fresh_co()


def test_open_trade_partial_fill_counts_and_logs_real_volume():
    _fresh_co()
    undo = _send_env(order_send=lambda r: NS(retcode=mt5.TRADE_RETCODE_DONE_PARTIAL, order=9, comment=""),
                     positions_get=lambda **k: [_pos(9, sl=3990.0, volume=0.01, price=4000.3)])
    try:
        assert tm.open_trade("BUY", 3990.0, 4020.0, 0.02, SYM) == 9
        import json
        filled = [json.loads(l) for l in journal.PATH.read_text(encoding="utf-8").splitlines()
                  if '"filled"' in l][-1]
        assert filled["partial"] and filled["lot"] == 0.01 and filled["slippage_pts"] == 20
    finally:
        undo()
        _fresh_co()


def test_open_trade_without_sl_repairs_or_closes():
    _fresh_co()
    saved = (tm._modify_sl, tm.close_trade)
    book = {"sl": 0.0}
    closed = []
    tm._modify_sl = lambda t, sl, tp, d, s=None: book.update(sl=sl) or True
    tm.close_trade = lambda t, info: closed.append(t) or True
    undo = _send_env(order_send=lambda r: NS(retcode=mt5.TRADE_RETCODE_DONE, order=11, comment=""),
                     positions_get=lambda **k: [_pos(11, sl=book["sl"])])
    try:
        assert tm.open_trade("BUY", 3990.0, 4020.0, 0.01, SYM) == 11
        assert book["sl"] == 3990.0 and not closed and not co.state["breaker"]    # SL repuesto
        book["sl"] = 0.0
        tm._modify_sl = lambda *a, **k: False                                     # no se puede reponer
        tm.open_trade("BUY", 3990.0, 4020.0, 0.01, SYM)
        assert closed == [11] and "sin stop-loss" in co.state["breaker"]["reason"]   # se cierra + SAFE_MODE
    finally:
        tm._modify_sl, tm.close_trade = saved
        undo()
        _fresh_co()


def test_can_open_trade_blocks_when_positions_unreadable():
    saved = (rm.is_daily_loss_exceeded, rm._peak, rm._dd_stopped)
    rm.is_daily_loss_exceeded = lambda: False
    restore = _mt5(positions_get=lambda *a, **k: None if not k else [],    # por símbolo bien, la cuenta entera falla
                   account_info=lambda: NS(balance=100, equity=100, margin_free=100, margin=0))
    try:
        ok, why = rm.can_open_trade("BUY")
        assert not ok and "leer" in why                                    # antes contaba 0 abiertas y dejaba pasar
    finally:
        rm.is_daily_loss_exceeded, rm._peak, rm._dd_stopped = saved
        restore()


def test_news_cache_from_another_week_is_unavailable():
    from bot_engine import news_filter as nf
    from datetime import timedelta
    saved = (nf._cache_events, nf._cache_time, nf._fetch_calendar)
    nf._fetch_calendar = lambda: None                                      # sin internet
    try:
        nf._cache_events, nf._cache_time = [(datetime.now(timezone.utc), "USD", "High", "x")], datetime.now(timezone.utc)
        assert nf._get_events() is not None                                # fresca: se usa
        nf._cache_time = datetime.now(timezone.utc) - timedelta(days=8)
        assert nf._get_events() is None                                    # otra semana: "no disponible"
    finally:
        nf._cache_events, nf._cache_time, nf._fetch_calendar = saved


def test_backtest_trade_cost_matches_broker_commission():
    sys.path.insert(0, str(ROOT / "backtesting"))
    import engine_backtest as eb
    assert eb.trade_cost(0.01, 0.01, 100.0) == 0.0                                  # sin costes: idéntico a antes
    assert abs(eb.trade_cost(0.01, 0.01, 100.0, commission_per_lot=6.0) - 0.06) < 1e-9   # XAUUSD-ECN: 0.03 × 2 lados
    assert abs(eb.trade_cost(0.01, 0.01, 100.0, slippage_points=5) - 0.10) < 1e-9        # 5 pts × 2 lados × $1/pt/0.01


def test_backtest_regime_labels_do_not_look_ahead():
    sys.path.insert(0, str(ROOT / "backtesting"))
    import engine_backtest as eb
    import numpy as np, pandas as pd
    rng = np.random.default_rng(1)
    c = 4000 + rng.normal(0, 3, 900).cumsum()
    df = pd.DataFrame({"open": c, "high": c + 2, "low": c - 2, "close": c})
    lab = eb.regime_labels(df, 20, window=300, min_hist=100)
    assert lab[0] == "sin datos" and lab[-1] != "sin datos"
    df2 = df.copy()
    df2.loc[700:, ["high", "low", "close"]] *= 1.10                                # cambiar el futuro…
    assert (eb.regime_labels(df2, 20, window=300, min_hist=100)[:701] == lab[:701]).all()   # …no cambia el pasado
    st = eb.regime_stats([{"open_time": 850, "pnl": 1.0, "r": 0.5}], lab, np.arange(900))
    assert sum(v["trades"] for v in st.values()) == 1
    # vivo (core._regime_now): velas cerradas hasta k, shift=0 → misma etiqueta que el backtest en la vela de entrada k+1
    for k in (500, 650, 898):
        assert eb.regime_labels(df.iloc[:k + 1], 20, window=300, min_hist=100, shift=0)[-1] == lab[k + 1]


def test_ml_calibration_beats_base_rate_only_when_informative():
    sys.path.insert(0, str(ROOT / "backtesting"))
    import engine_backtest as eb
    import numpy as np
    y = np.array([1, 0, 1, 0, 1, 0, 1, 0], bool)
    good = eb.calibration(np.where(y, 0.8, 0.2), y)
    flat = eb.calibration(np.full(8, 0.5), y)
    assert good["brier"] < good["brier_base"] and good["logloss"] < good["logloss_base"]
    assert flat["brier"] == flat["brier_base"]                                    # sin información = tasa base


def test_trend_family_cap_and_session_vwap():
    from bot_engine import indicators as ind, signals as sg
    import pandas as pd
    idx = pd.date_range("2026-10-26 22:00", periods=8, freq="h")                    # cruza la medianoche del servidor
    s = pd.Series([10.0, 10, 20, 20, 20, 20, 20, 20], index=idx)                  # 22h, 23h | 00h… (día nuevo)
    v = ind.calc_vwap_session(s, s, s, pd.Series(1.0, index=idx))
    assert v.iloc[1] == 10.0 and v.iloc[2] == 20.0 and v.iloc[-1] == 20.0          # se reinicia a las 00:00
    saved = getattr(sg._cfg, "TREND_FAMILY_CAP", None)
    ip = {"ema9": 110, "ema21": 105, "ema50": 100, "ema200": 90, "rsi": 55, "macd": 1, "macd_signal": 0,
          "macd_hist": 1, "macd_hist_prev": 0.5, "bb_upper": 120, "bb_lower": 90, "bb_middle": 105, "bb_pct": 0.6,
          "vwap": 104, "adx": 30, "atr": 3.0}
    try:
        sg._cfg.TREND_FAMILY_CAP = None
        full = sg.generate_signal(112, ip, ip, {"score": 0}, 3.0, ip)["score"]
        sg._cfg.TREND_FAMILY_CAP = 1.0
        capped = sg.generate_signal(112, ip, ip, {"score": 0}, 3.0, ip)["score"]
        assert capped < full                                                       # la familia EMA vota menos
    finally:
        sg._cfg.TREND_FAMILY_CAP = saved


def test_backtest_r_distribution_counts_every_trade():
    sys.path.insert(0, str(ROOT / "backtesting"))
    import engine_backtest as eb
    t = lambda side, r, k: dict(side=side, r=r, pnl=r * 10, cost=0.0, open_time=k * 900, close_time=k * 900 + 600,
                                bars=1, reason="SL" if r < 0 else "TP")
    trades = [t("BUY", -1.0, 1), t("BUY", 2.0, 2), t("SELL", -2.5, 3), t("SELL", 0.4, 4)]
    m = eb.metrics(trades, [(k * 900, 1000.0 + k) for k in range(6)], 1000.0)
    assert sum(m["r_dist"]["hist"].values()) == 4 and m["r_dist"]["p5"] < -2.0   # todas, compras y ventas


def test_symbol_resolves_per_broker_name():
    from bot_engine.symbols import pick_symbol
    s = lambda name, spread, mode=4: NS(name=name, spread=spread, trade_mode=mode)
    vt = [s("BTCXAU", 5), s("XAUEUR-ECN", 3), s("XAUUSD-ECN", 11), s("XAUUSD247", 22), s("XAUUSD.crp", 1, 0)]
    assert pick_symbol("XAUUSD", ("GOLD",), vt) == ("XAUUSD-ECN", ["XAUUSD-ECN", "XAUUSD247"])   # cruces y .crp fuera
    assert pick_symbol("XAUUSD", (), [s("XAUUSD", 30), s("XAUUSDm", 10)])[0] == "XAUUSD"          # exacto gana
    assert pick_symbol("XAUUSD", (), [s("XAUUSD", 30, 0), s("#XAUUSD", 10)])[0] == "#XAUUSD"      # exacto no operable
    assert pick_symbol("XAUUSD", ("GOLD",), [s("GOLD.pro", 9), s("GOLDEUR", 2)])[0] == "GOLD.pro"
    assert pick_symbol("XAUUSD", (), [s("xau/usd.pro", 8), s("XAUUSDm", 8)])[0] == "XAUUSDm"      # empate: más corto
    assert pick_symbol("XAUUSD", ("GOLD",), [s("EURUSD", 1)]) == ("XAUUSD", [])


def test_backtest_fine_entry_on_lower_tf():
    import numpy as np
    bt = _backtest_module()
    n, f = 6, 3                                                     # 6 velas M15 = 18 velas M5, spread 0
    arr = (np.full(n, 100.0), np.full(n, 100.05), np.full(n, 99.95), np.full(n, 100.0), np.zeros(n))
    x = {k: np.full(n * f, v) for k, v in (("o", 100.0), ("h", 100.05), ("l", 99.95), ("c", 100.0))}

    def run(mode, edit=None):
        xx = {k: v.copy() for k, v in x.items()}
        for (k, m), v in (edit or {}).items():
            xx[k][m] = v
        ex = NS(**xx, sp=np.zeros(n * f), t=np.arange(n * f) * 300, t_prim=np.arange(n) * 900,
                e9=np.where(np.arange(n * f) == 3, 2.0, 1.0), e21=np.ones(n * f), mode=mode, f=0.25)
        return bt.make_outcome(arr, np.full(n, 1.0), SYM, rm, tm, max_bars=2, ex=ex)(0, bt.BUY, 1.5, 3.0)
    ctrl = bt.make_outcome(arr, np.full(n, 1.0), SYM, rm, tm, max_bars=2)(0, bt.BUY, 1.5, 3.0)
    assert run("market")[2:4] == ctrl[2:4]                          # misma entrada y SL que hoy
    out = run("pullback", {("l", 4): 99.70})                      # vela M5 n.º 2 de la M15 k=1 cruza 99.75
    assert out[2] == 99.75 and out[3] == ctrl[3]                    # entra en el límite, mismo SL → menos riesgo
    assert run("pullback", {("l", 4): 99.76}) == "noexec"         # no lo cruza: sin operación
    assert run("pullback", {("l", 4): 98.0})[4] == "SL"           # en la vela del llenado solo cuenta el SL
    out = run("confirm", {("c", 3): 100.04, ("o", 4): 100.03})    # M5 n.º 1 cierra al alza con EMA9 > EMA21
    assert out[2] == 100.03                                         # entra al abrir la siguiente M5
    assert run("confirm") == "noexec"                               # sin vela a favor: sin operación


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"{len(tests)} pruebas OK")
