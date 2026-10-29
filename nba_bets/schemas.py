"""Estructuras de datos compartidas."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Price:
    market: str          # "moneyline" | "spread" | "total"
    selection: str       # "home" | "away" | "over" | "under"
    odds: float          # cuota decimal
    point: float | None = None   # hándicap (perspectiva de la selección) o línea de puntos
    book: str = ""


@dataclass
class Injury:
    team: str
    player: str
    status: str          # Out, Day-To-Day, Questionable...
    detail: str = ""


@dataclass
class ExpertTip:
    source: str          # sportsgambler / scores24
    market: str          # moneyline | spread | total
    selection: str       # home | away | over | under
    point: float | None = None
    text: str = ""


@dataclass
class Game:
    id: str
    start: str           # ISO 8601
    home: str            # abreviatura
    away: str
    status: str = "pre"
    home_record: str = ""
    away_record: str = ""
    home_score: int | None = None
    away_score: int | None = None
    prices: list[Price] = field(default_factory=list)
    odds_event_id: str | None = None   # id de The Odds API (para pedir props)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PropLine:
    player: str
    market: str          # points | rebounds | assists | threes | pra
    point: float
    over_odds: float | None
    under_odds: float | None
    book: str = ""
