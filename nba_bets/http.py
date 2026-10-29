"""Cliente HTTP con caché en disco (para no gastar cuota de APIs ni saturar las webs)."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import requests

from .config import settings

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})


def _cache_path(key: str):
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return settings.cache_dir / (hashlib.sha1(key.encode()).hexdigest() + ".json")


def cache_get(key: str, ttl: float) -> Any | None:
    path = _cache_path(key)
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def cache_set(key: str, value: Any) -> None:
    try:
        _cache_path(key).write_text(json.dumps(value), encoding="utf-8")
    except (OSError, TypeError) as exc:
        log.debug("No se pudo cachear %s: %s", key, exc)


def get_json(url: str, params: dict | None = None, ttl: float = 300) -> Any | None:
    key = url + "?" + json.dumps(params or {}, sort_keys=True)
    cached = cache_get(key, ttl)
    if cached is not None:
        return cached
    try:
        resp = _session.get(url, params=params, timeout=settings.http_timeout)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Error al pedir %s: %s", url, exc)
        return None
    cache_set(key, data)
    return data


def get_text(url: str, ttl: float = 1800) -> str | None:
    cached = cache_get("text:" + url, ttl)
    if cached is not None:
        return cached
    try:
        resp = _session.get(url, timeout=settings.http_timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Error al pedir %s: %s", url, exc)
        return None
    cache_set("text:" + url, resp.text)
    return resp.text
