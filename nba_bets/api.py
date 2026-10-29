"""Servidor web: API JSON + panel en el navegador."""
from __future__ import annotations

import hmac
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from . import engine
from .config import settings
from .http import USER_AGENT

app = FastAPI(title="NBA Bets", description="Análisis de apuestas NBA")
STATIC = Path(__file__).parent / "static"
AUTH_COOKIE = "nba_bets_key"
PUBLIC_PATHS = {"/manifest.webmanifest", "/icon-180.png", "/icon-512.png", "/healthz"}

LOGIN_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>NBA Bets</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#e8eaed;
font:16px system-ui,sans-serif}form{display:flex;flex-direction:column;gap:10px;padding:16px;width:min(320px,100%)}
input,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #2a2e36;background:#181b21;color:inherit}
button{background:#ea580c;border-color:#ea580c;color:#fff}</style></head>
<body><form method="get" action="/"><b>NBA Bets</b>
<input name="key" type="password" placeholder="Contraseña" autofocus><button>Entrar</button></form></body></html>"""


def _key_ok(value: str | None) -> bool:
    return bool(value) and hmac.compare_digest(value, settings.app_password)


@app.middleware("http")
async def password_guard(request: Request, call_next):
    """Si APP_PASSWORD está definida, pide la contraseña una vez y la recuerda en una cookie."""
    if not settings.app_password or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if _key_ok(request.cookies.get(AUTH_COOKIE)):
        return await call_next(request)
    key = request.query_params.get("key")
    if _key_ok(key):
        response = await call_next(request)
        response.set_cookie(AUTH_COOKIE, key, max_age=365 * 24 * 3600, httponly=True,
                            samesite="lax", secure=request.url.scheme == "https")
        return response
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Contraseña requerida"}, status_code=401)
    return HTMLResponse(LOGIN_PAGE, status_code=401)


def _parse_day(value: str | None) -> date:
    if not value:
        # La NBA organiza el calendario en hora de la costa este de EE. UU.
        return datetime.now(ZoneInfo("America/New_York")).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "Fecha inválida, usa AAAA-MM-DD") from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    # Sin start_url: el icono de la pantalla de inicio abre la URL desde la que se añadió.
    return JSONResponse({
        "name": "NBA Bets",
        "short_name": "NBA Bets",
        "display": "standalone",
        "background_color": "#0f1115",
        "theme_color": "#0f1115",
        "icons": [{"src": "/icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }, media_type="application/manifest+json")


@app.get("/icon-{size}.png")
def icon(size: int) -> FileResponse:
    if size not in (180, 512):
        raise HTTPException(404)
    return FileResponse(STATIC / f"icon-{size}.png", media_type="image/png")


@app.get("/api/analysis")
def analysis(day: str | None = Query(None, alias="date"), props: bool = False, tips: bool | None = None) -> dict:
    return engine.analyze_day(_parse_day(day), with_props=props, with_tips=tips)


DIAG_TARGETS = {
    "ESPN partidos": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "ESPN clasificación": "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings",
    "stats.nba.com": "https://stats.nba.com/stats/scoreboardv2?GameDate=2025-01-15&LeagueID=00&DayOffset=0",
    "The Odds API": "https://api.the-odds-api.com/v4/sports",      # este endpoint no gasta cuota
    "sportsgambler": "https://www.sportsgambler.com/betting-tips/basketball/",
    "scores24": "https://scores24.live/en/basketball",
}


@app.get("/api/diagnostico")
def diagnostico() -> dict:
    """Prueba cada fuente desde el servidor (sin caché) y dice si responde y cuánto tarda."""
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.nba.com/", "Origin": "https://www.nba.com"}

    def probe(item):
        name, url = item
        params = {"apiKey": settings.odds_api_key} if name == "The Odds API" and settings.odds_api_key else None
        t0 = time.time()
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            result = {"ok": resp.ok, "http": resp.status_code}
            if name == "The Odds API":
                result["cuota_restante"] = resp.headers.get("x-requests-remaining")
                if not settings.odds_api_key:
                    result["nota"] = "sin ODDS_API_KEY configurada"
        except requests.RequestException as exc:
            result = {"ok": False, "error": type(exc).__name__}
        result["segundos"] = round(time.time() - t0, 1)
        return name, result

    with ThreadPoolExecutor(max_workers=len(DIAG_TARGETS)) as pool:
        return dict(pool.map(probe, DIAG_TARGETS.items()))
