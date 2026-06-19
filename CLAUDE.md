# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

An automated trading bot for MetaTrader 5 (Windows only — MT5's Python API requires the MT5 terminal
running locally). The original bot is the gold one in `xauusd_bot/`; the repo now holds **four
independent bot variants**, each a self-contained copy of the same engine with its own `config.py`,
`MAGIC_NUMBER`, and `LOG_FILE` (so they can run side-by-side on one account without touching each
other's trades):

| Folder | Symbol | Mode | Magic |
|---|---|---|---|
| `xauusd_bot/`          | GOLD   | swing H1/H4/D1     | 20260618 |
| `xauusd_scalping_bot/` | GOLD   | scalping M5/M15/H1 | 20260621 |
| `eurusd_bot/`          | EURUSD | swing H1/H4/D1     | 20260619 |
| `eurusd_scalping_bot/` | EURUSD | scalping M5/M15/H1 | 20260620 |

`run.py` (repo root) is the launcher: `python run.py` for an interactive menu, or
`python run.py <key>` where key ∈ `oro | oro_scalping | eurusd | eurusd_scalping`. Because the engine is
**copied** (not shared/imported), a fix in one bot's module must be applied to the others by hand — they
have drifted on purpose (e.g. the D1 macro filter and gold-scale S/R live only in `xauusd_bot/`; the
EURUSD bots have a parametrized S/R fix the gold bots don't need).

The repo root also contains a separate, unrelated generic backtesting framework
(`trading_backtest_framework.py`, `metatrader_data_loader.py`, `ejemplo_completo_backtest.py`) that is
not wired into any bot — treat it as a standalone toolkit, not part of the bots' runtime path.

**Important — README.md is stale.** It still describes the bot as scalping (M5/M15/H1, 30s loop,
`MIN_SIGNAL_SCORE=4.5`). The actual current code (`xauusd_bot/config.py`, see commit "Areglos Claude
Scalping a swing trading") runs **swing trading on H1/H4/D1** with a 60s loop and
`MIN_SIGNAL_SCORE=5.0`. Trust `config.py` and the module docstrings over `README.md` when they conflict.

## Running the bot

```bash
pip install -r xauusd_bot/requirements.txt   # same deps for every variant
python run.py                # interactive menu to pick a bot
python run.py oro_scalping   # or launch one directly (oro | oro_scalping | eurusd | eurusd_scalping)
# — or run a single variant straight from its folder —
cd xauusd_bot && python main.py   # MT5 terminal must already be open and logged in
```

Stop with Ctrl+C — it finishes the current cycle, then disconnects cleanly. Open positions are left in
MT5 (not closed) on shutdown; `close_all_trades()` in `trade_manager.py` exists but is commented out in
`main.run()` if that behavior is ever wanted.

There is no test suite, linter, or build step in this repo. `validate_changes.py` and
`install_and_validate.sh` (repo root) are ad-hoc scripts that grep `xauusd_bot/config.py` for specific
expected values (e.g. `MIN_SIGNAL_SCORE.*5\.0`) to confirm a past round of tuning was applied — they are
not general-purpose tests and will go stale as config values change.

## Configuration

All tunable parameters live in `xauusd_bot/config.py`. MT5 credentials (`MT5_LOGIN`, `MT5_PASSWORD`,
`MT5_SERVER`) are loaded from a `.env` file via `python-dotenv` — never hardcode them in `config.py`.
If `MT5_LOGIN` is left at 0, the bot uses whatever account is already logged into the MT5 terminal.

`SYMBOL` may need adjusting per broker (`XAUUSD`, `GOLD`, `XAUUSDm`, etc.) — see `GUIA_BROKERS_COLOMBIA.md`
and `MIGRACION_A_XM.md` for broker-specific notes (this project has been evaluated against ICMarkets,
Pepperstone, XM, FP Markets).

## Architecture — the per-cycle pipeline

`main.py` runs an infinite loop (`LOOP_INTERVAL` seconds, currently 60s) calling `_run_cycle()`. Each
cycle is a strict pipeline through the other modules, and most modules only make sense in light of this
flow:

1. **`connection.py`** — verify/reconnect to the MT5 terminal, validate the symbol is in Market Watch.
2. **`data_handler.py`** — pull OHLCV for three timeframes at once: `primary` (`PRIMARY_TF`, currently
   H1), `trend` (`TREND_TF`, H4), `higher` (`HIGHER_TF`, D1). The most recent (still-forming) candle is
   always dropped to avoid acting on incomplete data. (Gold bot only: `higher`/D1 is now consumed as a
   macro-context filter — see step 5. The two EURUSD bots still fetch but don't consume it.)
3. **`indicators.py`** — `calculate_all()` computes EMA(9/21/50/200), SMA(20/50), RSI, MACD, ATR,
   Bollinger Bands, VWAP, and support/resistance pivots. Called for `primary`, `trend`, and — in the Gold
   bot — `higher` (D1).
4. **`patterns.py`** — `analyze_patterns()` detects 35+ candlestick patterns on the primary timeframe,
   producing a bull/bear score and named pattern lists.
5. **`signals.py`** — `generate_signal()` combines indicator scores (primary timeframe) + trend-timeframe
   EMA confirmation + pattern score into one weighted total (`SCORE_WEIGHTS` in config, range roughly
   ±12). Thresholded by `MIN_SIGNAL_SCORE` into BUY/SELL/HOLD. If `REQUIRE_TREND_ALIGNMENT` is true
   (default), a signal against the primary-timeframe EMA trend is forced to HOLD — the bot only trades
   with the trend. **Gold bot only:** `generate_signal()` also takes `ind_higher` (D1) and `_score_macro()`
   adds a weighted daily-trend bias (`SCORE_WEIGHTS["macro_tf"]`, max ±2.0 pre-weight so it nudges but
   never triggers a trade alone); when the daily EMAs are in a *strong* full cascade and
   `REQUIRE_MACRO_ALIGNMENT` is true (default), trades against that daily trend are vetoed to HOLD.
6. **`risk_manager.py`** — gates trade entry (`can_open_trade`): daily loss limit, max simultaneous
   trades, free margin floor. Also computes lot size from `RISK_PER_TRADE` × balance against ATR-based
   SL distance, and computes SL/TP prices from `SL_ATR_MULT`/`TP_ATR_MULT`.
7. **`trade_manager.py`** — sends/closes MT5 orders, and on *every* cycle (before any new entry is
   considered) runs break-even (`update_breakeven`) and trailing-stop (`update_trailing_stop`) on all
   open positions belonging to this bot (filtered by `MAGIC_NUMBER`, not by all positions on the symbol).
   Anti-duplicate logic (`is_too_close_to_existing`) prevents stacking trades within `0.5×ATR` of an
   existing position in the same direction.

`main._try_open_trade()` is the orchestration glue for step 6→7: `can_open_trade()` →
`is_too_close_to_existing()` → `calculate_sl_tp()` → `calculate_lot()` → `open_trade()`.

Cross-cutting concerns:
- All MT5 position queries filter by `MAGIC_NUMBER` (`data_handler.get_open_positions`), so this bot
  only ever manages/counts trades it itself opened — other manual or EA trades on the same symbol are
  ignored.
- `logger_config.py` sets up a single shared `logger` (console INFO+, file DEBUG+ to `LOG_FILE`). Import
  `from logger_config import logger` rather than creating new loggers.
- Broker compatibility quirks (filling mode bitmask, `trade_stops_level` minimum SL/TP distance, lot
  step/min/max) are handled defensively in `trade_manager.py` and `risk_manager.py` since brokers differ.
