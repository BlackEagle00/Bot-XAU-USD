"""
Diario de eventos (JSONL) — una línea por decisión, para reconstruir después qué pasó y por qué.

Eventos: signal → rejected | authorized → refused | sent → filled → protected/unprotected → breaker.
Cada línea lleva la versión del código (git) y un hash de la configuración. Nunca credenciales:
las claves MT5_*/TELEGRAM_* y cualquier *PASSWORD*/*TOKEN* quedan fuera del hash y de los eventos.
"""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import config as _cfg
from .logger_config import logger

_DIR = Path(_cfg.__file__).resolve().parent
PATH = _DIR / "journal.jsonl"
_SECRET = ("MT5_", "TELEGRAM", "PASSWORD", "TOKEN")


def _version() -> str:
    try:
        run = lambda *a: subprocess.run(["git", *a], cwd=_DIR, capture_output=True, text=True, timeout=5).stdout.strip()
        rev = run("rev-parse", "--short", "HEAD")
        return (rev + ("-dirty" if run("status", "--porcelain") else "")) if rev else "nogit"
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def _config_hash() -> str:
    vals = {k: repr(v) for k, v in vars(_cfg).items()
            if k.isupper() and not any(s in k for s in _SECRET)}
    return hashlib.sha256(json.dumps(vals, sort_keys=True).encode()).hexdigest()[:12]


VERSION, CONFIG_HASH = _version(), _config_hash()


def log(event: str, **fields) -> None:
    """Agrega un evento al diario. Un fallo de disco avisa en el log pero no detiene el bot."""
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event,
           "symbol": getattr(_cfg, "SYMBOL", ""), "magic": getattr(_cfg, "MAGIC_NUMBER", None),
           "version": VERSION, "config": CONFIG_HASH, **fields}
    try:
        with open(PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.warning(f"No se pudo escribir el diario {PATH.name}: {exc}")
