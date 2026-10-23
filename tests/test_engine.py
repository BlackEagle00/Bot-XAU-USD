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

SYM = NS(trade_tick_size=0.01, trade_tick_value=1.0, volume_step=0.01,
         volume_min=0.01, volume_max=100.0, digits=2, point=0.01, trade_stops_level=0)


def test_lot_uses_real_sl_and_rounds_down():
    acc = NS(balance=10_000, equity=10_000)                    # riesgo 1% = $100
    assert rm.calculate_lot(acc, SYM, 4.39) == 0.22            # 0.2278 → abajo, no 0.23
    assert rm.calculate_lot(acc, SYM, 8.78) == 0.11            # SL más ancho → lote menor


def test_small_account_trades_min_lot_up_to_5pct_risk():
    acc = NS(balance=100, equity=100)
    lot, need = rm.lot_plan(acc, SYM, 4.39)                    # 0.01 lote arriesga $4.39 = 4.4%
    assert lot == 0.01 and abs(need - 439) < 1e-6              # con $439 vuelve al 1%
    assert abs(rm.lot_risk_pct(acc, SYM, 4.39, lot) - 0.0439) < 1e-9
    lot, need = rm.lot_plan(acc, SYM, 8.78)                    # 8.8% > 5% → no opera
    assert lot == 0.0 and abs(need - 175.6) < 1e-6             # capital mínimo para operarlo al 5%
    assert rm.calculate_lot(acc, SYM, 8.78) == 0.0


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
        assert rm.lot_plan(NS(balance=100, equity=100), gold, 8.11)[0] == 0.0   # $100 no alcanza 1%
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
    text = (ROOT / "dashboard" / "profiles" / "forex_swing" / "config.py").read_text(encoding="utf-8")
    out = cal.apply_params(text, {"tf": "H4", "MIN_SIGNAL_SCORE": 6.0, "SL_ATR_MULT": 2.0}, "prueba")
    assert 'tf="H4"' in out and "    MIN_SIGNAL_SCORE=6.0,\n" in out and out.rstrip().endswith("))")
    again = cal.apply_params(out, {"tf": "H1", "MIN_SIGNAL_SCORE": 4.0}, "otra")
    assert again.count("MIN_SIGNAL_SCORE") == 1 and "SL_ATR_MULT" not in again and 'tf="H1"' in again
    ns = {}
    exec(compile(again.replace('Path(__file__)', f'Path(r"{ROOT / "dashboard" / "profiles" / "forex_swing" / "config.py"}")'),
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


def test_server_now_is_utc_aware():
    real = dh.mt5
    dh.mt5 = NS(symbol_info_tick=lambda s: NS(time=1_760_000_000))
    try:
        assert dh.server_now() == datetime.fromtimestamp(1_760_000_000, tz=timezone.utc)
    finally:
        dh.mt5 = real


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK  {t.__name__}")
    print(f"{len(tests)} pruebas OK")
