"""The Odds API (https://the-odds-api.com): cuotas de muchas casas y player props."""
from __future__ import annotations

import logging
from collections import defaultdict

from .. import http
from ..config import settings
from ..schemas import Game, Price, PropLine
from ..teams import to_abbr

log = logging.getLogger(__name__)

BASE = "https://api.the-odds-api.com/v4/sports/basketball_nba"

PROP_MARKETS = {
    "player_points": "points",
    "player_rebounds": "rebounds",
    "player_assists": "assists",
    "player_threes": "threes",
    "player_points_rebounds_assists": "pra",
}


def enabled() -> bool:
    return bool(settings.odds_api_key)


def fetch_odds() -> list | None:
    if not enabled():
        return None
    return http.get_json(f"{BASE}/odds", {
        "apiKey": settings.odds_api_key,
        "regions": settings.odds_regions,
        "markets": "h2h,spreads,totals",
        "oddsFormat": "decimal",
    }, ttl=600)


def fetch_event_props(event_id: str) -> dict | None:
    if not enabled():
        return None
    return http.get_json(f"{BASE}/events/{event_id}/odds", {
        "apiKey": settings.odds_api_key,
        "regions": settings.odds_regions + ",us",
        "markets": ",".join(PROP_MARKETS),
        "oddsFormat": "decimal",
    }, ttl=900)


def parse_event_prices(event: dict) -> list[Price]:
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    prices: list[Price] = []
    for book in event.get("bookmakers", []):
        title = book.get("title", book.get("key", ""))
        for market in book.get("markets", []):
            key = market.get("key")
            for o in market.get("outcomes", []):
                name, price, point = o.get("name"), o.get("price"), o.get("point")
                if not price:
                    continue
                if key in ("h2h", "spreads"):
                    sel = "home" if name == home else "away" if name == away else None
                    if sel is None:
                        continue
                    prices.append(Price("moneyline" if key == "h2h" else "spread",
                                        sel, float(price), point, title))
                elif key == "totals":
                    prices.append(Price("total", str(name).lower(), float(price), point, title))
    return prices


def attach_odds(games: list[Game], events: list | None) -> None:
    """Sustituye las cuotas de ESPN por las de The Odds API cuando hay partido coincidente."""
    if not events:
        return
    by_teams = {(to_abbr(e.get("home_team")), to_abbr(e.get("away_team"))): e for e in events}
    for game in games:
        event = by_teams.get((game.home, game.away))
        if not event:
            continue
        prices = parse_event_prices(event)
        if prices:
            game.prices = prices
        game.odds_event_id = event.get("id")


def parse_props(data: dict) -> list[PropLine]:
    """Agrupa los props por (jugador, mercado, línea) y se queda con la mejor cuota over/under."""
    best: dict[tuple, dict] = defaultdict(lambda: {"over": None, "under": None, "book_o": "", "book_u": ""})
    for book in (data or {}).get("bookmakers", []):
        title = book.get("title", book.get("key", ""))
        for market in book.get("markets", []):
            mkey = PROP_MARKETS.get(market.get("key"))
            if not mkey:
                continue
            for o in market.get("outcomes", []):
                player, point, price = o.get("description"), o.get("point"), o.get("price")
                side = str(o.get("name", "")).lower()
                if not player or point is None or not price or side not in ("over", "under"):
                    continue
                entry = best[(player, mkey, float(point))]
                if entry[side] is None or price > entry[side]:
                    entry[side] = float(price)
                    entry["book_o" if side == "over" else "book_u"] = title
    lines = []
    for (player, mkey, point), e in best.items():
        lines.append(PropLine(player, mkey, point, e["over"], e["under"],
                              e["book_o"] or e["book_u"]))
    return _main_lines(lines)


def _main_lines(lines: list[PropLine]) -> list[PropLine]:
    """Si una casa ofrece varias líneas alternativas, nos quedamos con la más equilibrada."""
    grouped: dict[tuple, list[PropLine]] = defaultdict(list)
    for line in lines:
        grouped[(line.player, line.market)].append(line)
    out = []
    for group in grouped.values():
        both = [l for l in group if l.over_odds and l.under_odds]
        pool = both or group
        out.append(min(pool, key=lambda l: abs((l.over_odds or 2) - (l.under_odds or 2))))
    return out


def get_props(event_id: str) -> list[PropLine]:
    return parse_props(fetch_event_props(event_id) or {})
