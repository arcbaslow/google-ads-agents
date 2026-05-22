"""Shared helpers: date ranges, formatting, cache, and a small terminal
table renderer used by the pretty-print fallback in emit()."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable

CACHE_DIR = Path.home() / ".claude" / "gads-cache"
CACHE_TTL_SECONDS = 15 * 60


# ---------- dates and money ----------

def date_range(days: int) -> tuple[str, str]:
    """Return ('YYYY-MM-DD', 'YYYY-MM-DD') for the last N days, inclusive of yesterday."""
    from datetime import date, timedelta

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def micros_to_currency(micros: int | str | None) -> float:
    if micros is None:
        return 0.0
    return int(micros) / 1_000_000


def normalize_customer_id(cid: str) -> str:
    return cid.replace("-", "").strip()


# ---------- cache ----------

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


# ---------- table renderer ----------

def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.2f}" if abs(value) < 1000 else f"{value:,.0f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def table(rows: list[dict], columns: list[str] | None = None, max_width: int = 40) -> str:
    """Compact ASCII table. Truncates long cells. Empty input returns "(no rows)"."""
    if not rows:
        return "(no rows)"
    if columns is None:
        columns = list({k for r in rows for k in r.keys()})

    string_rows: list[list[str]] = []
    for r in rows:
        string_rows.append([_truncate(_stringify(r.get(c, "")), max_width) for c in columns])

    widths = [max(len(c), *(len(row[i]) for row in string_rows)) for i, c in enumerate(columns)]

    sep = "  "
    out = [sep.join(c.ljust(widths[i]) for i, c in enumerate(columns))]
    out.append(sep.join("-" * widths[i] for i in range(len(columns))))
    for row in string_rows:
        out.append(sep.join(row[i].ljust(widths[i]) for i in range(len(columns))))
    return "\n".join(out)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------- emit (JSON or compact pretty-print) ----------

# Known list-valued payload keys, in priority order. The first that
# matches is rendered as a table.
_LIST_KEYS = (
    "campaigns", "candidates", "anomalies", "events", "ideas",
    "search_terms", "conversion_actions", "asset_groups", "app_campaigns",
    "audits", "placements", "rows", "results", "data",
)


def emit(data: Any, as_json: bool, stream=None) -> None:
    stream = stream or sys.stdout
    if as_json:
        stream.write(json.dumps(data, indent=2, default=str) + "\n")
        return
    stream.write(_pretty(data) + "\n")


def _pretty(data: Any) -> str:
    if not isinstance(data, dict):
        return _stringify(data)

    lines: list[str] = []

    # Header — pull the top-level identifiers
    header_bits = []
    for k in ("customer_id", "active", "status", "action"):
        if data.get(k) is not None:
            header_bits.append(f"{k}={data[k]}")
    dr = data.get("date_range") or {}
    if dr.get("start") and dr.get("end"):
        header_bits.append(f"window={dr['start']}..{dr['end']}")
    if header_bits:
        lines.append(" ".join(header_bits))

    if data.get("summary"):
        lines.append("")
        lines.append(_stringify(data["summary"]))

    # Multi-agent audit shape
    if isinstance(data.get("agents"), dict):
        lines.append("")
        lines.append("agents:")
        for name, out in data["agents"].items():
            if not isinstance(out, dict):
                continue
            status = out.get("status", "ok")
            s = out.get("summary") or out.get("error") or status
            lines.append(f"  {name:24s} {status:7s} {_stringify(s)}")

    # Findings group
    findings = data.get("findings") or []
    if findings:
        lines.append("")
        lines.append("findings:")
        for f in findings:
            sev = f.get("severity", "?")
            msg = f.get("message", "")
            lines.append(f"  [{sev:8s}] {msg}")

    # First list-valued key becomes a table
    for key in _LIST_KEYS:
        rows = data.get(key)
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            lines.append("")
            lines.append(f"{key}:")
            cols = _columns_for(key, rows[0])
            lines.append(table(rows, cols))
            break

    # Grouped dict-of-lists (placement scanner, recommendations)
    for key in ("to_exclude", "by_type", "by_category"):
        grouped = data.get(key)
        if isinstance(grouped, dict) and grouped:
            lines.append("")
            lines.append(f"{key}:")
            for cat, items in grouped.items():
                count = len(items) if isinstance(items, list) else 0
                lines.append(f"  {cat:20s} {count}")
            break

    if not lines:
        # Nothing matched a known shape — fall back to compact JSON.
        return json.dumps(data, indent=2, default=str)

    return "\n".join(lines)


def _columns_for(key: str, sample: dict) -> list[str]:
    """A few hand-picked column orderings for the common shapes."""
    presets = {
        "candidates": ["search_term", "cost", "clicks", "conversions"],
        "anomalies": ["date", "campaign_name", "metric", "value", "baseline_mean", "z_score"],
        "events": ["change_date_time", "user_email", "change_resource_type", "resource_change_operation"],
        "ideas": ["text", "avg_monthly_searches", "competition", "low_top_of_page_bid", "high_top_of_page_bid"],
    }
    if key in presets:
        return [c for c in presets[key] if c in _flatten_keys(sample)]
    # default: top-level keys, skip nested dicts
    return [k for k, v in sample.items() if not isinstance(v, (dict, list))][:6]


def _flatten_keys(sample: dict) -> set[str]:
    out: set[str] = set()
    for k, v in sample.items():
        out.add(k)
        if isinstance(v, dict):
            for kk in v:
                out.add(kk)
    return out
