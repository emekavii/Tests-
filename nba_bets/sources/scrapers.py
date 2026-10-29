"""Pronósticos de webs de tipsters: sportsgambler.com y scores24.live.

Es scraping "best effort": las webs cambian su HTML a menudo, así que en vez de depender de
clases CSS concretas buscamos los enlaces de cada partido por los nombres de los equipos y
extraemos del texto de la página frases típicas de pronóstico ("Over 221.5", "Celtics -5.5",
"Celtics to win"...). Se respeta robots.txt y todo se cachea 30 minutos.
Revisa los términos de uso de cada web antes de usarlo.
"""
from __future__ import annotations

import logging
import re
from urllib import robotparser
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .. import http
from ..schemas import ExpertTip, Game
from ..teams import full_name, nickname, normalize

log = logging.getLogger(__name__)

SOURCES = {
    "sportsgambler": [
        "https://www.sportsgambler.com/betting-tips/basketball/",
        "https://www.sportsgambler.com/betting-tips/basketball/nba/",
    ],
    "scores24": [
        "https://scores24.live/en/basketball/predictions",
        "https://scores24.live/en/basketball/l-usa-nba/predictions",
        "https://scores24.live/en/basketball",
    ],
}

TIP_KEYWORDS = re.compile(
    r"(prediction|our tip|tip:|betting tip|best bet|our pick|pick:|we predict|recommend)", re.I)

_robots: dict[str, robotparser.RobotFileParser | None] = {}


def allowed(url: str) -> bool:
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    if host not in _robots:
        text = http.get_text(host + "/robots.txt", ttl=24 * 3600)
        if text is None:
            _robots[host] = None
        else:
            rp = robotparser.RobotFileParser()
            rp.parse(text.splitlines())
            _robots[host] = rp
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(http.USER_AGENT, url)


def _slug_words(abbr: str) -> list[str]:
    return [normalize(full_name(abbr)).replace(" ", "-"), normalize(nickname(abbr)).replace(" ", "-")]


def find_match_links(html: str, base_url: str, game: Game) -> list[str]:
    """Enlaces de la página cuyo href/texto menciona a ambos equipos."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        text = normalize(a.get_text(" "))
        hay = href + " " + text.replace(" ", "-")
        if any(w in hay for w in _slug_words(game.home)) and any(w in hay for w in _slug_words(game.away)):
            url = urljoin(base_url, a["href"])
            if url not in links:
                links.append(url)
    return links


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" "))


def extract_tips(text: str, game: Game, source: str) -> list[ExpertTip]:
    """Busca pronósticos en ventanas de texto que siguen a palabras como 'Prediction' o 'Tip'."""
    windows = [text[m.start(): m.start() + 350] for m in TIP_KEYWORDS.finditer(text)]
    names = {
        "home": [nickname(game.home), full_name(game.home)],
        "away": [nickname(game.away), full_name(game.away)],
    }
    tips: list[ExpertTip] = []
    seen: set[tuple] = set()

    def add(tip: ExpertTip) -> None:
        key = (tip.market, tip.selection, tip.point)
        if key not in seen:
            seen.add(key)
            tips.append(tip)

    for win in windows:
        for m in re.finditer(r"\b(over|under)\s*(\d{3}(?:\.\d)?)\b", win, re.I):
            point = float(m.group(2))
            if 170 <= point <= 280:
                add(ExpertTip(source, "total", m.group(1).lower(), point, win[:200]))
        for side, team_names in names.items():
            alt = "|".join(re.escape(n) for n in team_names)
            for m in re.finditer(rf"(?:{alt})\s*\(?\s*([+-]\d{{1,2}}(?:\.5)?)\)?(?!\d)", win, re.I):
                add(ExpertTip(source, "spread", side, float(m.group(1)), win[:200]))
            if re.search(rf"(?:{alt})\s+(?:to\s+win|win\b|will\s+win|moneyline|ML\b)", win, re.I) or \
                    re.search(rf"(?:winner|victory)\s*[:\-]?\s*(?:the\s+)?(?:{alt})", win, re.I):
                add(ExpertTip(source, "moneyline", side, None, win[:200]))
    return tips


def tips_for_game(game: Game) -> list[ExpertTip]:
    tips: list[ExpertTip] = []
    for source, listing_urls in SOURCES.items():
        for listing in listing_urls:
            if not allowed(listing):
                continue
            html = http.get_text(listing)
            if not html:
                continue
            links = find_match_links(html, listing, game)
            for link in links[:2]:
                if not allowed(link):
                    continue
                match_html = http.get_text(link)
                if match_html:
                    found = extract_tips(page_text(match_html), game, source)
                    if found:
                        tips.extend(found)
                        break
            if any(t.source == source for t in tips):
                break
    return tips
