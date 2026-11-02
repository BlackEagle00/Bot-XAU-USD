"""
Noticias de hoy del calendario que usa el bot (bot_engine/news_filter, ForexFactory), en hora local, para los reportes
(pedido del usuario 2026-10-29: "A nivel de las noticias, adjunta también eso").
Muestra las divisas de NEWS_CURRENCIES con impacto Alto/Medio; "BLOQUEA" = impacto en NEWS_IMPACTS (veto 📰 ±ventana).
Los títulos vienen de una web externa: se muestran como dato, nunca se ejecutan.

Uso (desde la raíz):  python tools/news_next.py
"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "xauusd_scalping_bot"), str(ROOT)]
import config  # noqa: E402

config.LOG_FILE = str(ROOT / "logs" / "news_next.log")   # el logger del motor no escribe en el log del bot
from bot_engine import news_filter as nf  # noqa: E402

CACHE = ROOT / "logs" / "news_cache.json"


def events():
    """Calendario de la semana; se descarga como mucho 1 vez por hora (ForexFactory limita peticiones)."""
    fresh = CACHE.exists() and time.time() - CACHE.stat().st_mtime < 3600
    ev = None if fresh else nf._fetch_calendar()
    if ev:
        CACHE.write_text(json.dumps([(d.isoformat(), c, i, t) for d, c, i, t in ev]), encoding="utf-8")
    elif CACHE.exists():
        if not fresh:
            print(f"⚠ calendario no descargado: uso la copia de hace {(time.time() - CACHE.stat().st_mtime) / 3600:.1f} h")
        ev = [(datetime.fromisoformat(d), c, i, t) for d, c, i, t in json.loads(CACHE.read_text(encoding="utf-8"))]
    return ev


def status(dt, now, before, after):
    if now < dt - before:
        return f"en {int((dt - now).total_seconds() // 60)} min"
    return "EN VENTANA 📰" if now <= dt + after else "pasada"


if __name__ == "__main__":
    b, a = timedelta(minutes=10), timedelta(minutes=15)
    t0 = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    assert status(t0, t0 - timedelta(minutes=30), b, a) == "en 30 min"
    assert status(t0, t0 - timedelta(minutes=5), b, a) == "EN VENTANA 📰"
    assert status(t0, t0 + timedelta(minutes=16), b, a) == "pasada"

    ev = events()
    if not ev:
        sys.exit("📰 calendario no disponible (sin conexión y sin copia local)")
    now = datetime.now(timezone.utc)
    before = timedelta(minutes=config.NEWS_BLACKOUT_BEFORE_MIN)
    after = timedelta(minutes=config.NEWS_BLACKOUT_AFTER_MIN)
    cur, block = {c.upper() for c in config.NEWS_CURRENCIES}, set(config.NEWS_IMPACTS)
    today = now.astimezone().date()
    rel = sorted(e for e in ev if e[1] in cur and e[2] in ("High", "Medium"))
    hoy = [e for e in rel if e[0].astimezone().date() == today]
    print(f"📰 Noticias hoy ({', '.join(sorted(cur))}, Alto/Medio; veto ±{config.NEWS_BLACKOUT_BEFORE_MIN}/"
          f"{config.NEWS_BLACKOUT_AFTER_MIN} min si impacto {'/'.join(sorted(block))}): {len(hoy) or 'ninguna'}")
    for dt, c, imp, title in hoy:
        print(f"  {dt.astimezone():%H:%M} {c} {imp:6} {'BLOQUEA' if imp in block else 'info   '} "
              f"{status(dt, now, before, after):14} {title[:60]}")
    nxt = next((e for e in rel if e[2] in block and e[0] > now), None)
    if nxt:
        print(f"  próxima que bloquea: {nxt[0].astimezone():%a %d %H:%M} {nxt[1]} {nxt[3][:60]}")
