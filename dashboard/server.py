"""
Panel web local del bot — solo librería estándar.

Uso (desde la raíz del repo, con MT5 abierto en una cuenta DEMO):
    python dashboard/server.py            # abre http://127.0.0.1:8765
    python run.py dashboard

Arranca un trabajador por PERFIL de clase (dashboard/profiles/<clase>_<modo>, ver worker.py) y sirve:
  GET  /                      → la página (static/index.html con un token de sesión)
  GET  /api/analysis?mode=…   → análisis de todos los perfiles de ese modo (scalping | swing), unido
  GET  /api/news              → titulares (Google Noticias, CNBC, Investing.com) + calendario económico
  POST /api/trade             → abre una orden {symbol, action, mode} (exige el token)

Seguridad: escucha solo en 127.0.0.1; cada POST exige el token de esta sesión y un Origin/Host
locales (si no, cualquier web abierta en el navegador podría disparar órdenes contra localhost);
símbolo y acción contra lista blanca; máximo 1 orden por activo cada 5 s; la página no se puede
incrustar en otra (anti-clickjacking). Las noticias son datos de terceros: se limitan en tamaño,
se rechazan XML con DOCTYPE/ENTITY y enlaces que no sean http(s), y la página las escapa.
"""
import hmac
import itertools
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST, PORT = "127.0.0.1", 8765
HERE  = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
MODES = ("scalping", "swing")
PROFILES = sorted(d.name for d in (HERE / "profiles").iterdir()
                  if d.is_dir() and not d.name.startswith("_") and (d / "config.py").exists())
SECTION_ORDER = ("Divisas", "Metales", "Acciones", "Cripto (ETF)")
ORDER_COOLDOWN_SECS = 5
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

NEWS_SOURCES = (
    ("Google Noticias", "https://news.google.com/rss/search?q=mercados+financieros+oro+d%C3%B3lar+bolsa"
                        "&hl=es-419&gl=CO&ceid=CO:es-419"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
)
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEWS_REFRESH_SECS = 600
MAX_FEED_BYTES = 2_000_000


def validate_trade_request(headers, body: bytes, token: str, whitelist: dict, last_order: dict, now: float):
    """
    Revisa un POST /api/trade. Devuelve (status_http, error | dict_validado). Pura → probada en tests.
    whitelist = {modo: {símbolos}}; last_order = {símbolo: epoch de la última orden}.
    """
    if headers.get("Host") not in ALLOWED_HOSTS:
        return 403, "Host no permitido"
    origin = headers.get("Origin")
    if origin is not None and urlparse(origin).netloc not in ALLOWED_HOSTS:
        return 403, "Origen no permitido"
    if not hmac.compare_digest(headers.get("X-Token", ""), token):
        return 403, "Token inválido"
    if len(body) > 1024:
        return 413, "Petición demasiado grande"
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return 400, "JSON inválido"
    if not isinstance(data, dict):
        return 400, "JSON inválido"
    mode, sym, action = data.get("mode"), data.get("symbol"), data.get("action")
    if mode not in whitelist or sym not in whitelist[mode] or action not in ("BUY", "SELL"):
        return 400, "Activo, modo u orden no permitidos"
    if now - last_order.get(sym, 0) < ORDER_COOLDOWN_SECS:
        return 429, "Espera unos segundos antes de otra orden en este activo"
    return 200, {"mode": mode, "symbol": sym, "action": action}


# ═══════════════════════════════════════════════════════════════════════════════
# NOTICIAS (datos de terceros: se validan antes de usarlos)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_rss(raw: bytes, source: str, limit: int = 25) -> list:
    """Titulares de un RSS. Rechaza XML con DOCTYPE/ENTITY (bombas de entidades) y archivos enormes."""
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("feed demasiado grande")
    low = raw.lower()
    if b"<!doctype" in low or b"<!entity" in low:
        raise ValueError("feed con DOCTYPE/ENTITY rechazado")
    items = []
    for it in ET.fromstring(raw).iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        link = (it.findtext("link") or "").strip()
        if not title or urlparse(link).scheme not in ("http", "https"):
            continue
        try:
            ts = int(parsedate_to_datetime(it.findtext("pubDate")).timestamp())
        except (TypeError, ValueError):
            ts = None
        items.append({"title": title[:300], "link": link[:1000],
                      "source": " ".join((it.findtext("source") or source).split())[:80], "ts": ts})
    return items[:limit]


def parse_calendar(raw: bytes) -> list:
    """Eventos de alto y medio impacto de la semana (ForexFactory) con su hora como epoch."""
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("calendario demasiado grande")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("calendario inválido")
    out = []
    for ev in data:
        try:
            if ev.get("impact") not in ("High", "Medium"):
                continue
            dt = datetime.fromisoformat(ev["date"])
            dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            out.append({"title": str(ev.get("title", ""))[:120], "country": str(ev.get("country", ""))[:8],
                        "impact": ev["impact"], "ts": int(dt.timestamp()),
                        "forecast": str(ev.get("forecast") or "")[:20], "previous": str(ev.get("previous") or "")[:20]})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return sorted(out, key=lambda e: e["ts"])


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BotPanel)"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("respuesta demasiado grande")
    return raw


class News:
    """Refresca las noticias en segundo plano; una fuente caída no tumba las demás."""

    def __init__(self):
        self.data = {"items": [], "calendar": [], "updated": None, "errors": {}}
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            items, errors, calendar = [], {}, self.data["calendar"]
            for name, url in NEWS_SOURCES:
                try:
                    feed = sorted(parse_rss(_http_get(url), name), key=lambda x: x["ts"] or 0, reverse=True)
                    items += [{**it, "_rank": i} for i, it in enumerate(feed)]
                except Exception as exc:                 # red, formato o rechazo de seguridad
                    errors[name] = str(exc)[:120]
            try:
                calendar = parse_calendar(_http_get(CALENDAR_URL))
            except Exception as exc:
                errors["Calendario"] = str(exc)[:120]
            # intercala las fuentes (la más prolífica no tapa a las demás), lo más reciente primero en cada una
            items.sort(key=lambda x: (x["_rank"], -(x["ts"] or 0)))
            items = [{k: v for k, v in it.items() if k != "_rank"} for it in items]
            self.data = {"items": items[:60], "calendar": calendar, "updated": int(time.time()), "errors": errors}
            time.sleep(NEWS_REFRESH_SECS)


# ═══════════════════════════════════════════════════════════════════════════════
# TRABAJADORES (un proceso por perfil de clase)
# ═══════════════════════════════════════════════════════════════════════════════

class Worker:
    """Proceso worker.py de un perfil: guarda su último análisis y despacha órdenes."""

    def __init__(self, profile: str):
        self.profile, self.mode = profile, profile.rsplit("_", 1)[1]
        self.analysis, self.hello, self.fatal = None, None, None
        self.symbols, self._pending, self._ids, self._lock = set(), {}, itertools.count(1), threading.Lock()
        self.proc = subprocess.Popen(
            [sys.executable, str(HERE / "worker.py"), profile], cwd=str(HERE.parent),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "hello":
                self.hello = msg
                self.symbols = {s for group in msg["sections"].values() for s in group}
            elif kind == "analysis":
                self.analysis = msg["data"]
            elif kind == "fatal":
                self.fatal = msg.get("error")
            elif kind == "trade_result":
                slot = self._pending.get(msg.get("id"))
                if slot:
                    slot["result"] = msg
                    slot["event"].set()
        if not self.fatal:
            self.fatal = f"El análisis de {self.profile} se detuvo (revisa la consola)."

    def trade(self, symbol: str, action: str, timeout: float = 30.0) -> dict:
        req_id = next(self._ids)
        slot = {"event": threading.Event(), "result": None}
        self._pending[req_id] = slot
        with self._lock:
            self.proc.stdin.write(json.dumps({"type": "trade", "id": req_id, "symbol": symbol, "action": action,
                                              "ts": time.time()}) + "\n")   # el worker descarta órdenes viejas
            self.proc.stdin.flush()
        ok = slot["event"].wait(timeout)
        self._pending.pop(req_id, None)
        return slot["result"] if ok else {"ok": False, "reason": "MT5 no respondió a tiempo."}

    def stop(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


WORKERS: dict = {}
NEWS: News = None
LAST_ORDER: dict = {}
ORDER_LOCK = threading.Lock()


def merged_analysis(mode: str) -> dict:
    """Une los análisis de los perfiles de un modo en una sola respuesta para la página."""
    ws = [w for w in WORKERS.values() if w.mode == mode]
    ready = [w.analysis for w in ws if w.analysis]
    fatal = "; ".join(w.fatal for w in ws if w.fatal) or None
    if not ready:
        return {"mode": mode, "fatal": fatal, "ready": False, "data": None}
    sections = {}
    for a in ready:
        sections.update(a["sections"])
    ordered = {k: sections[k] for k in SECTION_ORDER if k in sections}
    ordered.update({k: v for k, v in sections.items() if k not in ordered})
    data = {"mode": mode, "label": ready[0]["label"], "server_time": max(a["server_time"] for a in ready),
            "profiles": [{"profile": a["profile"], "tfs": a["tfs"], "sections": list(a["sections"]), "edge": a.get("edge")}
                         for a in ready],
            "sections": ordered, "account": next((a["account"] for a in ready if a.get("account")), None),
            "pending": [w.profile for w in ws if not w.analysis and not w.fatal]}
    return {"mode": mode, "fatal": fatal, "ready": True, "data": data}


class Handler(BaseHTTPRequestHandler):
    server_version = "BotPanel"

    def log_message(self, fmt, *args):          # silencio: el polling llenaría la consola
        pass

    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                         "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
                         "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        if self.headers.get("Host") not in ALLOWED_HOSTS:      # anti DNS-rebinding
            return self._json(403, {"error": "Host no permitido"})
        url = urlparse(self.path)
        if url.path == "/":
            html = (HERE / "static" / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if url.path == "/api/analysis":
            mode = parse_qs(url.query).get("mode", ["swing"])[0]
            if mode not in MODES:
                return self._json(400, {"error": "modo inválido"})
            return self._json(200, merged_analysis(mode))
        if url.path == "/api/news":
            return self._json(200, NEWS.data)
        return self._json(404, {"error": "no encontrado"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/trade":
            return self._json(404, {"error": "no encontrado"})
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        body = self.rfile.read(length)
        whitelist = {m: set().union(*[w.symbols for w in WORKERS.values() if w.mode == m]) for m in MODES}
        with ORDER_LOCK:
            status, res = validate_trade_request(self.headers, body, TOKEN, whitelist, LAST_ORDER, time.time())
            if status == 200:
                LAST_ORDER[res["symbol"]] = time.time()
        if status != 200:
            return self._json(status, {"ok": False, "reason": res})
        worker = next(w for w in WORKERS.values() if w.mode == res["mode"] and res["symbol"] in w.symbols)
        return self._json(200, worker.trade(res["symbol"], res["action"]))


def main():
    global NEWS
    for p in PROFILES:
        WORKERS[p] = Worker(p)
    NEWS = News()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Panel en {url}  ({len(PROFILES)} perfiles: {', '.join(PROFILES)}) — Ctrl+C para detener", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        for w in WORKERS.values():
            w.stop()


if __name__ == "__main__":
    main()
