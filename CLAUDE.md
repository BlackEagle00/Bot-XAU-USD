# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

An automated trading bot for MetaTrader 5 (Windows only — MT5's Python API requires the MT5 terminal
running locally). The original bot was the gold one in `xauusd_bot/`; the repo now holds **four bot
variants that share a single engine** (`bot_engine/`). Each bot folder contains only its own `config.py`
(parameters) and a thin `main.py` launcher — all logic lives once in `bot_engine/`. Each bot has its own
`MAGIC_NUMBER` and `LOG_FILE`, so they run side-by-side on one account without touching each other's trades:

| Folder | Symbol | Mode | Magic |
|---|---|---|---|
| `xauusd_bot/`          | GOLD   | swing H1/H4/D1     | 20260618 |
| `xauusd_scalping_bot/` | GOLD   | scalping M5/M15/H1 | 20260621 |
| `eurusd_bot/`          | EURUSD | swing H1/H4/D1     | 20260619 |
| `eurusd_scalping_bot/` | EURUSD | scalping M5/M15/H1 | 20260620 |

`run.py` (repo root) is the launcher: `python run.py` for an interactive menu, or
`python run.py <key>` where key ∈ `oro | oro_scalping | eurusd | eurusd_scalping`. **The engine is shared,
not copied**: fix or improve it **once** in `bot_engine/` and it applies to all 4 bots. A bot's `main.py`
puts its own folder first on `sys.path`, so the engine's `from config import …` resolves to that bot's
`config.py`; engine modules import each other relatively (`from .signals import …`). Each bot runs in its
own process (`run.py` uses subprocess), so configs never collide. Differences between bots are **driven by
config**, not by divergent code:
- **Macro context** is one code path in `bot_engine/signals.py`, gated per bot by `USE_MACRO_CONTEXT`:
  gold bots set it `True` (swing consumes D1 with a hard veto `REQUIRE_MACRO_ALIGNMENT=True`; scalp
  consumes H1 as a soft nudge, `REQUIRE_MACRO_ALIGNMENT=False`), and `MACRO_TF_LABEL` ("D1"/"H1") sets the
  log label. The EURUSD bots set `USE_MACRO_CONTEXT=False` (+ `REQUIRE_MACRO_ALIGNMENT=False`, no
  `macro_tf` weight) → `core.py` passes `ind_higher=None` and the macro fields don't even appear in their
  log line.
- **S/R scale** is parametrized in `bot_engine/indicators.py` via `SR_CLUSTER_ATR_MULT`,
  `SR_TOLERANCE_FLOOR`, `PSYCH_LEVEL_STEP`, `PSYCH_LEVEL_COUNT` (gold: 0.3 / 0.5 / 5.0 / 5, which reproduces
  the old `max(atr*0.3, 0.5)` + $5 levels; EUR: floor 0.0 + a decimal step).
- **Order-comment prefix** is `ORDER_COMMENT_PREFIX` ("XAU"/"XAU"/"EUR"/"EURs"); the startup banner text is
  `BOT_LABEL`.
- All the directional factors below are single implementations in the engine, switched/weighted by config
  (only the numeric values differ per bot — see the tuning table below):
  - **BE+**, **anti-exhaustion RSI filter**, **configurable anti-dup spacing** (the original trio).
  - **Progressive trailing lock** (`TRAIL_LOCK_*` in config; `_progressive_lock_sl` in `trade_manager.py`)
    — the trailing tightens to lock a growing fraction of open profit (→ ~1:1) as a trade matures.
  - **ADX filter** (`USE_ADX_FILTER`/`ADX_MIN_TREND`; `calc_adx` in `indicators.py`, gate in `signals.py`)
    — blocks new entries when the trend lacks strength (chop).
  - **Order-flow** (`USE_ORDERFLOW`; `data_handler.get_orderflow_delta`, scored in `signals.py` via
    `SCORE_WEIGHTS["orderflow"]`) — buy/sell pressure from recent ticks (CFDs have no real volume, so it's
    a tick-delta proxy).
  - **Inter-market DXY** (`USE_INTERMARKET`; `data_handler.get_intermarket_bias`, scored via
    `SCORE_WEIGHTS["intermarket"]`, `INTERMARKET_INVERSE=True`) — dollar-index bias, inverse for gold/EUR.
    `INTERMARKET_SYMBOL` is `"USDX-SEP26"` on the XM account (a quarterly **futures** contract — roll the
    suffix when it expires ~2026-09-11); if the broker lacks the symbol the factor degrades to no-op.
  - **News filter** (`USE_NEWS_FILTER`; engine module **`bot_engine/news_filter.py`**) — blackout gate
    around high-impact calendar events (ForexFactory weekly JSON; fail-open when offline via `NEWS_FAIL_OPEN`).
  - **Telegram notifications** (`USE_TELEGRAM`; engine module **`bot_engine/telegram_notifier.py`**) —
    pushes bot start/stop, trade open, trade close (SL/TP/manual, with realized P&L), and MT5 connection
    lost/restored to a Telegram chat. Stdlib `urllib` (no new dep), sends off a daemon thread, fail-open;
    **self-disables** if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (from `.env`) are empty. Each bot tags
    messages with its own `TELEGRAM_PREFIX` (`[GOLD swing]`, `[GOLD scalp]`, `[EURUSD swing]`,
    `[EURUSD scalp]`), read from its `config.py` — only that value differs between bots.

The `backtesting/` folder holds a separate, unrelated generic backtesting framework
(`trading_backtest_framework.py`, `metatrader_data_loader.py`, `ejemplo_completo_backtest.py`) that is
not wired into any bot — treat it as a standalone toolkit, not part of the bots' runtime path.

Repo layout: the shared engine is the package `bot_engine/` (`core.py` is the loop + entry point
`run()`, plus `signals.py`, `indicators.py`, `trade_manager.py`, etc.). Each bot folder holds only
`config.py` + a thin `main.py` launcher that prepends its folder to `sys.path` and calls
`bot_engine.core.run()`. Engine modules use **relative** imports for each other (`from .signals import …`)
and **absolute** `from config import …` (resolves to the launching bot's config via `sys.path[0]`) — keep
that split when editing or adding engine modules. Reference docs live in `docs/` (per-instrument guides
`docs/GUIA_GOLD.md` / `docs/GUIA_EURUSD.md`, broker/migration notes, and `docs/historico/` for dated
one-off reports); the backtesting toolkit lives in `backtesting/`. Root keeps only `run.py`,
`requirements.txt`, `.env.example`, `README.md` and this file.

**README.md is current** — it was rewritten alongside this round of features and now documents all 4
variants, the scoring/gates, the extra directional factors (ADX / order-flow / DXY / news), and every
on/off flag. Still trust `config.py` and the module docstrings for the exact live numbers when in doubt;
the README's per-bot numbers are illustrative snapshots that can drift as tuning changes.

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
`core.run()` if that behavior is ever wanted.

There is no test suite, linter, or build step in this repo. (Two ad-hoc validator scripts,
`validate_changes.py` and `install_and_validate.sh`, plus a `CAMBIOS_RECOMENDADOS.py` notes file, used
to live at the root; they were removed in the structural cleanup as stale — recover from git history if
ever needed. To smoke-test a change, `python -m py_compile <bot>/*.py` per folder.)

## Configuration

All tunable parameters live in each bot's own `config.py` (e.g. `xauusd_bot/config.py`) — the engine in
`bot_engine/` reads them via `from config import …`. MT5 credentials (`MT5_LOGIN`, `MT5_PASSWORD`,
`MT5_SERVER`) — and the optional Telegram secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) — are loaded
from a `.env` file via `python-dotenv`; never hardcode them in `config.py`.
If `MT5_LOGIN` is left at 0, the bot uses whatever account is already logged into the MT5 terminal.

`SYMBOL` may need adjusting per broker (`XAUUSD`, `GOLD`, `XAUUSDm`, etc.) — see `docs/GUIA_BROKERS_COLOMBIA.md`
and `docs/MIGRACION_A_XM.md` for broker-specific notes (this project has been evaluated against ICMarkets,
Pepperstone, XM, FP Markets). Account currently in use is an **XM demo** (`XMGlobal-MT5`), and gold
trades on this broker under `SYMBOL="GOLD"`.

**Changes need a bot restart.** A running bot holds the old code/config in memory — editing `config.py`
or a module does nothing until you Ctrl+C and relaunch that variant.

### Per-bot tuning (current values)

Each variant is tuned for its symbol+mode; keep these *intentionally different* when editing. Key knobs:

| Param | gold swing | gold scalp | eur swing | eur scalp |
|---|---|---|---|---|
| `SL_ATR_MULT` / `TP_ATR_MULT` | 2.0 / 4.5 | 1.5 / 3.0 | 1.2 / 2.7 | 1.0 / 1.5 |
| `MIN_RR` | 2.0 | 1.8 | 2.0 | 1.2 |
| `MIN_SIGNAL_SCORE` | 5.0 | 5.5 | 5.0 | 4.5 |
| `RISK_PER_TRADE` / `MAX_OPEN_TRADES` | 0.01 / **5** | 0.01 / 3 | 0.01 / 3 | 0.01 / 3 |
| `BE_TRIGGER_PCT` / `BE_PLUS_POINTS` | 0.40 / 5 | 0.55 / 5 | 0.50 / 5 | 0.55 / 5 |
| `BREAKEVEN_ATR_MULT` (fallback) | 1.5 | 1.0 | 0.9 | 0.6 |
| `TRAILING_ATR_MULT` | 2.5 | 1.0 | 1.5 | 0.5 |
| progressive lock `START`/`PCT_MIN→MAX`/`FULL_ATR` | 1.5 / .35→.90 / 4.0 | 1.0 / .40→.90 / 2.7 | 0.9 / .35→.90 / 2.4 | 0.5 / .40→.90 / 1.3 |
| `ANTI_DUP_ATR_MULT` | 1.0 | 0.75 | 1.0 | 0.75 |
| `RSI_NO_SELL_BELOW` / `RSI_NO_BUY_ABOVE` | 32 / 68 | 30 / 70 | 32 / 68 | 30 / 70 |
| `MAX_SPREAD_POINTS` | 80 | 70 | 50 | 18 |
| `LOOP_INTERVAL` (s) | 60 | 15 | 60 | 10 |
| macro filter | D1 veto (`macro_tf` 0.8) | H1 nudge (`macro_tf` 0.5) | none | none |
| `ADX_MIN_TREND` (chop gate) | 20 | 18 | 20 | 18 |
| `ORDERFLOW_LOOKBACK_SECS` / `orderflow` wt | 300 / 0.5 | 120 / 0.8 | 300 / 0.5 | 120 / 0.8 |
| `INTERMARKET_TF` / `intermarket` wt | H4 / 0.8 | H1 / 0.4 | H4 / 0.8 | H1 / 0.3 |
| `NEWS_BLACKOUT` ±min / `NEWS_CURRENCIES` | 30 / USD | 15 / USD | 30 / USD,EUR | 15 / USD,EUR |

The `USE_*` factor flags (`USE_PROGRESSIVE_TRAIL`, `USE_ADX_FILTER`, `USE_ORDERFLOW`,
`USE_INTERMARKET`, `USE_NEWS_FILTER`, plus `USE_TELEGRAM` for notifications) default to `True`; flip any
to `False` to disable that factor without touching the rest (`USE_TELEGRAM` also self-disables when its
`.env` creds are absent). `INTERMARKET_SYMBOL="USDX-SEP26"` (XM quarterly dollar-index future — roll the
suffix at expiry ~2026-09-11) must exist on the broker or the factor self-disables.

Note: total *correlated* risk ≈ `MAX_OPEN_TRADES × RISK_PER_TRADE` because `REQUIRE_TREND_ALIGNMENT`
forces every open trade the same direction. Gold swing is therefore at ~5% (5 × 1%). To raise the trade
cap without raising risk, lower `RISK_PER_TRADE` proportionally (e.g. 8 trades × 0.005 ≈ 4%).

**Open decision (not yet applied):** the user asked about allowing 5–8 simultaneous trades "without more
risk." Gold swing's `MAX_OPEN_TRADES` was manually bumped to 5 but `RISK_PER_TRADE` is still 0.01 (so
risk did rise to ~5%). A proportional `RISK_PER_TRADE` cut to keep total risk flat is still pending the
user's chosen budget (3% / 4% / 5%) and whether to apply it to the other bots.

### Applying a logic change (now: edit the engine once)

With the shared engine there's no more copy/paste across folders — that's the whole point of the refactor.
1. **Logic change** → edit the relevant module in `bot_engine/` **once**; it applies to all 4 bots.
2. **Behavior that must differ per bot** → don't fork the code. Add a config key (gate/weight/scale),
   read it in the engine with `from config import …` (or `SCORE_WEIGHTS.get(...)`/`getattr` with a default
   for backward-compat), and set its value in each `config.py`. Existing examples: `USE_MACRO_CONTEXT`,
   `MACRO_TF_LABEL`, `SR_TOLERANCE_FLOOR`, `ORDER_COMMENT_PREFIX`, `BOT_LABEL`. **If you import a new
   config key unconditionally in the engine, add it to all 4 `config.py` or those bots fail at import.**
3. **Tuning** → edit each `config.py` in place (never `cp` — every value is per-bot; see the tuning table).
4. **Verify**: `python -m py_compile bot_engine/*.py */config.py */main.py`, then a per-bot import smoke
   test in a separate process (replicate the launcher's `sys.path`: bot folder first, then repo root;
   `import config; import bot_engine.core`) so a missing config key surfaces. For behavior-preserving
   refactors, snapshot the originals and diff `generate_signal` output (action/score/reasons/log line) old
   vs new on identical synthetic inputs.

## Architecture — the per-cycle pipeline

`bot_engine/core.py` (launched by each bot's `main.py` → `run()`) runs an infinite loop (`LOOP_INTERVAL`
seconds, currently 60s) calling `_run_cycle()`. Each
cycle is a strict pipeline through the other modules, and most modules only make sense in light of this
flow:

1. **`connection.py`** — verify/reconnect to the MT5 terminal, validate the symbol is in Market Watch.
2. **`data_handler.py`** — pull OHLCV for three timeframes at once: `primary` (`PRIMARY_TF`, currently
   H1), `trend` (`TREND_TF`, H4), `higher` (`HIGHER_TF`, D1). The most recent (still-forming) candle is
   always dropped to avoid acting on incomplete data. (Both Gold bots consume `higher` as a macro-context
   filter — D1 in `xauusd_bot/`, H1 in `xauusd_scalping_bot/` — see step 5. The two EURUSD bots still
   fetch but don't consume it.) It also exposes two optional directional helpers used by all 4 bots:
   `get_orderflow_delta()` (recent-tick buy/sell pressure via `copy_ticks_range`, returns a delta in
   [-1,1] or `None`) and `get_intermarket_bias()` (dollar-index trend via `mt5.symbol_select` +
   `copy_rates_from_pos`; returns `None`/no-op if the broker lacks `INTERMARKET_SYMBOL`).
3. **`indicators.py`** — `calculate_all()` computes EMA(9/21/50/200), SMA(20/50), RSI, MACD, ATR,
   **ADX (trend strength)**, Bollinger Bands, VWAP, and support/resistance pivots. Called for `primary`,
   `trend`, and — in the Gold bot — `higher` (D1).
4. **`patterns.py`** — `analyze_patterns()` detects 35+ candlestick patterns on the primary timeframe,
   producing a bull/bear score and named pattern lists.
5. **`signals.py`** — `generate_signal(price, ind_primary, ind_trend, patterns, atr, ind_higher=None,
   orderflow=None, intermarket=None)` combines indicator scores (primary timeframe) + trend-timeframe EMA
   confirmation + pattern score + **order-flow** (`SCORE_WEIGHTS["orderflow"]`, ±~0.5–0.8) + **inter-market
   DXY** (`SCORE_WEIGHTS["intermarket"]`, ±~1.2, inverse) into one weighted total (range roughly ±12).
   Thresholded by `MIN_SIGNAL_SCORE` into BUY/SELL/HOLD. Then several gates can downgrade a BUY/SELL to HOLD:
   - **Trend alignment** — if `REQUIRE_TREND_ALIGNMENT` is true (default), a signal against the
     primary-timeframe EMA trend is forced to HOLD; the bot only trades with the trend.
   - **Anti-exhaustion RSI** (all 4 bots) — a new SELL is blocked when `rsi ≤ RSI_NO_SELL_BELOW` and a
     new BUY when `rsi ≥ RSI_NO_BUY_ABOVE`, so the bot doesn't "sell the bottom / buy the top" at a
     likely reversal. Swing uses 32/68, scalping 30/70. This filter only stops *opening*; it never
     closes existing positions.
   - **ADX trend-strength** (all 4 bots) — when `USE_ADX_FILTER` and the primary-TF `adx < ADX_MIN_TREND`
     (swing 20, scalping 18), new entries are blocked: the bot is trend-following, so a weak/ranging tape
     (low ADX) is where its cross signals fail. Measures strength only, not direction; never closes.
   - **Macro (Gold bots only)** — `generate_signal()` takes `ind_higher` and `_score_macro()` adds a
     weighted higher-TF trend bias (`SCORE_WEIGHTS["macro_tf"]`, capped so it nudges but never triggers a
     trade alone). In `xauusd_bot/` this is D1 (`macro_tf=0.8`) and, when the daily EMAs are in a *strong*
     full cascade with `REQUIRE_MACRO_ALIGNMENT=True`, trades against that daily trend are vetoed to HOLD.
     In `xauusd_scalping_bot/` it's H1 (`macro_tf=0.5`, `REQUIRE_MACRO_ALIGNMENT=False`) — nudge only, no
     veto. The EURUSD bots have no macro scoring at all.
6. **`risk_manager.py`** — gates trade entry (`can_open_trade`): daily loss limit, max simultaneous
   trades, free margin floor. Also computes lot size from `RISK_PER_TRADE` × balance against ATR-based
   SL distance, and computes SL/TP prices from `SL_ATR_MULT`/`TP_ATR_MULT`.
7. **`trade_manager.py`** — sends/closes MT5 orders, and on *every* cycle (before any new entry is
   considered) runs break-even (`update_breakeven`) and trailing-stop (`update_trailing_stop`) on all
   open positions belonging to this bot (filtered by `MAGIC_NUMBER`, not by all positions on the symbol).
   Break-even is "BE+": it triggers once price has covered `BE_TRIGGER_PCT` of the entry→TP distance
   (uses `pos.tp`; per-bot, ~0.40–0.55) and places the new SL at
   `entry ∓ (live_spread + BE_PLUS_POINTS×point)` so a reversal exits at a small profit (covers the
   spread), not at exactly entry. If a position has no TP, it falls back to `BREAKEVEN_ATR_MULT×ATR`.
   On the cycle BE fires, trailing is skipped (`if not moved_be` — the in-memory `pos.sl` is stale) and
   resumes next cycle. **BE+ never retroactively protects a position still below its trigger** — it only
   acts once the profit threshold is crossed, so positions opened before a code/config change need a
   bot restart and enough profit before they get protected.
   The trailing stop (`update_trailing_stop`) takes the *more protective* of two SLs each cycle: the
   classic ATR trail (`price ∓ TRAILING_ATR_MULT×ATR`, lets winners breathe) and the **progressive lock**
   (`_progressive_lock_sl`) — once open profit passes `TRAIL_LOCK_START_ATR` it secures a growing fraction
   of that profit, ramping linearly from `TRAIL_LOCK_PCT_MIN` to `TRAIL_LOCK_PCT_MAX` (≈1:1) by
   `TRAIL_LOCK_FULL_ATR`, so a pullback exits in profit instead of at break-even. Logged at INFO when the
   lock drives the SL move (`... | lock progresivo asegura NN% del profit`).
   Anti-duplicate logic (`is_too_close_to_existing`) prevents stacking trades within
   `ANTI_DUP_ATR_MULT × ATR` of an existing position in the same direction (was a hardcoded `0.5×ATR`;
   now per-bot config — swing 1.0, scalping 0.75 — to stop laddering many correlated entries into one leg).

`core._try_open_trade()` is the orchestration glue for step 6→7: **`in_news_blackout()`** (high-impact
news gate) → `can_open_trade()` → `is_too_close_to_existing()` → `calculate_sl_tp()` → `calculate_lot()` →
`open_trade()`. The news gate lives in the engine module **`bot_engine/news_filter.py`**, which fetches
ForexFactory's weekly JSON (`urllib`, stdlib — no new dependency), caches it ~6h, and is fail-open by
default (`NEWS_FAIL_OPEN=True`) so an offline calendar never freezes the bot.

Cross-cutting concerns:
- All MT5 position queries filter by `MAGIC_NUMBER` (`data_handler.get_open_positions`), so this bot
  only ever manages/counts trades it itself opened — other manual or EA trades on the same symbol are
  ignored.
- `logger_config.py` sets up a single shared `logger` (console INFO+, file DEBUG+ to `LOG_FILE`). Import
  `from logger_config import logger` rather than creating new loggers. The Windows console is cp1252, so
  the emoji in log lines raise a `UnicodeEncodeError` ("Logging error") **on the console only** — the
  `.log` file is UTF-8 and fine. This is cosmetic; the user has chosen to leave it.
- A repeated identical `📊 SELL | Score: …` log line across many cycles is expected: the bot re-evaluates
  and re-logs the live signal every cycle even while a position is open and its profit changes — the log
  reflects the current *signal*, not a new trade. New entries are gated by anti-dup + the risk manager.
- Broker compatibility quirks (filling mode bitmask, `trade_stops_level` minimum SL/TP distance, lot
  step/min/max) are handled defensively in `trade_manager.py` and `risk_manager.py` since brokers differ.
- **Telegram notifications** (`telegram_notifier.py`) run as a side-channel to logging, hooked in three
  spots: `trade_manager.open_trade()` fires `notify()` on a filled order; `core.run()` sends start/stop;
  and `core._run_cycle()` calls `notify_connection_lost/restored()` around reconnect. Trade *closes* are
  **not** sent from `close_trade()` (it's effectively unused in the loop) — instead
  `check_closed_positions(get_open_positions())` runs each cycle (right after `manage_open_trades`) and
  detects vanished tickets, querying `mt5.history_deals_get(position=...)` for the realized P&L. All
  sends are best-effort daemon threads (the shutdown message uses `block=True` so it isn't cut off); the
  whole module is a no-op unless `.env` creds are set, so it never affects trading.
