"""Proyección de marcador de un partido a partir de ratings ofensivos/defensivos y ritmo.

puntos_local = posesiones * ORtg_local * (DRtg_visitante / DRtg_liga) / 100 + ventaja_campo/2
Ajustes: back-to-back y bajas importantes. El margen y el total se modelan como normales.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .odds import normal_cdf, prob_above

LEAGUE_DEFAULT = {"off": 114.5, "def": 114.5, "pace": 99.5}
HOME_ADVANTAGE = 2.3      # puntos de margen
B2B_PENALTY = 1.5         # puntos que pierde un equipo en back-to-back
MARGIN_SD = 12.5          # desviación típica histórica del margen NBA
TOTAL_SD = 18.0           # desviación típica histórica del total NBA
RECENT_WEIGHT = 0.35      # peso de los últimos 10 partidos frente a la temporada


@dataclass
class Projection:
    home_pts: float
    away_pts: float
    notes: list[str] = field(default_factory=list)

    @property
    def margin(self) -> float:      # local - visitante
        return self.home_pts - self.away_pts

    @property
    def total(self) -> float:
        return self.home_pts + self.away_pts

    def p_home_win(self) -> float:
        return normal_cdf(self.margin / MARGIN_SD)

    def p_cover(self, side: str, handicap: float) -> float:
        """Probabilidad de cubrir un hándicap (handicap desde la perspectiva de `side`)."""
        side_margin = self.margin if side == "home" else -self.margin
        return prob_above(side_margin + handicap, MARGIN_SD, 0)

    def p_total(self, side: str, line: float) -> float:
        p_over = prob_above(self.total, TOTAL_SD, line)
        return p_over if side == "over" else 1 - p_over


def blend_ratings(season: dict | None, recent: dict | None) -> dict:
    if not season and not recent:
        return dict(LEAGUE_DEFAULT)
    if not season:
        return dict(recent)
    if not recent or recent.get("games", 0) < 3:
        return dict(season)
    return {k: (1 - RECENT_WEIGHT) * season[k] + RECENT_WEIGHT * recent[k] for k in ("off", "def", "pace")}


def early_season_blend(current: dict[str, dict], previous: dict[str, dict]) -> dict[str, dict]:
    """Con pocos partidos jugados, la temporada anterior pesa más (hasta 20 partidos)."""
    out = {}
    for team in set(current) | set(previous):
        cur, prev = current.get(team), previous.get(team)
        if not prev:
            out[team] = cur
            continue
        if not cur:
            out[team] = {**prev, "games": 0}
            continue
        w = min(cur.get("games", 0), 20) / 20
        out[team] = {k: w * cur[k] + (1 - w) * prev[k] for k in ("off", "def", "pace")}
        out[team]["games"] = cur.get("games", 0)
    return out


def league_average(ratings: dict[str, dict]) -> dict:
    if not ratings:
        return dict(LEAGUE_DEFAULT)
    n = len(ratings)
    return {k: sum(r[k] for r in ratings.values()) / n for k in ("off", "def", "pace")}


def project_game(home: dict, away: dict, league: dict, *, home_b2b: bool = False,
                 away_b2b: bool = False, home_injury_pts: float = 0.0,
                 away_injury_pts: float = 0.0) -> Projection:
    pace = home["pace"] * away["pace"] / league["pace"]
    home_pts = pace * home["off"] * (away["def"] / league["def"]) / 100 + HOME_ADVANTAGE / 2
    away_pts = pace * away["off"] * (home["def"] / league["def"]) / 100 - HOME_ADVANTAGE / 2
    notes = [f"Posesiones estimadas: {pace:.1f}"]
    if home_b2b:
        home_pts -= B2B_PENALTY
        notes.append("Local en back-to-back")
    if away_b2b:
        away_pts -= B2B_PENALTY
        notes.append("Visitante en back-to-back")
    if home_injury_pts:
        home_pts -= home_injury_pts
        notes.append(f"Bajas local: -{home_injury_pts:.1f} pts")
    if away_injury_pts:
        away_pts -= away_injury_pts
        notes.append(f"Bajas visitante: -{away_injury_pts:.1f} pts")
    return Projection(home_pts, away_pts, notes)


def injury_impact(out_players: list[dict]) -> float:
    """Puntos netos que pierde un equipo por sus bajas.

    Un sustituto recupera buena parte de la producción: contamos ~30% de los puntos
    del lesionado, más si es un jugador de muchos minutos. Tope de 8 puntos por equipo.
    """
    impact = 0.0
    for p in out_players:
        share = 0.3 + 0.1 * (p.get("min", 0) >= 30)
        impact += min(p.get("pts", 0) * share, 4.5)
    return min(impact, 8.0)
