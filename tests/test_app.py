import json
from datetime import date
from pathlib import Path

import pytest

from nba_bets import engine
from nba_bets.model import odds as om
from nba_bets.model import props_model, team_model
from nba_bets.schemas import Injury
from nba_bets.sources import espn, nba_stats, odds_api, scrapers
from nba_bets.teams import to_abbr

FIX = Path(__file__).parent / "fixtures"


def load(name):
    text = (FIX / name).read_text()
    return json.loads(text) if name.endswith(".json") else text


# ----------------------------------------------------------------- matemáticas

def test_odds_conversions():
    assert om.american_to_decimal(-110) == pytest.approx(1.909, abs=1e-3)
    assert om.american_to_decimal(150) == 2.5
    assert om.decimal_to_american(2.5) == 150
    assert om.decimal_to_american(1.5) == -200
    a, b = om.no_vig(1.91, 1.91)
    assert a == pytest.approx(0.5)
    assert om.expected_value(0.55, 2.0) == pytest.approx(0.10)
    assert om.kelly(0.55, 2.0, fraction=1, cap=1) == pytest.approx(0.10)
    assert om.kelly(0.40, 2.0) == 0


def test_poisson():
    # P(X > 2.5) con media 2.5 ~ 0.456
    assert om.poisson_prob_above(2.5, 2.5) == pytest.approx(0.4562, abs=1e-3)


def test_team_names():
    assert to_abbr("Los Angeles Clippers") == "LAC"
    assert to_abbr("LA Clippers") == "LAC"
    assert to_abbr("GS") == "GSW"
    assert to_abbr("Philadelphia 76ers") == "PHI"
    assert to_abbr("Trail Blazers") == "POR"


def test_projection_and_probabilities():
    league = team_model.LEAGUE_DEFAULT
    strong = {"off": 120, "def": 110, "pace": 99.5}
    weak = {"off": 110, "def": 118, "pace": 99.5}
    proj = team_model.project_game(strong, weak, league)
    assert proj.margin > 10
    assert proj.p_home_win() > 0.75
    # cubrir -5.5 es menos probable que ganar
    assert proj.p_cover("home", -5.5) < proj.p_home_win()
    assert proj.p_cover("home", -5.5) + proj.p_cover("away", 5.5) == pytest.approx(1)
    assert proj.p_total("over", 200) > 0.9
    tired = team_model.project_game(strong, weak, league, home_b2b=True, home_injury_pts=3)
    assert tired.margin == pytest.approx(proj.margin - 4.5)


def test_early_season_blend():
    cur = {"BOS": {"off": 130, "def": 100, "pace": 100, "games": 4}}
    prev = {"BOS": {"off": 120, "def": 110, "pace": 98, "games": 82},
            "NYK": {"off": 115, "def": 112, "pace": 97, "games": 82}}
    out = team_model.early_season_blend(cur, prev)
    assert out["BOS"]["off"] == pytest.approx(0.2 * 130 + 0.8 * 120)
    assert out["NYK"]["off"] == 115


def test_props_projection():
    log = [{"min": 35, "pts": p, "reb": 8, "ast": 5, "fg3m": 3} for p in (30, 28, 25, 32, 27, 26, 29)]
    pr = props_model.project(log, [], "points", line=27.5)
    assert 26 < pr.mean < 30
    assert pr.hit_rate == (4, 7)
    assert 0.3 < pr.p_over("points", 27.5) < 0.8
    pra = props_model.project(log, [], "pra")
    assert pra.mean == pytest.approx(pr.mean + 13, abs=1.5)
    assert props_model.project([], [], "points") is None


# ----------------------------------------------------------------- parsers

def test_espn_parser_both_formats():
    games = espn.parse_scoreboard(load("espn_scoreboard.json"))
    assert [(g.away, g.home) for g in games] == [("NYK", "BOS"), ("GSW", "LAL")]
    bos = {(p.market, p.selection): p for p in games[0].prices}
    assert bos[("spread", "home")].point == -5.5
    assert bos[("spread", "away")].point == 5.5
    assert bos[("moneyline", "away")].odds == pytest.approx(2.8)
    assert bos[("total", "over")].point == 221.5
    lal = {(p.market, p.selection): p for p in games[1].prices}
    assert lal[("spread", "home")].point == 2.0           # GS favorito por 2
    assert lal[("moneyline", "home")].odds == pytest.approx(2.1)
    assert lal[("total", "under")].point == 229.5


def test_espn_injuries():
    data = {"injuries": [{"displayName": "Boston Celtics", "injuries": [
        {"athlete": {"displayName": "Jrue Holiday"}, "status": "Out", "shortComment": "Knee"}]}]}
    inj = espn.parse_injuries(data)
    assert inj == [Injury("BOS", "Jrue Holiday", "Out", "Knee")]


def test_odds_api_attach_and_props():
    games = espn.parse_scoreboard(load("espn_scoreboard.json"))
    odds_api.attach_odds(games, load("odds_events.json"))
    assert games[0].odds_event_id == "evt1"
    assert all(p.book != "ESPN BET" for p in games[0].prices)
    props = {(p.player, p.market): p for p in odds_api.parse_props(load("odds_props.json"))}
    tatum = props[("Jayson Tatum", "points")]
    assert tatum.point == 27.5                    # línea principal, no la alternativa 32.5
    assert tatum.over_odds == 1.91 and tatum.under_odds == 1.95
    assert props[("Jalen Brunson", "threes")].point == 2.5


def test_scraper_extracts_tips():
    game = espn.parse_scoreboard(load("espn_scoreboard.json"))[0]
    links = scrapers.find_match_links(load("tips_listing.html"), "https://example.com/", game)
    assert links == ["https://example.com/betting-tips/basketball/new-york-knicks-vs-boston-celtics-prediction-29-10-2026/"]
    tips = scrapers.extract_tips(scrapers.page_text(load("tips_match.html")), game, "sportsgambler")
    found = {(t.market, t.selection, t.point) for t in tips}
    assert ("spread", "home", -5.5) in found
    assert ("total", "under", 221.5) in found
    assert ("moneyline", "home", None) in found
    assert not any(t.point == 300 for t in tips)


# ----------------------------------------------------------------- motor completo

@pytest.fixture
def offline(monkeypatch):
    ratings = {"BOS": {"off": 121, "def": 109, "pace": 98, "games": 40},
               "NYK": {"off": 116, "def": 113, "pace": 97, "games": 40},
               "LAL": {"off": 115, "def": 115, "pace": 100, "games": 40},
               "GSW": {"off": 116, "def": 113, "pace": 101, "games": 40}}
    monkeypatch.setattr(espn, "fetch_scoreboard", lambda day: load("espn_scoreboard.json") if day == date(2026, 10, 29) else {})
    monkeypatch.setattr(espn, "fetch_injuries_raw", lambda: {"injuries": []})
    monkeypatch.setattr(nba_stats, "team_ratings", lambda season, last_n=0: ratings)
    monkeypatch.setattr(nba_stats, "player_season_stats", lambda season: [
        {"id": 1, "name": "Jayson Tatum", "team": "BOS", "gp": 40, "min": 36, "pts": 27, "reb": 8, "ast": 5, "fg3m": 3},
        {"id": 2, "name": "Jalen Brunson", "team": "NYK", "gp": 40, "min": 35, "pts": 26, "reb": 3, "ast": 7, "fg3m": 2.6},
    ])
    monkeypatch.setattr(nba_stats, "player_game_log", lambda pid, season: [
        {"min": 35, "pts": 31 if pid == 1 else 24, "reb": 8, "ast": 6, "fg3m": 3}] * 10)
    monkeypatch.setattr(odds_api, "fetch_event_props", lambda event_id: load("odds_props.json"))
    monkeypatch.setattr(scrapers, "tips_for_game", lambda game: [])


def test_analyze_day_with_espn_odds(offline):
    data = engine.analyze_day(date(2026, 10, 29), with_props=True, with_tips=True)
    assert len(data["games"]) == 2
    g = data["games"][0]
    assert {m["market"] for m in g["markets"]} == {"moneyline", "spread", "total"}
    for m in g["markets"]:
        assert 0 < m["prob"] < 1
        assert m["ev"] == pytest.approx(m["prob"] * m["odds"] - 1, abs=1e-3)
    # sin clave de The Odds API: props son solo proyecciones
    assert g["props"] and g["props"][0]["line"] is None
    assert all(p["ev"] >= engine.settings.min_edge for p in data["top_picks"])


def test_analyze_day_with_odds_api(offline, monkeypatch):
    monkeypatch.setattr(odds_api, "enabled", lambda: True)
    monkeypatch.setattr(odds_api, "fetch_odds", lambda: load("odds_events.json"))
    data = engine.analyze_day(date(2026, 10, 29), with_props=True, with_tips=False)
    g = data["games"][0]
    spread = [m for m in g["markets"] if m["market"] == "spread"]
    assert {m["point"] for m in spread} == {-5.5, 5.5}      # línea mayoritaria
    assert max(m["odds"] for m in spread if m["selection"] == "away") == 1.95
    props = {p["player"]: p for p in g["props"]}
    assert props["Jayson Tatum"]["side"] == "over"            # promedia 31 vs línea 27.5
    assert props["Jayson Tatum"]["recommended"]


def test_api_endpoint(offline):
    from fastapi.testclient import TestClient

    from nba_bets.api import app

    client = TestClient(app)
    assert client.get("/").status_code == 200
    res = client.get("/api/analysis", params={"date": "2026-10-29", "tips": "false"})
    assert res.status_code == 200
    assert res.json()["date"] == "2026-10-29"
    assert client.get("/api/analysis", params={"date": "ayer"}).status_code == 400


def test_password_and_home_screen_assets(offline, monkeypatch):
    from fastapi.testclient import TestClient

    from nba_bets import api
    from nba_bets.config import Settings

    monkeypatch.setattr(api, "settings", Settings(app_password="secreto"))
    client = TestClient(api.app)
    # Icono y manifest accesibles sin contraseña (iOS los pide sin cookies)
    assert client.get("/icon-180.png").headers["content-type"] == "image/png"
    assert client.get("/manifest.webmanifest").json()["display"] == "standalone"
    assert client.get("/").status_code == 401
    assert client.get("/api/analysis").status_code == 401
    assert client.get("/?key=mala").status_code == 401
    assert client.get("/?key=secreto").status_code == 200       # guarda la cookie
    res = client.get("/api/analysis", params={"date": "2026-10-29", "tips": "false"})
    assert res.status_code == 200
