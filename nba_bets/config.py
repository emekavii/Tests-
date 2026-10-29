"""Configuración leída de variables de entorno (o de un fichero .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    odds_api_key: str = os.environ.get("ODDS_API_KEY", "")
    odds_regions: str = os.environ.get("ODDS_REGIONS", "eu")
    bankroll: float = _float("BANKROLL", 100)
    kelly_fraction: float = _float("KELLY_FRACTION", 0.25)
    max_stake_pct: float = _float("MAX_STAKE_PCT", 0.03)
    min_edge: float = _float("MIN_EDGE", 0.03)
    model_weight: float = _float("MODEL_WEIGHT", 0.5)
    enable_scrapers: bool = os.environ.get("ENABLE_SCRAPERS", "1") == "1"
    max_prop_players: int = int(_float("MAX_PROP_PLAYERS", 8))
    cache_dir: Path = Path(os.environ.get("CACHE_DIR", ".cache"))
    http_timeout: float = _float("HTTP_TIMEOUT", 15)


settings = Settings()
