"""Servidor web: API JSON + panel en el navegador."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import engine

app = FastAPI(title="NBA Bets", description="Análisis de apuestas NBA")
STATIC = Path(__file__).parent / "static"


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


@app.get("/api/analysis")
def analysis(day: str | None = Query(None, alias="date"), props: bool = False, tips: bool | None = None) -> dict:
    return engine.analyze_day(_parse_day(day), with_props=props, with_tips=tips)
