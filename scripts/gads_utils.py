"""Shared helpers: date ranges, formatting, cache."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".claude" / "gads-cache"
CACHE_TTL_SECONDS = 15 * 60


def date_range(days: int) -> tuple[str, str]:
    """Return ('YYYY-MM-DD', 'YYYY-MM-DD') for the last N days, inclusive of yesterday."""
    from datetime import date, timedelta

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _key(parts: list[str]) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def cache_get(parts: list[str]) -> Any | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{_key(parts)}.json"
    if not f.exists():
        return None
    if time.time() - f.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return None


def cache_set(parts: list[str], data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / f"{_key(parts)}.json"
    f.write_text(json.dumps(data, indent=2, default=str))


def micros_to_currency(micros: int | str | None) -> float:
    if micros is None:
        return 0.0
    return int(micros) / 1_000_000


def emit(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return
    # human-readable fallback
    print(json.dumps(data, indent=2, default=str))


def normalize_customer_id(cid: str) -> str:
    return cid.replace("-", "").strip()
