"""ESPN (API pública sin clave): calendario, marcadores, cuotas de referencia y lesiones."""
from __future__ import annotations

import logging
import re
from datetime import date

from .. import http
from ..model.odds import american_to_decimal
from ..schemas import Game, Injury, Price
from ..teams import to_abbr

log = logging.getLogger(__name__)

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
DEFAULT_JUICE = american_to_decimal(-110)


def fetch_scoreboard(day: date) -> dict | None:
    return http.get_json(f"{BASE}/scoreboard", {"dates": day.strftime("%Y%m%d")}, ttl=120)


def fetch_injuries_raw() -> dict | None:
    return http.get_json(f"{BASE}/injuries", ttl=900)


def _to_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in ("even", "ev", "pk", "pick"):
        return 100.0
    text = text.lstrip("ou")
    try:
        return float(text)
    except ValueError:
        return None


def _dec(american) -> float | None:
    val = _to_float(american)
    if val is None or val == 0:
        return None
    return american_to_decimal(val)


def parse_odds(odds: dict, home: str, away: str) -> list[Price]:
    """Convierte el bloque `odds` de ESPN en precios. Soporta el formato antiguo y el nuevo."""
    book = (odds.get("provider") or {}).get("name", "ESPN BET")
    prices: list[Price] = []

    # Moneyline
    home_ml = (odds.get("homeTeamOdds") or {}).get("moneyLine")
    away_ml = (odds.get("awayTeamOdds") or {}).get("moneyLine")
    ml = odds.get("moneyline") or {}
    if home_ml is None and ml:
        home_ml = ((ml.get("home") or {}).get("close") or {}).get("odds")
        away_ml = ((ml.get("away") or {}).get("close") or {}).get("odds")
    if _dec(home_ml) and _dec(away_ml):
        prices.append(Price("moneyline", "home", _dec(home_ml), None, book))
        prices.append(Price("moneyline", "away", _dec(away_ml), None, book))

    # Hándicap (spread) desde la perspectiva del local
    home_line = None
    details = odds.get("details") or ""
    m = re.match(r"^\s*([A-Za-z]+)\s+([+-]?\d+(?:\.\d+)?)", details)
    if m:
        fav = to_abbr(m.group(1))
        line = float(m.group(2))
        if fav == home:
            home_line = line
        elif fav == away:
            home_line = -line
    elif details.strip().upper() in ("EVEN", "PK"):
        home_line = 0.0
    if home_line is None and odds.get("spread") is not None:
        home_line = _to_float(odds.get("spread"))
    if home_line is not None:
        ps = odds.get("pointSpread") or {}
        h_odds = _dec(((ps.get("home") or {}).get("close") or {}).get("odds")) or _dec(
            (odds.get("homeTeamOdds") or {}).get("spreadOdds")) or DEFAULT_JUICE
        a_odds = _dec(((ps.get("away") or {}).get("close") or {}).get("odds")) or _dec(
            (odds.get("awayTeamOdds") or {}).get("spreadOdds")) or DEFAULT_JUICE
        prices.append(Price("spread", "home", h_odds, home_line, book))
        prices.append(Price("spread", "away", a_odds, -home_line, book))

    # Total (over/under)
    total = _to_float(odds.get("overUnder"))
    tot = odds.get("total") or {}
    if total is None and tot:
        total = _to_float(((tot.get("over") or {}).get("close") or {}).get("line"))
    if total:
        o_odds = _dec(odds.get("overOdds")) or _dec(
            ((tot.get("over") or {}).get("close") or {}).get("odds")) or DEFAULT_JUICE
        u_odds = _dec(odds.get("underOdds")) or _dec(
            ((tot.get("under") or {}).get("close") or {}).get("odds")) or DEFAULT_JUICE
        prices.append(Price("total", "over", o_odds, total, book))
        prices.append(Price("total", "under", u_odds, total, book))
    return prices


def parse_scoreboard(data: dict) -> list[Game]:
    games: list[Game] = []
    for event in (data or {}).get("events", []):
        try:
            comp = event["competitions"][0]
            teams = {c["homeAway"]: c for c in comp["competitors"]}
            home_c, away_c = teams["home"], teams["away"]
            home = to_abbr(home_c["team"]["abbreviation"]) or to_abbr(home_c["team"]["displayName"])
            away = to_abbr(away_c["team"]["abbreviation"]) or to_abbr(away_c["team"]["displayName"])
            if not home or not away:
                continue

            def record(c):
                recs = c.get("records") or []
                return recs[0].get("summary", "") if recs else ""

            def score(c):
                try:
                    return int(c.get("score"))
                except (TypeError, ValueError):
                    return None

            game = Game(
                id=str(event["id"]),
                start=event.get("date", ""),
                home=home,
                away=away,
                status=((event.get("status") or {}).get("type") or {}).get("state", "pre"),
                home_record=record(home_c),
                away_record=record(away_c),
                home_score=score(home_c),
                away_score=score(away_c),
            )
            for odds in comp.get("odds") or []:
                game.prices.extend(parse_odds(odds, home, away))
            games.append(game)
        except (KeyError, IndexError, TypeError) as exc:
            log.debug("Evento ESPN ignorado: %s", exc)
    return games


def get_games(day: date) -> list[Game]:
    return parse_scoreboard(fetch_scoreboard(day) or {})


def teams_playing(day: date) -> set[str]:
    """Equipos que jugaron un día (para detectar back-to-backs)."""
    out: set[str] = set()
    for g in get_games(day):
        out.update((g.home, g.away))
    return out


def parse_injuries(data: dict) -> list[Injury]:
    injuries: list[Injury] = []
    for team_block in (data or {}).get("injuries", []):
        team = to_abbr(team_block.get("displayName") or "") or to_abbr(
            ((team_block.get("team") or {}).get("abbreviation")) or "")
        for item in team_block.get("injuries", []):
            athlete = item.get("athlete") or {}
            team_i = team or to_abbr(((athlete.get("team") or {}).get("abbreviation")) or "")
            if not team_i:
                continue
            injuries.append(Injury(
                team=team_i,
                player=athlete.get("displayName", "?"),
                status=item.get("status", ""),
                detail=item.get("shortComment") or item.get("longComment") or "",
            ))
    return injuries


def get_injuries() -> list[Injury]:
    return parse_injuries(fetch_injuries_raw() or {})
