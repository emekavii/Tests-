"""API oficial de estadísticas de la NBA (stats.nba.com) vía `nba_api`.

Da ratings ofensivos/defensivos, ritmo (pace) de los equipos y los game logs de jugadores.
stats.nba.com a veces bloquea IPs de servidores en la nube; en local suele ir bien.
"""
from __future__ import annotations

import logging
import time
from datetime import date

from .. import http
from ..teams import to_abbr

log = logging.getLogger(__name__)

_last_call = 0.0
_down_until = 0.0
TIMEOUT = 10          # segundos; desde servidores en la nube stats.nba.com suele colgarse
DOWN_PAUSE = 15 * 60  # si falla, no lo volvemos a intentar en 15 minutos


def available() -> bool:
    return time.time() >= _down_until


def _mark_down(exc: Exception) -> None:
    global _down_until
    _down_until = time.time() + DOWN_PAUSE
    log.warning("stats.nba.com no responde (%s); se usarán datos de ESPN durante 15 min", exc)


def _throttle() -> None:
    """stats.nba.com limita peticiones rápidas: dejamos ~0.7 s entre llamadas."""
    global _last_call
    wait = 0.7 - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def season_for(day: date) -> str:
    start = day.year if day.month >= 9 else day.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def previous_season(season: str) -> str:
    start = int(season[:4]) - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _frame_records(endpoint) -> list[dict]:
    return endpoint.get_data_frames()[0].to_dict("records")


def team_ratings(season: str, last_n: int = 0) -> dict[str, dict]:
    """{abbr: {off, def, pace, games}} con ratings avanzados."""
    key = f"nba:team_ratings:{season}:{last_n}"
    cached = http.cache_get(key, ttl=6 * 3600)
    if cached is not None:
        return cached
    if not available():
        return {}
    try:
        from nba_api.stats.endpoints import leaguedashteamstats

        _throttle()
        rows = _frame_records(leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
            last_n_games=last_n,
            timeout=TIMEOUT,
        ))
    except Exception as exc:  # nba_api lanza excepciones muy variadas (timeouts, JSON vacío...)
        _mark_down(exc)
        return {}
    out = {}
    for r in rows:
        abbr = to_abbr(r.get("TEAM_NAME", ""))
        if abbr:
            out[abbr] = {"off": r["OFF_RATING"], "def": r["DEF_RATING"],
                         "pace": r["PACE"], "games": r.get("GP", 0)}
    http.cache_set(key, out)
    return out


def player_season_stats(season: str) -> list[dict]:
    """Promedios de todos los jugadores (para lesiones y para elegir jugadores de props)."""
    key = f"nba:players:{season}"
    cached = http.cache_get(key, ttl=6 * 3600)
    if cached is not None:
        return cached
    if not available():
        return []
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats

        _throttle()
        rows = _frame_records(leaguedashplayerstats.LeagueDashPlayerStats(
            season=season, per_mode_detailed="PerGame", timeout=TIMEOUT))
    except Exception as exc:
        _mark_down(exc)
        return []
    out = [{
        "id": r["PLAYER_ID"], "name": r["PLAYER_NAME"], "team": to_abbr(r.get("TEAM_ABBREVIATION", "")),
        "gp": r["GP"], "min": r["MIN"], "pts": r["PTS"], "reb": r["REB"], "ast": r["AST"],
        "fg3m": r["FG3M"],
    } for r in rows]
    http.cache_set(key, out)
    return out


def player_id(name: str) -> int | None:
    from nba_api.stats.static import players

    from ..teams import normalize

    target = normalize(name)
    for p in players.get_players():
        if normalize(p["full_name"]) == target:
            return p["id"]
    # "Jr." / "III" y similares
    stripped = target.replace(" jr", "").replace(" iii", "").replace(" ii", "")
    for p in players.get_players():
        if normalize(p["full_name"]).replace(" jr", "").replace(" iii", "").replace(" ii", "") == stripped:
            return p["id"]
    return None


def player_game_log(pid: int, season: str) -> list[dict]:
    """Partidos del jugador (más reciente primero) con PTS, REB, AST, FG3M, MIN."""
    key = f"nba:gamelog:{pid}:{season}"
    cached = http.cache_get(key, ttl=3 * 3600)
    if cached is not None:
        return cached
    if not available():
        return []
    try:
        from nba_api.stats.endpoints import playergamelog

        _throttle()
        rows = _frame_records(playergamelog.PlayerGameLog(player_id=pid, season=season, timeout=TIMEOUT))
    except Exception as exc:
        _mark_down(exc)
        return []
    out = [{"date": r["GAME_DATE"], "matchup": r["MATCHUP"], "min": r["MIN"], "pts": r["PTS"],
            "reb": r["REB"], "ast": r["AST"], "fg3m": r["FG3M"]} for r in rows]
    http.cache_set(key, out)
    return out
