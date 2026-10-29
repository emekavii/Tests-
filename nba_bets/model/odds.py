"""Matemática de apuestas: conversión de cuotas, quitar el margen (vig), EV y Kelly."""
from __future__ import annotations

import math


def american_to_decimal(american: float) -> float:
    if american > 0:
        return 1 + american / 100
    return 1 + 100 / abs(american)


def decimal_to_american(dec: float) -> int:
    if dec >= 2:
        return round((dec - 1) * 100)
    return round(-100 / (dec - 1))


def implied_prob(dec: float) -> float:
    return 1 / dec


def no_vig(dec_a: float, dec_b: float) -> tuple[float, float]:
    """Probabilidades 'justas' de un mercado de dos opciones, eliminando el margen de la casa."""
    pa, pb = implied_prob(dec_a), implied_prob(dec_b)
    total = pa + pb
    return pa / total, pb / total


def expected_value(prob: float, dec: float) -> float:
    """Beneficio esperado por unidad apostada."""
    return prob * dec - 1


def kelly(prob: float, dec: float, fraction: float = 0.25, cap: float = 0.03) -> float:
    """Fracción del bankroll a apostar (Kelly fraccional, con tope)."""
    b = dec - 1
    if b <= 0:
        return 0.0
    full = (prob * b - (1 - prob)) / b
    return max(0.0, min(full * fraction, cap))


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_above(mean: float, sd: float, line: float) -> float:
    """P(X > line) con X ~ Normal(mean, sd)."""
    if sd <= 0:
        return 1.0 if mean > line else 0.0
    return 1 - normal_cdf((line - mean) / sd)


def poisson_prob_above(mean: float, line: float) -> float:
    """P(X > line) con X ~ Poisson(mean). Útil para triples."""
    if mean <= 0:
        return 0.0
    k_max = math.floor(line)
    cdf = 0.0
    term = math.exp(-mean)
    for k in range(0, k_max + 1):
        if k > 0:
            term *= mean / k
        cdf += term
    return max(0.0, 1 - cdf)
