"""
Filtro de noticias — calendario económico (ForexFactory semanal, JSON gratuito).

Bloquea la apertura de trades en una ventana alrededor de eventos de ALTO impacto
de las divisas relevantes: los spikes de NFP / CPI / FOMC / BCE destruyen las señales
técnicas. Cachea el calendario en memoria y degrada con elegancia si no hay internet.

Uso:
    from news_filter import in_news_blackout
    bloqueado, evento = in_news_blackout()

Fuente: https://nfs.faireconomy.media/ff_calendar_thisweek.json
  Campos por evento: title, country (= divisa, p.ej. "USD"), date (ISO con offset),
  impact ("High"/"Medium"/"Low"/"Holiday"), forecast, previous.
"""
import json
import urllib.request
from datetime import datetime, timedelta, timezone

from .logger_config import logger
from config import (
    USE_NEWS_FILTER, NEWS_CURRENCIES, NEWS_IMPACTS,
    NEWS_BLACKOUT_BEFORE_MIN, NEWS_BLACKOUT_AFTER_MIN, NEWS_FAIL_OPEN,
)

_FF_URL       = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_REFRESH_SECS = 6 * 3600        # refrescar el calendario cada 6 horas

_cache_events = None            # lista de (datetime_utc, divisa, impacto, título)
_cache_time   = None            # cuándo se cargó por última vez


def _fetch_calendar():
    """Descarga y parsea el calendario semanal. Devuelve lista de eventos o None."""
    try:
        req = urllib.request.Request(_FF_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning(f"📰 No se pudo cargar el calendario económico: {exc}")
        return None

    events = []
    for it in data:
        try:
            dt = datetime.fromisoformat(it["date"])   # incluye offset, p.ej. -04:00
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            events.append((
                dt.astimezone(timezone.utc),
                str(it.get("country", "")).upper(),
                str(it.get("impact", "")),
                str(it.get("title", "")),
            ))
        except Exception:
            continue
    logger.info(f"📰 Calendario económico cargado: {len(events)} eventos esta semana.")
    return events


def _get_events():
    """Devuelve los eventos cacheados, refrescándolos si ya caducaron."""
    global _cache_events, _cache_time
    now = datetime.now(timezone.utc)
    if (_cache_events is None or _cache_time is None
            or (now - _cache_time).total_seconds() > _REFRESH_SECS):
        fetched = _fetch_calendar()
        if fetched is not None:
            _cache_events = fetched
            _cache_time   = now
    return _cache_events


def in_news_blackout(now=None):
    """
    Returns:
        (bloqueado: bool, evento: str)

    bloqueado=True si AHORA cae dentro de [evento - BEFORE, evento + AFTER] de una
    noticia de alto impacto en una divisa relevante (NEWS_CURRENCIES / NEWS_IMPACTS).
    Si el calendario no está disponible: respeta NEWS_FAIL_OPEN (True = no bloquea).
    """
    if not USE_NEWS_FILTER:
        return False, ""

    events = _get_events()
    if events is None:                          # calendario no disponible
        if NEWS_FAIL_OPEN:
            return False, ""                    # no congelar el bot si la API falla
        return True, "calendario no disponible (fail-closed)"

    now    = now or datetime.now(timezone.utc)
    before = timedelta(minutes=NEWS_BLACKOUT_BEFORE_MIN)
    after  = timedelta(minutes=NEWS_BLACKOUT_AFTER_MIN)
    cur    = {c.upper() for c in NEWS_CURRENCIES}
    imp    = set(NEWS_IMPACTS)

    for dt, country, impact, title in events:
        if country in cur and impact in imp:
            if (dt - before) <= now <= (dt + after):
                return True, f"{country} {impact}: {title} @ {dt.strftime('%H:%M UTC')}"
    return False, ""
