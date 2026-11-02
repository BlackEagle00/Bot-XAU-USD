"""Resumen (solo lectura) de los bots desde los DEALS de MT5, por magic: últimos 30 min y desde START.
Uso: python bots_summary.py "AAAA-MM-DD HH:MM" BALANCE_INICIAL"""
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import MetaTrader5 as mt5

ROOT = Path(r"C:\Users\Andrés Bonilla\Documents\ProyectosClaude\Proyecto Bot XAUUSD Git\Bot-XAU-USD")
BOTS = {20260618: "swing", 20260621: "scalping", 20260622: "grid"}
start_local, bal0 = datetime.strptime(sys.argv[1], "%Y-%m-%d %H:%M"), float(sys.argv[2])
mt5.initialize()
# el tick del oro puede venir vacío o congelado (feed caído 2026-10-27): se toma el más reciente de dos símbolos
srv = max((t.time for s in ("XAUUSD", "EURUSD") if (t := mt5.symbol_info_tick(s))), default=0) or time.time() + 7 * 3600
start_srv = start_local.timestamp() + (srv - time.time())          # hora servidor ≈ local + desfase del bróker
deals = [d for d in mt5.history_deals_get(datetime.now(timezone.utc) - timedelta(days=3),
                                          datetime.now(timezone.utc) + timedelta(days=1)) or []
         if d.magic in BOTS and d.entry == 1 and d.time >= start_srv]
a, pos = mt5.account_info(), [p for p in (mt5.positions_get() or []) if p.magic in BOTS]
mt5.shutdown()

print(f"{datetime.now():%H:%M} | demo={a.trade_mode == 0} bal {a.balance:.2f} eq {a.equity:.2f} | "
      f"desde {sys.argv[1]}: {a.balance - bal0:+.2f} (balance inicial {bal0:.2f})")
for magic, name in BOTS.items():
    log = ROOT / f"xauusd_{'' if name == 'swing' else name + '_'}bot" / f"xauusd_{'' if name == 'swing' else name + '_'}bot.log"
    alive = log.exists() and time.time() - log.stat().st_mtime < 180
    ds = [d for d in deals if d.magic == magic]
    pnl = lambda xs: sum(d.profit + d.swap + d.commission for d in xs)
    last = [d for d in ds if d.time > srv - 1800]
    op = [p for p in pos if p.magic == magic]
    sl = sum(d.comment.startswith("[sl") for d in ds); tp = sum(d.comment.startswith("[tp") for d in ds)
    print(f"  {name:<8} {'VIVO' if alive else 'parado'} | abiertas {len(op)} ({sum(p.profit for p in op):+.2f}) | "
          f"30 min: {len(last)} cierres {pnl(last):+.2f} | total: {len(ds)} cierres {pnl(ds):+.2f} (TP {tp} / SL {sl})")
