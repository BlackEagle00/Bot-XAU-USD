"""
Configuración de logging para el bot XAU/USD.
"""
import logging
import sys
from config import LOG_FILE


def setup_logger(name: str = "XAUBot") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # Evitar duplicar handlers

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Consola (INFO y superior)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    # Archivo (DEBUG y superior)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


logger = setup_logger()