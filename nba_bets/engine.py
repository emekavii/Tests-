"""Motor de recomendaciones: junta todas las fuentes, aplica los modelos y calcula el valor."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from .config import settings
from .model import odds as om
from .model import props_model, team_model
from .schemas import ExpertTip, Game, Injury, Price
from .sources import espn, nba_stats, odds_api, scrapers
from .teams import full_name, normalize

log = logging.getLogger(__name__)

TIP_BONUS = 0.015       # ajuste de probabilidad por cada web de tipsters que coincide
TIP_BONUS_CAP = 0.03
PROP_LABELS = {"points": "puntos", "rebounds": "rebotes", "assists": "asistencias",
               "threes": "triples", "pra": "puntos+reb+ast"}


# --------------------------------------------------------------------------- mercados

def _main_line(prices: list[Price], market: str) -> tuple[float | None, dict[str, list[Price]]]:
    """Elige la línea principal del mercado (la que ofrecen más casas)."""
    rows = [p for p in prices if p.market == market]
    if not rows:
        return None, {}
    if market == "moneyline":
        line = None
    else:
        # Normalizamos a la perspectiva del local / línea de total
        keyed = Counter(p.point if p.selection in ("home", "over", "under") else -p.point
                        for p in rows if p.point is not None)
        if not keyed:
            return None, {}
        line = keyed.most_common(1)[0][0]
    by_sel: dict[str, list[Price]] = defaultdict(list)
    for p in rows:
        if market == "spread":
            home_pt = p.point if p.selection == "home" else -p.point
            if home_pt != line:
                continue
        elif market == "total" and p.point != line:
            continue
        by_sel[p.selection].append(p)
    return line, by_sel


def _market_probs(by_sel: dict[str, list[Price]], a: str, b: str) -> dict[str, float] | None:
    """Probabilidad de mercado sin margen, promediando las casas que ofrecen ambos lados."""
    books_a = {p.book: p.odds for p in by_sel.get(a, [])}
    books_b = {p.book: p.odds for p in by_sel.get(b, [])}
    common = [bk for bk in books_a if bk in books_b]
    if not common:
        return None
    pa = sum(om.no_vig(books_a[bk], books_b[bk])[0] for bk in common) / len(common)
    return {a: pa, b: 1 - pa}


def _tip_adjust(tips: list[ExpertTip], market: str, selection: str, point: float | None) -> tuple[float, list[str]]:
    agree, against = set(), set()
    opposite = {"home": "away", "away": "home", "over": "under", "under": "over"}[selection]
    for t in tips:
        same_market = t.market == market or (market == "moneyline" and t.market == "spread")
        if not same_market:
            continue
        if t.selection == selection:
            agree.add(t.source)
        elif t.selection == opposite:
            against.add(t.source)
    adj = TIP_BONUS * (len(agree) - len(against))
    return max(-TIP_BONUS_CAP, min(TIP_BONUS_CAP, adj)), sorted(agree)


def _label(game: Game, market: str, selection: str, point: float | None) -> str:
    if market == "moneyline":
        return f"Gana {full_name(game.home if selection == 'home' else game.away)}"
    if market == "spread":
        team = full_name(game.home if selection == "home" else game.away)
        return f"{team} {point:+g} (hándicap)"
    return f"{'Más' if selection == 'over' else 'Menos'} de {point:g} puntos ({selection.capitalize()})"


def _confidence(ev: float, agree: list[str], model_edge: float) -> str:
    score = ev * 100 + 2 * len(agree) + (2 if model_edge > 0.06 else 0)
    if score >= 9:
        return "Alta"
    if score >= 5.5:
        return "Media"
    return "Baja"


def evaluate_markets(game: Game, proj: team_model.Projection, tips: list[ExpertTip]) -> list[dict]:
    w = settings.model_weight
    picks = []
    for market, (a, b) in (("moneyline", ("home", "away")), ("spread", ("home", "away")),
                           ("total", ("over", "under"))):
        line, by_sel = _main_line(game.prices, market)
        if not by_sel:
            continue
        market_p = _market_probs(by_sel, a, b)
        for sel in (a, b):
            if not by_sel.get(sel):
                continue
            best = max(by_sel[sel], key=lambda p: p.odds)
            if market == "moneyline":
                model_p = proj.p_home_win() if sel == "home" else 1 - proj.p_home_win()
            elif market == "spread":
                model_p = proj.p_cover(sel, best.point)
            else:
                model_p = proj.p_total(sel, best.point)
            mkt = market_p[sel] if market_p else None
            prob = model_p if mkt is None else w * model_p + (1 - w) * mkt
            adj, agree = _tip_adjust(tips, market, sel, best.point)
            prob = min(0.97, max(0.03, prob + adj))
            ev = om.expected_value(prob, best.odds)
            stake_pct = om.kelly(prob, best.odds, settings.kelly_fraction, settings.max_stake_pct)
            picks.append({
                "market": market,
                "selection": sel,
                "point": best.point,
                "label": _label(game, market, sel, best.point),
                "odds": round(best.odds, 3),
                "american": om.decimal_to_american(best.odds),
                "book": best.book,
                "model_prob": round(model_p, 4),
                "market_prob": round(mkt, 4) if mkt is not None else None,
                "prob": round(prob, 4),
                "fair_odds": round(1 / prob, 2),
                "ev": round(ev, 4),
                "stake_pct": round(stake_pct, 4),
                "stake": round(stake_pct * settings.bankroll, 2),
                "tips_agree": agree,
                "recommended": ev >= settings.min_edge and stake_pct > 0,
                "confidence": _confidence(ev, agree, model_p - (mkt or model_p)),
            })
    return picks


# --------------------------------------------------------------------------- props

def _find_player(stats: list[dict], name: str) -> dict | None:
    target = normalize(name)
    for p in stats:
        if normalize(p["name"]) == target:
            return p
    return None


def evaluate_props(game: Game, ratings: dict, league: dict, season_players: list[dict],
                   injuries: list[Injury], season: str) -> list[dict]:
    """Props con línea de casa (The Odds API) o, si no hay clave, proyecciones sin línea."""
    out_names = {normalize(i.player) for i in injuries if i.status.lower() == "out"}
    lines = odds_api.get_props(game.odds_event_id) if game.odds_event_id else []

    if lines:
        by_player: dict[str, list] = defaultdict(list)
        for l in lines:
            by_player[l.player].append(l)
        players = sorted(by_player, key=lambda n: -((_find_player(season_players, n) or {}).get("pts", 0)))
        candidates = [(n, by_player[n]) for n in players if normalize(n) not in out_names]
    else:
        roster = [p for p in season_players if p["team"] in (game.home, game.away)
                  and normalize(p["name"]) not in out_names and p["min"] >= 20]
        roster.sort(key=lambda p: -p["pts"])
        candidates = [(p["name"], [None]) for p in roster]
    candidates = candidates[: settings.max_prop_players]

    proj_pace = None
    if game.home in ratings and game.away in ratings:
        proj_pace = ratings[game.home]["pace"] * ratings[game.away]["pace"] / league["pace"]

    results = []
    prev_season = nba_stats.previous_season(season)
    for name, player_lines in candidates:
        info = _find_player(season_players, name)
        pid = info["id"] if info else nba_stats.player_id(name)
        if not pid:
            continue
        team = info["team"] if info else None
        opp = game.away if team == game.home else game.home if team == game.away else None
        opp_factor = ratings[opp]["def"] / league["def"] if opp in ratings else 1.0
        pace_factor = proj_pace / league["pace"] if proj_pace else 1.0
        current = nba_stats.player_game_log(pid, season)
        previous = nba_stats.player_game_log(pid, prev_season)

        if player_lines == [None]:
            projections = {}
            for market in ("points", "rebounds", "assists", "threes", "pra"):
                pr = props_model.project(current, previous, market,
                                         opp_def_factor=opp_factor, pace_factor=pace_factor)
                if pr:
                    projections[market] = round(pr.mean, 1)
            if projections:
                results.append({"player": name, "team": team, "projections": projections,
                                "line": None, "recommended": False})
            continue

        for l in player_lines:
            pr = props_model.project(current, previous, l.market, opp_def_factor=opp_factor,
                                     pace_factor=pace_factor, line=l.point)
            if not pr:
                continue
            p_over = pr.p_over(l.market, l.point)
            best = None
            for side, price, p_model in (("over", l.over_odds, p_over), ("under", l.under_odds, 1 - p_over)):
                if not price:
                    continue
                p = p_model
                if l.over_odds and l.under_odds:
                    mkt = om.no_vig(l.over_odds, l.under_odds)[0 if side == "over" else 1]
                    p = settings.model_weight * p_model + (1 - settings.model_weight) * mkt
                ev = om.expected_value(p, price)
                cand = (ev, side, price, p)
                if best is None or cand > best:
                    best = cand
            if best is None:
                continue
            ev, side, price, p = best
            stake_pct = om.kelly(p, price, settings.kelly_fraction, settings.max_stake_pct)
            results.append({
                "player": name, "team": team, "market": l.market,
                "label": f"{name} {'Más' if side == 'over' else 'Menos'} de {l.point:g} {PROP_LABELS[l.market]}",
                "side": side, "line": l.point, "odds": round(price, 3), "book": l.book,
                "projection": round(pr.mean, 1), "prob": round(p, 4), "ev": round(ev, 4),
                "hit_rate": pr.hit_rate, "stake": round(stake_pct * settings.bankroll, 2),
                "recommended": ev >= settings.min_edge and stake_pct > 0 and pr.games >= 5,
            })
    results.sort(key=lambda r: -(r.get("ev") or -1))
    return results


# --------------------------------------------------------------------------- día completo

def analyze_day(day: date, with_props: bool = False, with_tips: bool | None = None) -> dict:
    with_tips = settings.enable_scrapers if with_tips is None else with_tips
    season = nba_stats.season_for(day)
    status = {}

    games = espn.get_games(day)
    status["espn"] = bool(games)
    if odds_api.enabled():
        events = odds_api.fetch_odds()
        odds_api.attach_odds(games, events)
        status["odds_api"] = events is not None
    else:
        status["odds_api"] = "sin clave (usando cuotas de ESPN)"

    season_r = nba_stats.team_ratings(season)
    recent_r = nba_stats.team_ratings(season, last_n=10)
    if sum(r.get("games", 0) for r in season_r.values()) < 30 * 10:
        # Inicio de temporada: pocos partidos, mezclamos con la temporada anterior
        prev_r = nba_stats.team_ratings(nba_stats.previous_season(season))
        season_r = team_model.early_season_blend(season_r, prev_r)
    ratings = {t: team_model.blend_ratings(season_r.get(t), recent_r.get(t))
               for t in set(season_r) | set(recent_r)}
    league = team_model.league_average(ratings)
    status["nba_stats"] = bool(ratings)

    injuries = espn.get_injuries()
    status["injuries"] = bool(injuries)
    season_players = nba_stats.player_season_stats(season)
    if len(season_players) < 200:
        season_players = season_players + [p for p in nba_stats.player_season_stats(
            nba_stats.previous_season(season)) if not _find_player(season_players, p["name"])]
    b2b_teams = espn.teams_playing(day - timedelta(days=1))

    result_games, top = [], []
    tips_found = False
    for game in games:
        inj = [i for i in injuries if i.team in (game.home, game.away)]

        def out_impact(team: str) -> float:
            outs = [_find_player(season_players, i.player) for i in inj
                    if i.team == team and i.status.lower() == "out"]
            return team_model.injury_impact([p for p in outs if p])

        proj = team_model.project_game(
            ratings.get(game.home, team_model.LEAGUE_DEFAULT),
            ratings.get(game.away, team_model.LEAGUE_DEFAULT),
            league,
            home_b2b=game.home in b2b_teams, away_b2b=game.away in b2b_teams,
            home_injury_pts=out_impact(game.home), away_injury_pts=out_impact(game.away),
        )
        if not ratings:
            proj.notes.append("Sin datos de stats.nba.com: proyección basada solo en el mercado")

        tips = []
        if with_tips and game.status == "pre":
            try:
                tips = scrapers.tips_for_game(game)
            except Exception as exc:  # una web caída no debe tumbar el análisis
                log.warning("Scraper falló para %s-%s: %s", game.away, game.home, exc)
        tips_found = tips_found or bool(tips)

        markets = evaluate_markets(game, proj, tips) if ratings or game.prices else []
        if not ratings:
            for m in markets:  # sin modelo no hay ventaja real: no recomendamos nada
                m["recommended"] = False

        props = []
        if with_props and game.status == "pre":
            props = evaluate_props(game, ratings, league, season_players, injuries, season)

        recommended = sorted([m for m in markets if m["recommended"]], key=lambda m: -m["ev"])
        if game.status == "pre":
            for m in recommended:
                top.append({**m, "game": f"{game.away} @ {game.home}", "game_id": game.id})
            for p in props:
                if p.get("recommended"):
                    top.append({**p, "market": "prop", "game": f"{game.away} @ {game.home}",
                                "game_id": game.id, "confidence": "Media" if p["ev"] >= 0.06 else "Baja"})

        result_games.append({
            **game.to_dict(),
            "home_name": full_name(game.home),
            "away_name": full_name(game.away),
            "home_b2b": game.home in b2b_teams,
            "away_b2b": game.away in b2b_teams,
            "projection": {
                "home_pts": round(proj.home_pts, 1), "away_pts": round(proj.away_pts, 1),
                "total": round(proj.total, 1), "margin": round(proj.margin, 1),
                "p_home_win": round(proj.p_home_win(), 4), "notes": proj.notes,
            },
            "injuries": [asdict(i) for i in inj],
            "tips": [asdict(t) for t in tips],
            "markets": markets,
            "best_pick": recommended[0] if recommended else None,
            "props": props,
        })

    status["scrapers"] = tips_found if with_tips else "desactivado"
    top.sort(key=lambda m: -m["ev"])
    return {
        "date": day.isoformat(),
        "season": season,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "settings": {"bankroll": settings.bankroll, "min_edge": settings.min_edge,
                     "model_weight": settings.model_weight},
        "sources": status,
        "games": result_games,
        "top_picks": top,
    }
