"""Proyección de player props (puntos, rebotes, asistencias, triples, PRA)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .odds import poisson_prob_above, prob_above

STAT_KEYS = {
    "points": ("pts",),
    "rebounds": ("reb",),
    "assists": ("ast",),
    "threes": ("fg3m",),
    "pra": ("pts", "reb", "ast"),
}


@dataclass
class PropProjection:
    mean: float
    sd: float
    games: int
    hit_rate: tuple[int, int] | None = None    # (veces por encima de la línea, partidos) últimos 10

    def p_over(self, market: str, line: float) -> float:
        if market == "threes":
            return poisson_prob_above(self.mean, line)
        return prob_above(self.mean, self.sd, line)


def stat_value(game: dict, market: str) -> float:
    return float(sum(game.get(k) or 0 for k in STAT_KEYS[market]))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def project(current: list[dict], previous: list[dict], market: str, *,
            opp_def_factor: float = 1.0, pace_factor: float = 1.0,
            line: float | None = None) -> PropProjection | None:
    """Media ponderada: últimos 5 (40%), temporada actual (35%), temporada anterior (25%).

    `current` y `previous` son game logs (más reciente primero). Se ignoran partidos con
    menos de 10 minutos (lesiones/descansos durante el partido).
    """
    cur = [stat_value(g, market) for g in current if (g.get("min") or 0) >= 10]
    prev = [stat_value(g, market) for g in previous if (g.get("min") or 0) >= 10]
    if not cur and not prev:
        return None

    parts = [(_mean(cur[:5]), 0.40 if len(cur) >= 3 else 0.15),
             (_mean(cur), 0.35 if len(cur) >= 5 else 0.20),
             (_mean(prev), 0.25 if prev else 0)]
    parts = [(m, w) for m, w in parts if m is not None and w > 0]
    total_w = sum(w for _, w in parts)
    mean = sum(m * w for m, w in parts) / total_w

    if market in ("points", "threes", "pra"):
        mean *= opp_def_factor * pace_factor
    else:
        mean *= pace_factor

    sample = (cur + prev)[:30]
    if len(sample) >= 2:
        avg = sum(sample) / len(sample)
        sd = math.sqrt(sum((x - avg) ** 2 for x in sample) / (len(sample) - 1))
    else:
        sd = 0.0
    sd = max(sd, math.sqrt(max(mean, 1)) * 1.1)   # suelo para muestras pequeñas

    hit = None
    if line is not None:
        recent = (cur + prev)[:10]
        if recent:
            hit = (sum(1 for x in recent if x > line), len(recent))
    return PropProjection(mean, sd, len(cur) + len(prev), hit)
