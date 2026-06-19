"""
Motor de Señales — XAU/USD Scalping Bot

Sistema de puntuación ponderada (score máximo ≈ ±12):
┌──────────────────────┬───────┬───────────────────┐
│ Componente           │ Peso  │ Rango bruto        │
├──────────────────────┼───────┼───────────────────┤
│ EMAs (posición+cruce)│ ×1.0  │ -3.0  a +3.0       │
│ RSI                  │ ×0.9  │ -2.0  a +2.0       │
│ MACD                 │ ×0.9  │ -2.0  a +2.0       │
│ Patrones de velas    │ ×0.8  │ -4.0  a +4.0       │
│ Bollinger Bands      │ ×0.6  │ -2.0  a +2.0       │
│ Soporte/Resistencia  │ ×0.5  │ -1.5  a +1.5       │
│ VWAP                 │ ×0.3  │ -1.0  a +1.0       │
│ Volumen              │ ×0.2  │ -0.5  a +0.5       │
│ Confirmación TF tend.│ ×1.0  │ (del score EMA H4) │
│ Contexto macro D1    │ ×0.8  │ -2.0  a +2.0       │
└──────────────────────┴───────┴───────────────────┘

 score ≥ +MIN_SIGNAL_SCORE → BUY
 score ≤ -MIN_SIGNAL_SCORE → SELL

El contexto macro (D1) además actúa como FILTRO: con REQUIRE_MACRO_ALIGNMENT,
una tendencia diaria FUERTE veta las operaciones en su contra.
"""
import pandas as pd
from typing import Tuple
from logger_config import logger
from config import (
    RSI_OB, RSI_OS, MIN_SIGNAL_SCORE, ATR_VOLATILITY_MIN, SCORE_WEIGHTS,
    REQUIRE_TREND_ALIGNMENT, REQUIRE_MACRO_ALIGNMENT,
    RSI_NO_SELL_BELOW, RSI_NO_BUY_ABOVE,
    USE_ADX_FILTER, ADX_MIN_TREND, INTERMARKET_INVERSE,
)


# ═══════════════════════════════════════════════════════════════════════════════
# COMPONENTES INDIVIDUALES
# ═══════════════════════════════════════════════════════════════════════════════

def _determine_trend(ind: dict) -> str:
    """
    Determina la tendencia de fondo con las EMAs.
    Returns: "up" | "down" | "neutral"
    """
    e9, e21, e50, e200 = (
        ind.get("ema9"), ind.get("ema21"),
        ind.get("ema50"), ind.get("ema200")
    )
    if None in [e9, e21, e50, e200]:
        return "neutral"
    if e9 > e21 > e50 and e50 > e200:
        return "up"
    if e9 < e21 < e50 and e50 < e200:
        return "down"
    # Tendencia parcial
    if e9 > e50:
        return "up"
    if e9 < e50:
        return "down"
    return "neutral"


def _score_ema(ind: dict, price: float) -> Tuple[float, list]:
    """
    Puntuación EMA. Evalúa:
      • Posición del precio respecto a cada EMA
      • Alineación en cascada (EMA9 > EMA21 > EMA50 > EMA200)
      • Cruce reciente de EMA9 / EMA21
    Rango: -3.0 a +3.0
    """
    e9, e21, e50, e200 = (
        ind.get("ema9"), ind.get("ema21"),
        ind.get("ema50"), ind.get("ema200")
    )
    e9_p  = ind.get("ema9_prev")
    e21_p = ind.get("ema21_prev")
    notes, score = [], 0.0

    if None in [e9, e21, e50, e200]:
        return 0.0, notes

    # Posición del precio
    if price > e9:   score += 0.30; notes.append("Precio > EMA9")
    else:             score -= 0.30
    if price > e21:  score += 0.40; notes.append("Precio > EMA21")
    else:             score -= 0.40
    if price > e50:  score += 0.45; notes.append("Precio > EMA50")
    else:             score -= 0.45
    if price > e200: score += 0.45; notes.append("Precio > EMA200")
    else:             score -= 0.45

    # Alineación en cascada
    if e9 > e21 > e50 > e200:
        score += 1.4; notes.append("✅ EMAs 100% alcistas")
    elif e9 < e21 < e50 < e200:
        score -= 1.4; notes.append("🔻 EMAs 100% bajistas")
    elif e9 > e21 > e50:
        score += 0.8; notes.append("EMA9>21>50 alcista")
    elif e9 < e21 < e50:
        score -= 0.8; notes.append("EMA9<21<50 bajista")

    # Cruce EMA9/EMA21 (señal de momentum)
    if None not in [e9_p, e21_p]:
        if e9_p <= e21_p and e9 > e21:
            score += 0.5; notes.append("🔀 Cruce alcista EMA9/21")
        elif e9_p >= e21_p and e9 < e21:
            score -= 0.5; notes.append("🔀 Cruce bajista EMA9/21")

    return max(-3.0, min(3.0, score)), notes


def _score_rsi(ind: dict) -> Tuple[float, list]:
    """
    Puntuación RSI. Evalúa zonas y dirección.
    Rango: -2.0 a +2.0
    """
    rsi   = ind.get("rsi")
    rsi_p = ind.get("rsi_prev")
    notes, score = [], 0.0

    if rsi is None:
        return 0.0, notes

    # Zonas de sobrecompra / sobreventa
    if rsi <= RSI_OS:           # < 30 sobreventa
        score += 1.5; notes.append(f"RSI sobreventa ({rsi:.1f})")
    elif rsi <= 40:
        score += 0.7; notes.append(f"RSI zona alcista ({rsi:.1f})")
    elif rsi >= RSI_OB:         # > 70 sobrecompra
        score -= 1.5; notes.append(f"RSI sobrecompra ({rsi:.1f})")
    elif rsi >= 60:
        score -= 0.7; notes.append(f"RSI zona bajista ({rsi:.1f})")
    # Zona neutra 40-60 → no suma ni resta

    # Dirección del RSI
    if rsi_p is not None:
        if rsi > rsi_p:    score += 0.3; notes.append("RSI ↑ subiendo")
        elif rsi < rsi_p:  score -= 0.3; notes.append("RSI ↓ bajando")

    # Divergencia básica: RSI fuertemente en zona y virando
    if rsi_p is not None:
        if rsi_p < RSI_OS and rsi > rsi_p:
            score += 0.3; notes.append("RSI saliendo de sobreventa ↗")
        elif rsi_p > RSI_OB and rsi < rsi_p:
            score -= 0.3; notes.append("RSI saliendo de sobrecompra ↘")

    return max(-2.0, min(2.0, score)), notes


def _score_macd(ind: dict) -> Tuple[float, list]:
    """
    Puntuación MACD. Evalúa línea, señal, histograma y cruces.
    Rango: -2.0 a +2.0
    """
    macd   = ind.get("macd")
    sig    = ind.get("macd_signal")
    hist   = ind.get("macd_hist")
    m_p    = ind.get("macd_prev")
    s_p    = ind.get("macd_sig_prev")
    h_p    = ind.get("macd_hist_prev")
    notes, score = [], 0.0

    if None in [macd, sig, hist]:
        return 0.0, notes

    # MACD vs señal
    if macd > sig:    score += 0.5; notes.append("MACD > Señal")
    else:              score -= 0.5

    # MACD vs cero
    if macd > 0:      score += 0.3; notes.append("MACD > 0")
    else:              score -= 0.3

    # Histograma: positivo y creciendo es fuerte
    if hist > 0:
        score += 0.3
        if h_p is not None and hist > h_p:
            score += 0.2; notes.append("Histograma MACD ↑ creciendo")
    else:
        score -= 0.3
        if h_p is not None and hist < h_p:
            score -= 0.2; notes.append("Histograma MACD ↓ cayendo")

    # Cruce MACD/Señal (el más poderoso)
    if None not in [m_p, s_p]:
        if m_p <= s_p and macd > sig:
            score += 0.8; notes.append("✅ Cruce alcista MACD/Señal")
        elif m_p >= s_p and macd < sig:
            score -= 0.8; notes.append("🔻 Cruce bajista MACD/Señal")

    return max(-2.0, min(2.0, score)), notes


def _score_bollinger(ind: dict, price: float) -> Tuple[float, list]:
    """
    Puntuación Bollinger Bands. Evalúa %B, posición vs media, squeeze.
    Rango: -2.0 a +2.0
    """
    bb_u   = ind.get("bb_upper")
    bb_l   = ind.get("bb_lower")
    bb_m   = ind.get("bb_mid")
    bb_pct = ind.get("bb_pct")
    bb_w   = ind.get("bb_width")
    bb_wp  = ind.get("bb_width_prev")
    notes, score = [], 0.0

    if None in [bb_u, bb_l, bb_m, bb_pct]:
        return 0.0, notes

    # %B: posición del precio en las bandas
    if bb_pct < 0.0:
        score += 1.5; notes.append(f"%B fuera banda inferior ({bb_pct:.2f}) 📈")
    elif bb_pct < 0.20:
        score += 1.0; notes.append(f"%B banda baja ({bb_pct:.2f})")
    elif bb_pct < 0.35:
        score += 0.4; notes.append(f"%B tercio inferior ({bb_pct:.2f})")
    elif bb_pct > 1.0:
        score -= 1.5; notes.append(f"%B fuera banda superior ({bb_pct:.2f}) 📉")
    elif bb_pct > 0.80:
        score -= 1.0; notes.append(f"%B banda alta ({bb_pct:.2f})")
    elif bb_pct > 0.65:
        score -= 0.4; notes.append(f"%B tercio superior ({bb_pct:.2f})")

    # Precio vs media de BB
    if price > bb_m:   score += 0.3; notes.append("Precio > BB media")
    else:               score -= 0.3

    # Squeeze (ancho decreció → expansión próxima, señal neutral de preparación)
    if bb_w is not None and bb_wp is not None:
        if bb_w < bb_wp * 0.80:
            notes.append("⚡ BB Squeeze — expansión próxima")

    return max(-2.0, min(2.0, score)), notes


def _score_vwap(ind: dict, price: float) -> Tuple[float, list]:
    """
    Puntuación VWAP. Precio > VWAP = sesgo alcista.
    Rango: -1.0 a +1.0
    """
    vwap = ind.get("vwap")
    notes = []

    if vwap is None:
        return 0.0, notes

    diff_pct = (price - vwap) / vwap * 100

    if price > vwap:
        score = min(1.0, 0.4 + abs(diff_pct) * 5)
        notes.append(f"Precio > VWAP (+{diff_pct:.2f}%)")
    else:
        score = max(-1.0, -0.4 - abs(diff_pct) * 5)
        notes.append(f"Precio < VWAP ({diff_pct:.2f}%)")

    return score, notes


def _score_volume(ind: dict) -> Tuple[float, list]:
    """
    Puntuación volumen. Alto volumen confirma el movimiento.
    Rango: -0.5 a +0.5
    """
    vol    = ind.get("volume")
    vol_ma = ind.get("volume_ma")
    notes  = []

    if None in [vol, vol_ma] or vol_ma == 0:
        return 0.0, notes

    ratio = vol / vol_ma

    if ratio >= 2.0:
        notes.append(f"Volumen muy alto ({ratio:.1f}× media) 🔥"); return 0.5, notes
    elif ratio >= 1.3:
        notes.append(f"Volumen alto ({ratio:.1f}× media) ✅");      return 0.3, notes
    elif ratio >= 0.8:
        notes.append(f"Volumen normal ({ratio:.1f}× media)");        return 0.1, notes
    else:
        notes.append(f"Volumen bajo ({ratio:.1f}× media) ⚠");       return -0.3, notes


def _score_support_resistance(ind: dict, price: float) -> Tuple[float, list]:
    """
    Puntuación S/R. Precio cerca de soporte → alcista; cerca de resistencia → bajista.
    Rango: -1.5 a +1.5
    """
    supports    = ind.get("supports", [])
    resistances = ind.get("resistances", [])
    atr         = ind.get("atr") or 1.0
    notes, score = [], 0.0

    tol_near = atr * 0.5    # Tocando el nivel
    tol_close = atr * 1.2   # Dentro de 1.2x ATR

    # Verificar soportes (bullish proximity)
    for sup in supports[:2]:
        dist = price - sup
        if dist < 0:               # Precio BAJO el soporte → roto
            score -= 0.5; notes.append(f"Soporte roto ${sup:.2f} 🔻"); break
        elif dist <= tol_near:
            score += 1.5; notes.append(f"Precio en soporte ${sup:.2f} 📈"); break
        elif dist <= tol_close:
            score += 0.5; notes.append(f"Cerca de soporte ${sup:.2f}"); break

    # Verificar resistencias (bearish proximity)
    for res in resistances[:2]:
        dist = res - price
        if dist < 0:               # Precio SOBRE la resistencia → rota
            score += 0.5; notes.append(f"Resistencia rota ${res:.2f} 📈"); break
        elif dist <= tol_near:
            score -= 1.5; notes.append(f"Precio en resistencia ${res:.2f} 📉"); break
        elif dist <= tol_close:
            score -= 0.5; notes.append(f"Cerca de resistencia ${res:.2f}"); break

    return max(-1.5, min(1.5, score)), notes


def _score_macro(ind: dict, price: float) -> Tuple[float, str, bool, list]:
    """
    Contexto macro del timeframe superior (D1 en el Oro).

    Evalúa la tendencia DIARIA con las EMAs para dar un sesgo direccional al
    score y clasificar la tendencia macro. Sirve a dos propósitos:
      • Nudge: suma/resta al score total a favor del diario (ponderado por
        SCORE_WEIGHTS["macro_tf"]). Máx ±2.0 antes de ponderar → no dispara
        una señal por sí solo, solo inclina la balanza.
      • Filtro: si `strong` es True (las 4 EMAs diarias en cascada perfecta),
        generate_signal veta las operaciones contra esa tendencia.

    Returns:
        (score, trend, strong, notes)
        score : -2.0 a +2.0  (sesgo macro, antes de ponderar)
        trend : "up" | "down" | "neutral"
        strong: True si EMA9>EMA21>EMA50>EMA200 (o el orden inverso)
        notes : list[str]
    """
    e9, e21, e50, e200 = (
        ind.get("ema9"), ind.get("ema21"),
        ind.get("ema50"), ind.get("ema200")
    )
    notes: list = []
    if None in [e9, e21, e50, e200]:
        return 0.0, "neutral", False, notes

    score, trend, strong = 0.0, "neutral", False

    # Alineación de las EMAs diarias
    if e9 > e21 > e50 > e200:
        score, trend, strong = 2.0, "up", True
        notes.append("🌐 D1: tendencia macro ALCISTA fuerte (EMAs en cascada)")
    elif e9 < e21 < e50 < e200:
        score, trend, strong = -2.0, "down", True
        notes.append("🌐 D1: tendencia macro BAJISTA fuerte (EMAs en cascada)")
    elif e9 > e50:
        score, trend = 1.0, "up"
        notes.append("🌐 D1: sesgo macro alcista (parcial)")
    elif e9 < e50:
        score, trend = -1.0, "down"
        notes.append("🌐 D1: sesgo macro bajista (parcial)")
    else:
        notes.append("🌐 D1: sin tendencia macro definida")

    # Precio respecto a la EMA200 diaria (la gran divisoria alcista/bajista)
    if price > e200:
        score += 0.5; notes.append("🌐 D1: precio sobre EMA200 (zona alcista)")
    else:
        score -= 0.5; notes.append("🌐 D1: precio bajo EMA200 (zona bajista)")

    return max(-2.0, min(2.0, score)), trend, strong, notes


def _score_orderflow(delta) -> Tuple[float, list]:
    """
    Presión compradora/vendedora por ticks (proxy del "volumen de compra").
    delta ∈ [-1, 1]: +1 = solo compras, -1 = solo ventas. Confirma la dirección.
    Rango: -1.0 a +1.0
    """
    notes = []
    if delta is None:
        return 0.0, notes
    score = max(-1.0, min(1.0, float(delta)))
    if delta >= 0.15:
        notes.append(f"Order-flow comprador ({delta:+.2f}) 🟢")
    elif delta <= -0.15:
        notes.append(f"Order-flow vendedor ({delta:+.2f}) 🔴")
    else:
        notes.append(f"Order-flow neutro ({delta:+.2f})")
    return score, notes


def _score_intermarket(bias, inverse: bool) -> Tuple[float, list]:
    """
    Sesgo inter-mercado según el índice dólar (DXY).
    `bias` = (trend, strong) con trend ∈ {"up","down","neutral"}, o None.
    Con inverse=True (oro/EUR), un dólar BAJISTA es alcista para el activo.
    Rango: -1.5 a +1.5
    """
    notes = []
    if not bias:
        return 0.0, notes
    trend, strong = bias
    if trend == "neutral":
        notes.append("🌐 Inter-mercado (DXY) sin dirección")
        return 0.0, notes

    mag     = 1.5 if strong else 0.8
    dxy_dir = 1.0 if trend == "up" else -1.0
    score   = (-dxy_dir if inverse else dxy_dir) * mag
    sesgo   = "alcista" if score > 0 else "bajista"
    notes.append(f"🌐 DXY {trend} → sesgo {sesgo} para el activo ({score:+.1f})")
    return score, notes


# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def generate_signal(
    price: float,
    ind_primary: dict,
    ind_trend: dict,
    patterns: dict,
    atr: float,
    ind_higher: dict = None,
    orderflow: float = None,
    intermarket: tuple = None,
) -> dict:
    """
    Genera la señal de trading combinando todos los análisis.

    Args:
        price:       Precio actual mid (bid+ask)/2
        ind_primary: Indicadores del TF primario (H1)
        ind_trend:   Indicadores del TF de tendencia (H4)
        patterns:    Resultado de analyze_patterns()
        atr:         ATR actual en precio
        ind_higher:  Indicadores del TF macro (D1). Opcional: si es None se
                     omite el contexto/ filtro macro.

    Returns:
        {
          "action"    : "BUY" | "SELL" | "HOLD",
          "score"     : float,
          "reasons"   : list[str],
          "atr"       : float,
          "trend"     : str,
          "breakdown" : dict  (puntuación por componente)
        }
    """
    # ── Filtro de volatilidad mínima ──────────────────────────────────────────
    if atr < ATR_VOLATILITY_MIN:
        return {
            "action": "HOLD",
            "score": 0.0,
            "reasons": [f"ATR {atr:.3f} < mínimo {ATR_VOLATILITY_MIN} (mercado plano)"],
            "atr": atr, "trend": "neutral", "breakdown": {}
        }

    trend = _determine_trend(ind_primary)
    w = SCORE_WEIGHTS

    # ── Puntuaciones individuales (TF primario) ───────────────────────────────
    s_ema,  n_ema  = _score_ema(ind_primary, price)
    s_rsi,  n_rsi  = _score_rsi(ind_primary)
    s_macd, n_macd = _score_macd(ind_primary)
    s_bb,   n_bb   = _score_bollinger(ind_primary, price)
    s_vwap, n_vwap = _score_vwap(ind_primary, price)
    s_vol,  n_vol  = _score_volume(ind_primary)
    s_sr,   n_sr   = _score_support_resistance(ind_primary, price)

    # ── Confirmación por TF de tendencia (H4) ─────────────────────────────────
    s_trend_ema, n_trend = _score_ema(ind_trend, price)
    s_trend_conf = s_trend_ema * w["trend_tf"]

    # ── Contexto macro del TF superior (D1) ───────────────────────────────────
    s_macro_raw, macro_trend, macro_strong, n_macro = 0.0, "neutral", False, []
    if ind_higher:
        s_macro_raw, macro_trend, macro_strong, n_macro = _score_macro(ind_higher, price)
    s_macro = s_macro_raw * w.get("macro_tf", 0.0)

    # ── Order-flow (presión compradora/vendedora por ticks) ───────────────────
    s_of, n_of = _score_orderflow(orderflow)

    # ── Inter-mercado (sesgo DXY, inverso para oro/EUR) ───────────────────────
    s_im, n_im = _score_intermarket(intermarket, INTERMARKET_INVERSE)

    # ── Puntuación de patrones de velas ───────────────────────────────────────
    s_pat = patterns.get("score", 0.0)
    pat_names_bull = patterns.get("bullish", [])
    pat_names_bear = patterns.get("bearish", [])

    # ── Suma ponderada total ──────────────────────────────────────────────────
    total = (
        s_ema   * w["ema"]      +
        s_rsi   * w["rsi"]      +
        s_macd  * w["macd"]     +
        s_pat   * w["patterns"] +
        s_bb    * w["bb"]       +
        s_sr    * w["sr"]       +
        s_vwap  * w["vwap"]     +
        s_vol   * w["volume"]   +
        s_trend_conf            +
        s_macro                 +
        s_of * w.get("orderflow", 0.0)   +
        s_im * w.get("intermarket", 0.0)
    )

    # ── Consolidar razones ────────────────────────────────────────────────────
    reasons = [f"Tendencia: {trend.upper()} | Score total: {total:+.2f}"]
    for note_group in [n_ema, n_rsi, n_macd, n_bb, n_vwap, n_vol, n_sr, n_macro, n_of, n_im]:
        reasons.extend(note_group)
    if pat_names_bull:
        reasons.append("🕯 Patrones alcistas: " + ", ".join(pat_names_bull))
    if pat_names_bear:
        reasons.append("🕯 Patrones bajistas: " + ", ".join(pat_names_bear))

    # ── Decisión ─────────────────────────────────────────────────────────────
    if total >= MIN_SIGNAL_SCORE:
        action = "BUY"
    elif total <= -MIN_SIGNAL_SCORE:
        action = "SELL"
    else:
        action = "HOLD"

    # ── Filtro de alineación de tendencia ─────────────────────────────────────
    # En swing trading solo operamos a favor de la tendencia dominante.
    # Un BUY en tendencia bajista o SELL en tendencia alcista aumenta el riesgo.
    if REQUIRE_TREND_ALIGNMENT and action != "HOLD":
        if trend == "up" and action == "SELL":
            reasons.append(
                f"⛔ SELL bloqueado: tendencia H1 alcista — solo BUY permitido"
            )
            action = "HOLD"
        elif trend == "down" and action == "BUY":
            reasons.append(
                f"⛔ BUY bloqueado: tendencia H1 bajista — solo SELL permitido"
            )
            action = "HOLD"

    # ── Filtro de contexto macro (D1) ─────────────────────────────────────────
    # Si el diario marca una tendencia FUERTE (EMAs en cascada), no operamos en
    # su contra: un BUY contra un D1 bajista fuerte suele ser una trampa alcista
    # (rebote dentro de tendencia mayor), y viceversa. Solo veta tendencias macro
    # decididas; en D1 mixto/neutral deja que decida el H1.
    if REQUIRE_MACRO_ALIGNMENT and action != "HOLD" and macro_strong:
        if macro_trend == "up" and action == "SELL":
            reasons.append("⛔ SELL bloqueado: contexto macro D1 ALCISTA fuerte")
            action = "HOLD"
        elif macro_trend == "down" and action == "BUY":
            reasons.append("⛔ BUY bloqueado: contexto macro D1 BAJISTA fuerte")
            action = "HOLD"

    # ── Filtro anti-agotamiento (extremos de RSI) ─────────────────────────────
    # No abrir NUEVAS entradas donde el movimiento suele agotarse y revertir:
    # vender con RSI sobrevendido = "vender en el suelo"; comprar con RSI
    # sobrecomprado = "comprar en el techo". Justo lo que castiga al apilar trades
    # de tendencia hasta el final del movimiento (rebote → todas tocan SL).
    rsi_now = ind_primary.get("rsi")
    if rsi_now is not None and action != "HOLD":
        if action == "SELL" and rsi_now <= RSI_NO_SELL_BELOW:
            reasons.append(
                f"⛔ SELL bloqueado: RSI {rsi_now:.0f} sobrevendido (posible suelo, no vender el fondo)"
            )
            action = "HOLD"
        elif action == "BUY" and rsi_now >= RSI_NO_BUY_ABOVE:
            reasons.append(
                f"⛔ BUY bloqueado: RSI {rsi_now:.0f} sobrecomprado (posible techo, no comprar el techo)"
            )
            action = "HOLD"

    # ── Filtro ADX (fuerza de tendencia) ──────────────────────────────────────
    # El bot es seguidor de tendencia: en mercado lateral (ADX bajo) los cruces son
    # ruido y suelen terminar en SL. Si la tendencia no tiene fuerza, no abrimos.
    adx_now = ind_primary.get("adx")
    if USE_ADX_FILTER and adx_now is not None and action != "HOLD":
        if adx_now < ADX_MIN_TREND:
            reasons.append(
                f"⛔ {action} bloqueado: ADX {adx_now:.0f} < {ADX_MIN_TREND} "
                f"(mercado lateral, tendencia sin fuerza)"
            )
            action = "HOLD"

    breakdown = {
        "ema": round(s_ema * w["ema"], 3),
        "rsi": round(s_rsi * w["rsi"], 3),
        "macd": round(s_macd * w["macd"], 3),
        "bollinger": round(s_bb * w["bb"], 3),
        "patterns": round(s_pat * w["patterns"], 3),
        "sr": round(s_sr * w["sr"], 3),
        "vwap": round(s_vwap * w["vwap"], 3),
        "volume": round(s_vol * w["volume"], 3),
        "trend_confirm": round(s_trend_conf, 3),
        "macro": round(s_macro, 3),
        "orderflow": round(s_of * w.get("orderflow", 0.0), 3),
        "intermarket": round(s_im * w.get("intermarket", 0.0), 3),
    }

    logger.info(
        f"📊 {action:4s} | Score: {total:+6.2f} | "
        f"EMA:{s_ema*w['ema']:+.2f} RSI:{s_rsi*w['rsi']:+.2f} "
        f"MACD:{s_macd*w['macd']:+.2f} BB:{s_bb*w['bb']:+.2f} "
        f"Pat:{s_pat*w['patterns']:+.2f} S/R:{s_sr*w['sr']:+.2f} "
        f"Macro:{s_macro:+.2f} OF:{s_of*w.get('orderflow',0.0):+.2f} "
        f"IM:{s_im*w.get('intermarket',0.0):+.2f} | "
        f"ADX:{(adx_now if adx_now is not None else 0):.0f} | "
        f"Tendencia: {trend} | D1: {macro_trend} | ATR: {atr:.3f}"
    )

    return {
        "action":    action,
        "score":     round(total, 4),
        "reasons":   reasons,
        "atr":       atr,
        "trend":     trend,
        "breakdown": breakdown,
    }