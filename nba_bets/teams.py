"""Equipos NBA y normalización de nombres entre fuentes (ESPN, The Odds API, nba_api, webs)."""
from __future__ import annotations

import re
import unicodedata

# abreviatura -> (nombre completo, apodo)
TEAMS: dict[str, tuple[str, str]] = {
    "ATL": ("Atlanta Hawks", "Hawks"),
    "BOS": ("Boston Celtics", "Celtics"),
    "BKN": ("Brooklyn Nets", "Nets"),
    "CHA": ("Charlotte Hornets", "Hornets"),
    "CHI": ("Chicago Bulls", "Bulls"),
    "CLE": ("Cleveland Cavaliers", "Cavaliers"),
    "DAL": ("Dallas Mavericks", "Mavericks"),
    "DEN": ("Denver Nuggets", "Nuggets"),
    "DET": ("Detroit Pistons", "Pistons"),
    "GSW": ("Golden State Warriors", "Warriors"),
    "HOU": ("Houston Rockets", "Rockets"),
    "IND": ("Indiana Pacers", "Pacers"),
    "LAC": ("LA Clippers", "Clippers"),
    "LAL": ("Los Angeles Lakers", "Lakers"),
    "MEM": ("Memphis Grizzlies", "Grizzlies"),
    "MIA": ("Miami Heat", "Heat"),
    "MIL": ("Milwaukee Bucks", "Bucks"),
    "MIN": ("Minnesota Timberwolves", "Timberwolves"),
    "NOP": ("New Orleans Pelicans", "Pelicans"),
    "NYK": ("New York Knicks", "Knicks"),
    "OKC": ("Oklahoma City Thunder", "Thunder"),
    "ORL": ("Orlando Magic", "Magic"),
    "PHI": ("Philadelphia 76ers", "76ers"),
    "PHX": ("Phoenix Suns", "Suns"),
    "POR": ("Portland Trail Blazers", "Trail Blazers"),
    "SAC": ("Sacramento Kings", "Kings"),
    "SAS": ("San Antonio Spurs", "Spurs"),
    "TOR": ("Toronto Raptors", "Raptors"),
    "UTA": ("Utah Jazz", "Jazz"),
    "WAS": ("Washington Wizards", "Wizards"),
}

# Abreviaturas alternativas que usan algunas fuentes (ESPN usa GS, NO, NY, SA, UTAH, WSH...)
_ABBR_ALIASES = {
    "GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA",
    "WSH": "WAS", "PHO": "PHX", "BRK": "BKN", "CHO": "CHA", "NJN": "BKN",
}

_NAME_ALIASES = {
    "los angeles clippers": "LAC",
    "la lakers": "LAL",
    "philadelphia sixers": "PHI",
    "sixers": "PHI",
    "blazers": "POR",
    "cavs": "CLE",
    "wolves": "MIN",
    "mavs": "DAL",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


_LOOKUP: dict[str, str] = {}
for _abbr, (_full, _nick) in TEAMS.items():
    _LOOKUP[normalize(_full)] = _abbr
    _LOOKUP[normalize(_nick)] = _abbr
    _LOOKUP[_abbr.lower()] = _abbr
for _alias, _abbr in _ABBR_ALIASES.items():
    _LOOKUP[_alias.lower()] = _abbr
for _alias, _abbr in _NAME_ALIASES.items():
    _LOOKUP[_alias] = _abbr


def to_abbr(name_or_abbr: str | None) -> str | None:
    """Devuelve la abreviatura canónica de un equipo a partir de cualquier nombre conocido."""
    if not name_or_abbr:
        return None
    key = normalize(name_or_abbr)
    if key in _LOOKUP:
        return _LOOKUP[key]
    # "Boston Celtics Basketball", "Celtics (BOS)", etc.
    for abbr, (_full, nick) in TEAMS.items():
        if normalize(nick) in key.split() or normalize(nick) in key:
            return abbr
    return None


def full_name(abbr: str) -> str:
    return TEAMS[abbr][0]


def nickname(abbr: str) -> str:
    return TEAMS[abbr][1]
