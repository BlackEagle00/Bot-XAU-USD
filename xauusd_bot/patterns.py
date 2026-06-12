"""
Detección de Patrones de Velas Japonesas.

Patrones implementados (35+):
  — 1 vela:  Doji, Gravestone Doji, Dragonfly Doji, Hammer, Hanging Man,
              Inverted Hammer, Shooting Star, Marubozu (Bull/Bear), Spinning Top
  — 2 velas: Bullish/Bearish Engulfing, Bullish/Bearish Harami, Harami Cross,
              Tweezer Top/Bottom, Piercing Pattern, Dark Cloud Cover,
              Bullish/Bearish Kicker, Meeting Lines, On Neck
  — 3 velas: Morning Star, Evening Star, Morning Doji Star, Evening Doji Star,
              Three White Soldiers, Three Black Crows, Three Inside Up/Down,
              Three Outside Up/Down, Abandoned Baby (Bull/Bear), Tri-Star
  — 5 velas: Rising/Falling Three Methods

Puntuación:
  Positivo (+) = Señal ALCISTA
  Negativo (-) = Señal BAJISTA
  Magnitud 0.3–3.0 según relevancia del patrón
"""
import pandas as pd
import numpy as np
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# UTILIDADES INTERNAS
# ═══════════════════════════════════════════════════════════════════════════════

def _body(c) -> float:
    return abs(c["close"] - c["open"])

def _range(c) -> float:
    return c["high"] - c["low"]

def _upper_shadow(c) -> float:
    return c["high"] - max(c["close"], c["open"])

def _lower_shadow(c) -> float:
    return min(c["close"], c["open"]) - c["low"]

def _is_bull(c) -> bool:
    return c["close"] > c["open"]

def _is_bear(c) -> bool:
    return c["close"] < c["open"]

def _body_pct(c) -> float:
    """Body / range, protegido contra división por cero."""
    r = _range(c)
    return (_body(c) / r) if r > 1e-10 else 0.0

def _mid_body(c) -> float:
    return (c["open"] + c["close"]) / 2


# ═══════════════════════════════════════════════════════════════════════════════
# 1 VELA
# ═══════════════════════════════════════════════════════════════════════════════

def doji(c0) -> Optional[float]:
    """Doji genérico: cuerpo < 10% del rango. Indecisión."""
    if _range(c0) < 1e-10:
        return None
    return 0.2 if _body_pct(c0) < 0.10 else None


def gravestone_doji(c0) -> Optional[float]:
    """Gravestone Doji: mecha superior larga ≥ 60%, sin mecha inferior. BAJISTA."""
    r = _range(c0)
    if r < 1e-10:
        return None
    if (_body_pct(c0) < 0.06 and
            _upper_shadow(c0) >= r * 0.60 and
            _lower_shadow(c0) <= r * 0.10):
        return -1.5
    return None


def dragonfly_doji(c0) -> Optional[float]:
    """Dragonfly Doji: mecha inferior larga ≥ 60%, sin mecha superior. ALCISTA."""
    r = _range(c0)
    if r < 1e-10:
        return None
    if (_body_pct(c0) < 0.06 and
            _lower_shadow(c0) >= r * 0.60 and
            _upper_shadow(c0) <= r * 0.10):
        return 1.5
    return None


def long_legged_doji(c0) -> Optional[float]:
    """Doji patas largas: cuerpo tiny, mechas largas a ambos lados. Indecisión máxima."""
    r = _range(c0)
    if r < 1e-10:
        return None
    if (_body_pct(c0) < 0.08 and
            _upper_shadow(c0) >= r * 0.35 and
            _lower_shadow(c0) >= r * 0.35):
        return 0.3
    return None


def hammer(c0, trend: str = "down") -> Optional[float]:
    """
    Hammer: mecha inferior ≥ 2× cuerpo, mecha superior ≤ 0.5× cuerpo.
    ALCISTA cuando aparece tras tendencia bajista.
    """
    b = _body(c0)
    r = _range(c0)
    if r < 1e-10 or b < 1e-10:
        return None
    ls = _lower_shadow(c0)
    us = _upper_shadow(c0)
    if ls >= 2 * b and us <= b * 0.5 and _body_pct(c0) > 0.08:
        return 1.5 if trend == "down" else 0.6


def hanging_man(c0, trend: str = "up") -> Optional[float]:
    """Hanging Man: misma forma que Hammer en tendencia alcista. BAJISTA."""
    b = _body(c0)
    r = _range(c0)
    if r < 1e-10 or b < 1e-10:
        return None
    ls = _lower_shadow(c0)
    us = _upper_shadow(c0)
    if ls >= 2 * b and us <= b * 0.5 and _body_pct(c0) > 0.08:
        return -1.5 if trend == "up" else -0.6


def inverted_hammer(c0, trend: str = "down") -> Optional[float]:
    """Inverted Hammer: mecha superior larga, cuerpo pequeño, mínima mecha inferior. ALCISTA."""
    b = _body(c0)
    r = _range(c0)
    if r < 1e-10 or b < 1e-10:
        return None
    us = _upper_shadow(c0)
    ls = _lower_shadow(c0)
    if us >= 2 * b and ls <= b * 0.5 and _body_pct(c0) > 0.08:
        return 1.2 if trend == "down" else 0.5


def shooting_star(c0, trend: str = "up") -> Optional[float]:
    """Shooting Star: mecha superior larga ≥ 2× cuerpo, casi sin mecha inferior. BAJISTA."""
    b = _body(c0)
    r = _range(c0)
    if r < 1e-10 or b < 1e-10:
        return None
    us = _upper_shadow(c0)
    ls = _lower_shadow(c0)
    if us >= 2 * b and ls <= b * 0.3 and _body_pct(c0) > 0.05:
        return -1.5 if trend == "up" else -0.6


def marubozu_bull(c0) -> Optional[float]:
    """Marubozu Alcista: vela alcista sin mechas (body ≥ 90% del rango). ALCISTA fuerte."""
    if _is_bull(c0) and _body_pct(c0) >= 0.90:
        return 2.0
    return None


def marubozu_bear(c0) -> Optional[float]:
    """Marubozu Bajista: vela bajista sin mechas. BAJISTA fuerte."""
    if _is_bear(c0) and _body_pct(c0) >= 0.90:
        return -2.0
    return None


def spinning_top(c0) -> Optional[float]:
    """Spinning Top: cuerpo pequeño con mechas largas a ambos lados. Indecisión."""
    r = _range(c0)
    if r < 1e-10:
        return None
    b  = _body(c0)
    us = _upper_shadow(c0)
    ls = _lower_shadow(c0)
    if _body_pct(c0) < 0.35 and us > b * 0.5 and ls > b * 0.5:
        return 0.2
    return None


def high_wave(c0) -> Optional[float]:
    """High Wave: mechas muy largas, cuerpo muy pequeño. Alta incertidumbre."""
    r = _range(c0)
    if r < 1e-10:
        return None
    us = _upper_shadow(c0)
    ls = _lower_shadow(c0)
    if _body_pct(c0) < 0.15 and us > r * 0.35 and ls > r * 0.35:
        return 0.1
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 2 VELAS
# ═══════════════════════════════════════════════════════════════════════════════

def bullish_engulfing(c1, c0) -> Optional[float]:
    """Bullish Engulfing: vela alcista engloba completamente el cuerpo bajista anterior."""
    if _is_bear(c1) and _is_bull(c0):
        if c0["open"] <= c1["close"] and c0["close"] >= c1["open"]:
            if _body(c0) > _body(c1) * 1.1:  # Debe ser más grande
                return 2.0
    return None


def bearish_engulfing(c1, c0) -> Optional[float]:
    """Bearish Engulfing: vela bajista engloba completamente el cuerpo alcista anterior."""
    if _is_bull(c1) and _is_bear(c0):
        if c0["open"] >= c1["close"] and c0["close"] <= c1["open"]:
            if _body(c0) > _body(c1) * 1.1:
                return -2.0
    return None


def bullish_harami(c1, c0) -> Optional[float]:
    """Bullish Harami: vela alcista pequeña dentro del cuerpo bajista grande previo."""
    if _is_bear(c1) and _is_bull(c0):
        if (c0["open"] > c1["close"] and c0["close"] < c1["open"] and
                _body(c0) < _body(c1) * 0.55):
            return 1.0
    return None


def bearish_harami(c1, c0) -> Optional[float]:
    """Bearish Harami: vela bajista pequeña dentro del cuerpo alcista grande previo."""
    if _is_bull(c1) and _is_bear(c0):
        if (c0["open"] < c1["close"] and c0["close"] > c1["open"] and
                _body(c0) < _body(c1) * 0.55):
            return -1.0
    return None


def bullish_harami_cross(c1, c0) -> Optional[float]:
    """Bullish Harami Cross: la segunda vela es un Doji dentro del cuerpo bajista."""
    if _is_bear(c1) and _body_pct(c0) < 0.10:
        c0_mid = _mid_body(c0)
        c1_mid = _mid_body(c1)
        if abs(c0_mid - c1_mid) < _body(c1) * 0.5:
            return 1.3
    return None


def bearish_harami_cross(c1, c0) -> Optional[float]:
    """Bearish Harami Cross: la segunda vela es un Doji dentro del cuerpo alcista."""
    if _is_bull(c1) and _body_pct(c0) < 0.10:
        c0_mid = _mid_body(c0)
        c1_mid = _mid_body(c1)
        if abs(c0_mid - c1_mid) < _body(c1) * 0.5:
            return -1.3
    return None


def tweezer_bottom(c1, c0) -> Optional[float]:
    """Tweezer Bottom: dos velas con mínimos casi iguales. ALCISTA."""
    rng = _range(c0)
    if rng < 1e-10:
        return None
    if abs(c1["low"] - c0["low"]) <= rng * 0.03:
        if _is_bear(c1) and _is_bull(c0):
            return 1.5
    return None


def tweezer_top(c1, c0) -> Optional[float]:
    """Tweezer Top: dos velas con máximos casi iguales. BAJISTA."""
    rng = _range(c0)
    if rng < 1e-10:
        return None
    if abs(c1["high"] - c0["high"]) <= rng * 0.03:
        if _is_bull(c1) and _is_bear(c0):
            return -1.5
    return None


def piercing_pattern(c1, c0) -> Optional[float]:
    """
    Piercing Pattern: vela bajista grande + vela alcista que abre bajo
    el mínimo anterior y cierra sobre el 50% del cuerpo previo. ALCISTA.
    """
    if _is_bear(c1) and _is_bull(c0) and _body_pct(c1) > 0.5:
        midpoint = c1["open"] - _body(c1) * 0.5
        if c0["open"] < c1["close"] and c0["close"] > midpoint:
            return 1.5
    return None


def dark_cloud_cover(c1, c0) -> Optional[float]:
    """
    Dark Cloud Cover: vela alcista grande + vela bajista que abre sobre
    el máximo anterior y cierra bajo el 50% del cuerpo previo. BAJISTA.
    """
    if _is_bull(c1) and _is_bear(c0) and _body_pct(c1) > 0.5:
        midpoint = c1["open"] + _body(c1) * 0.5
        if c0["open"] > c1["close"] and c0["close"] < midpoint:
            return -1.5
    return None


def bullish_kicker(c1, c0) -> Optional[float]:
    """Bullish Kicker: vela bajista seguida de vela alcista fuerte con gap al alza."""
    if _is_bear(c1) and _is_bull(c0) and _body_pct(c0) > 0.60:
        if c0["open"] >= c1["open"]:
            return 2.0
    return None


def bearish_kicker(c1, c0) -> Optional[float]:
    """Bearish Kicker: vela alcista seguida de vela bajista fuerte con gap a la baja."""
    if _is_bull(c1) and _is_bear(c0) and _body_pct(c0) > 0.60:
        if c0["open"] <= c1["open"]:
            return -2.0
    return None


def meeting_lines_bull(c1, c0) -> Optional[float]:
    """Meeting Lines Alcista: dos velas de color opuesto con cierres casi iguales."""
    rng = _range(c0)
    if rng < 1e-10:
        return None
    if _is_bear(c1) and _is_bull(c0):
        if abs(c0["close"] - c1["close"]) <= rng * 0.03:
            return 1.0
    return None


def meeting_lines_bear(c1, c0) -> Optional[float]:
    """Meeting Lines Bajista."""
    rng = _range(c0)
    if rng < 1e-10:
        return None
    if _is_bull(c1) and _is_bear(c0):
        if abs(c0["close"] - c1["close"]) <= rng * 0.03:
            return -1.0
    return None


def on_neck_bull(c1, c0) -> Optional[float]:
    """On Neck (alcista): cierre de c0 ≈ mínimo de c1. Continuación bajista débil."""
    rng = _range(c1)
    if rng < 1e-10 or not _is_bear(c1):
        return None
    if _is_bull(c0) and abs(c0["close"] - c1["low"]) <= rng * 0.05:
        return -0.5  # Leve señal bajista (continuación)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 3 VELAS
# ═══════════════════════════════════════════════════════════════════════════════

def morning_star(c2, c1, c0) -> Optional[float]:
    """
    Morning Star: gran bajista → vela pequeña (indecisión) → gran alcista
    que cierra sobre el 50% de c2. ALCISTA fuerte.
    """
    if (not _is_bear(c2) or not _is_bull(c0)):
        return None
    if (_body_pct(c2) > 0.50 and
            _body(c1) < _body(c2) * 0.5 and
            _body_pct(c0) > 0.50 and
            c0["close"] > _mid_body(c2)):
        return 2.5
    return None


def evening_star(c2, c1, c0) -> Optional[float]:
    """
    Evening Star: gran alcista → vela pequeña → gran bajista
    que cierra bajo el 50% de c2. BAJISTA fuerte.
    """
    if (not _is_bull(c2) or not _is_bear(c0)):
        return None
    if (_body_pct(c2) > 0.50 and
            _body(c1) < _body(c2) * 0.5 and
            _body_pct(c0) > 0.50 and
            c0["close"] < _mid_body(c2)):
        return -2.5
    return None


def morning_doji_star(c2, c1, c0) -> Optional[float]:
    """Morning Doji Star: igual que Morning Star pero c1 es Doji. Más fuerte."""
    if (not _is_bear(c2) or not _is_bull(c0)):
        return None
    if (_body_pct(c2) > 0.50 and
            _body_pct(c1) < 0.10 and
            _body_pct(c0) > 0.50 and
            c0["close"] > _mid_body(c2)):
        return 2.8
    return None


def evening_doji_star(c2, c1, c0) -> Optional[float]:
    """Evening Doji Star: igual que Evening Star pero c1 es Doji. Más fuerte."""
    if (not _is_bull(c2) or not _is_bear(c0)):
        return None
    if (_body_pct(c2) > 0.50 and
            _body_pct(c1) < 0.10 and
            _body_pct(c0) > 0.50 and
            c0["close"] < _mid_body(c2)):
        return -2.8
    return None


def tri_star_bull(c2, c1, c0) -> Optional[float]:
    """Tri-Star Alcista: tres Dojis consecutivos con el del medio más bajo."""
    if (_body_pct(c2) < 0.10 and _body_pct(c1) < 0.10 and _body_pct(c0) < 0.10):
        if c1["low"] < c2["low"] and c1["low"] < c0["low"]:
            return 2.0
    return None


def tri_star_bear(c2, c1, c0) -> Optional[float]:
    """Tri-Star Bajista: tres Dojis consecutivos con el del medio más alto."""
    if (_body_pct(c2) < 0.10 and _body_pct(c1) < 0.10 and _body_pct(c0) < 0.10):
        if c1["high"] > c2["high"] and c1["high"] > c0["high"]:
            return -2.0
    return None


def three_white_soldiers(c2, c1, c0) -> Optional[float]:
    """
    Three White Soldiers: tres velas alcistas consecutivas con cuerpos grandes
    y cierres sucesivamente más altos. ALCISTA muy fuerte.
    """
    if (all(_is_bull(c) for c in [c2, c1, c0]) and
            all(_body_pct(c) > 0.50 for c in [c2, c1, c0]) and
            c1["close"] > c2["close"] and c0["close"] > c1["close"] and
            c1["open"]  > c2["open"]  and c0["open"]  > c1["open"]):
        return 3.0
    return None


def three_black_crows(c2, c1, c0) -> Optional[float]:
    """
    Three Black Crows: tres velas bajistas consecutivas con cuerpos grandes
    y cierres sucesivamente más bajos. BAJISTA muy fuerte.
    """
    if (all(_is_bear(c) for c in [c2, c1, c0]) and
            all(_body_pct(c) > 0.50 for c in [c2, c1, c0]) and
            c1["close"] < c2["close"] and c0["close"] < c1["close"] and
            c1["open"]  < c2["open"]  and c0["open"]  < c1["open"]):
        return -3.0
    return None


def three_inside_up(c2, c1, c0) -> Optional[float]:
    """Three Inside Up: Bullish Harami + confirmación alcista en c0."""
    if bullish_harami(c2, c1) and _is_bull(c0) and c0["close"] > c2["open"]:
        return 2.0
    return None


def three_inside_down(c2, c1, c0) -> Optional[float]:
    """Three Inside Down: Bearish Harami + confirmación bajista en c0."""
    if bearish_harami(c2, c1) and _is_bear(c0) and c0["close"] < c2["open"]:
        return -2.0
    return None


def three_outside_up(c2, c1, c0) -> Optional[float]:
    """Three Outside Up: Bullish Engulfing + confirmación alcista en c0."""
    if bullish_engulfing(c2, c1) and _is_bull(c0) and c0["close"] > c1["close"]:
        return 2.5
    return None


def three_outside_down(c2, c1, c0) -> Optional[float]:
    """Three Outside Down: Bearish Engulfing + confirmación bajista en c0."""
    if bearish_engulfing(c2, c1) and _is_bear(c0) and c0["close"] < c1["close"]:
        return -2.5
    return None


def abandoned_baby_bull(c2, c1, c0) -> Optional[float]:
    """
    Abandoned Baby Alcista: gran bajista + Doji con gap doble + gran alcista.
    Señal de reversión extremamente fuerte.
    """
    if (_is_bear(c2) and _body_pct(c2) > 0.5 and
            _body_pct(c1) < 0.10 and
            c1["low"]  > c2["low"] and    # gap entre c2 y c1
            c1["low"]  > c0["low"] and    # gap entre c1 y c0
            _is_bull(c0) and _body_pct(c0) > 0.5):
        return 3.0
    return None


def abandoned_baby_bear(c2, c1, c0) -> Optional[float]:
    """
    Abandoned Baby Bajista: gran alcista + Doji con gap doble + gran bajista.
    Señal de reversión extremamente fuerte.
    """
    if (_is_bull(c2) and _body_pct(c2) > 0.5 and
            _body_pct(c1) < 0.10 and
            c1["high"] < c2["high"] and
            c1["high"] < c0["high"] and
            _is_bear(c0) and _body_pct(c0) > 0.5):
        return -3.0
    return None


def advance_block(c2, c1, c0) -> Optional[float]:
    """
    Advance Block: tres alcistas pero cuerpos decrecientes y mechas superiores crecientes.
    Debilitamiento de la subida. BAJISTA leve.
    """
    if (all(_is_bull(c) for c in [c2, c1, c0]) and
            c1["close"] > c2["close"] and c0["close"] > c1["close"]):
        b2, b1, b0 = _body(c2), _body(c1), _body(c0)
        us2, us1, us0 = _upper_shadow(c2), _upper_shadow(c1), _upper_shadow(c0)
        if b2 > b1 > b0 and us0 > us1 > us2:
            return -1.0
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 5 VELAS
# ═══════════════════════════════════════════════════════════════════════════════

def rising_three_methods(candles: list) -> Optional[float]:
    """
    Rising Three Methods: gran alcista + 3 pequeñas bajistas dentro del rango
    + gran alcista que supera el máximo inicial. ALCISTA de continuación.
    """
    if len(candles) < 5:
        return None
    c4, c3, c2, c1, c0 = candles[-5], candles[-4], candles[-3], candles[-2], candles[-1]

    if (not (_is_bull(c4) and _body_pct(c4) > 0.50)):
        return None
    if (not all(_is_bear(c) for c in [c3, c2, c1])):
        return None
    # Las 3 pequeñas deben estar dentro del rango de c4
    if not (c4["low"] < c1["close"] and c3["close"] < c4["close"]):
        return None
    if _is_bull(c0) and c0["close"] > c4["close"] and _body_pct(c0) > 0.50:
        return 2.0
    return None


def falling_three_methods(candles: list) -> Optional[float]:
    """
    Falling Three Methods: gran bajista + 3 pequeñas alcistas dentro del rango
    + gran bajista que supera el mínimo inicial. BAJISTA de continuación.
    """
    if len(candles) < 5:
        return None
    c4, c3, c2, c1, c0 = candles[-5], candles[-4], candles[-3], candles[-2], candles[-1]

    if (not (_is_bear(c4) and _body_pct(c4) > 0.50)):
        return None
    if (not all(_is_bull(c) for c in [c3, c2, c1])):
        return None
    if not (c4["high"] > c1["close"] and c3["close"] > c4["close"]):
        return None
    if _is_bear(c0) and c0["close"] < c4["close"] and _body_pct(c0) > 0.50:
        return -2.0
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_patterns(df: pd.DataFrame, trend: str = "neutral") -> dict:
    """
    Analiza todos los patrones sobre el DataFrame.

    Args:
        df:    DataFrame OHLCV con al menos 5 velas.
        trend: "up" | "down" | "neutral" para contextualizar patrones de 1 vela.

    Returns:
        {
            "patterns": [{"name": str, "score": float}, ...],
            "score":    float  (suma limitada a ±4.0)
        }
    """
    if len(df) < 5:
        return {"patterns": [], "score": 0.0}

    rows = df.tail(5).to_dict("records")
    c4, c3, c2, c1, c0 = rows

    detected    = []
    total_score = 0.0

    def _check(name: str, score):
        nonlocal total_score
        if score is not None and score != 0:
            detected.append({"name": name, "score": float(score)})
            total_score += float(score)

    # ── 1 vela ─────────────────────────────────────────────────────────────────
    _check("Doji",               doji(c0))
    _check("Gravestone Doji",    gravestone_doji(c0))
    _check("Dragonfly Doji",     dragonfly_doji(c0))
    _check("Long-Legged Doji",   long_legged_doji(c0))
    _check("Hammer",             hammer(c0, trend))
    _check("Hanging Man",        hanging_man(c0, trend))
    _check("Inverted Hammer",    inverted_hammer(c0, trend))
    _check("Shooting Star",      shooting_star(c0, trend))
    _check("Marubozu Alcista",   marubozu_bull(c0))
    _check("Marubozu Bajista",   marubozu_bear(c0))
    _check("Spinning Top",       spinning_top(c0))
    _check("High Wave",          high_wave(c0))

    # ── 2 velas ────────────────────────────────────────────────────────────────
    _check("Bullish Engulfing",    bullish_engulfing(c1, c0))
    _check("Bearish Engulfing",    bearish_engulfing(c1, c0))
    _check("Bullish Harami",       bullish_harami(c1, c0))
    _check("Bearish Harami",       bearish_harami(c1, c0))
    _check("Bullish Harami Cross", bullish_harami_cross(c1, c0))
    _check("Bearish Harami Cross", bearish_harami_cross(c1, c0))
    _check("Tweezer Bottom",       tweezer_bottom(c1, c0))
    _check("Tweezer Top",          tweezer_top(c1, c0))
    _check("Piercing Pattern",     piercing_pattern(c1, c0))
    _check("Dark Cloud Cover",     dark_cloud_cover(c1, c0))
    _check("Bullish Kicker",       bullish_kicker(c1, c0))
    _check("Bearish Kicker",       bearish_kicker(c1, c0))
    _check("Meeting Lines (Bull)", meeting_lines_bull(c1, c0))
    _check("Meeting Lines (Bear)", meeting_lines_bear(c1, c0))
    _check("On Neck",              on_neck_bull(c1, c0))

    # ── 3 velas ────────────────────────────────────────────────────────────────
    _check("Morning Star",          morning_star(c2, c1, c0))
    _check("Evening Star",          evening_star(c2, c1, c0))
    _check("Morning Doji Star",     morning_doji_star(c2, c1, c0))
    _check("Evening Doji Star",     evening_doji_star(c2, c1, c0))
    _check("Tri-Star Alcista",      tri_star_bull(c2, c1, c0))
    _check("Tri-Star Bajista",      tri_star_bear(c2, c1, c0))
    _check("Three White Soldiers",  three_white_soldiers(c2, c1, c0))
    _check("Three Black Crows",     three_black_crows(c2, c1, c0))
    _check("Three Inside Up",       three_inside_up(c2, c1, c0))
    _check("Three Inside Down",     three_inside_down(c2, c1, c0))
    _check("Three Outside Up",      three_outside_up(c2, c1, c0))
    _check("Three Outside Down",    three_outside_down(c2, c1, c0))
    _check("Abandoned Baby (Bull)", abandoned_baby_bull(c2, c1, c0))
    _check("Abandoned Baby (Bear)", abandoned_baby_bear(c2, c1, c0))
    _check("Advance Block",         advance_block(c2, c1, c0))

    # ── 5 velas ────────────────────────────────────────────────────────────────
    _check("Rising Three Methods",  rising_three_methods(rows))
    _check("Falling Three Methods", falling_three_methods(rows))

    # Limitar puntuación total de patrones a ±4.0
    total_score = max(-4.0, min(4.0, total_score))

    return {
        "patterns": detected,
        "score": round(total_score, 3),
        "bullish": [p["name"] for p in detected if p["score"] > 0],
        "bearish": [p["name"] for p in detected if p["score"] < 0],
    }