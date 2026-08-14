"""Two things in one script:

  1. `change_event` — what humans and algorithms changed in the
     account over the last N days. Useful when investigating CPA
     spikes, sudden volume drops, or unexpected status changes.

  2. Local audit history — every `gads_audit.py` run can be persisted
     under ~/.claude/gads-audit-history/<customer>/<timestamp>.json.
     `--diff a b` compares two of those audits to see which findings
     were resolved, which are new, and which are unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import gads_client
import gads_utils

HISTORY_ROOT = Path.home() / ".claude" / "gads-audit-history"

CHANGE_QUERY = """
    SELECT
      change_event.resource_change_operation,
      change_event.resource_name,
      change_event.change_resource_type,
      change_event.user_email,
      change_event.client_type,
      change_event.change_date_time,
      change_event.campaign,
      change_event.ad_group,
      change_event.changed_fields
    FROM change_event
    WHERE change_event.change_date_time >= '{start} 00:00:00'
      AND change_event.change_date_time <= '{end} 23:59:59'
    ORDER BY change_event.change_date_time DESC
    LIMIT 500
"""


# ---------- change_event ----------

def changes(customer_id: str, days: int = 7) -> dict:
    start, end = gads_utils.date_range(days)
    query = CHANGE_QUERY.format(start=start, end=end)
    rows = gads_client.search_stream(customer_id, query)
    by_actor: dict[str, int] = {}
    by_resource: dict[str, int] = {}
    for row in rows:
        e = row.get("change_event", {})
        by_actor[e.get("user_email") or e.get("client_type") or "unknown"] = (
            by_actor.get(e.get("user_email") or e.get("client_type") or "unknown", 0) + 1
        )
        by_resource[e.get("change_resource_type", "?")] = (
            by_resource.get(e.get("change_resource_type", "?"), 0) + 1
        )
    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "total": len(rows),
        "by_actor": by_actor,
        "by_resource": by_resource,
        "events": rows,
    }


# ---------- audit history ----------

def save_audit(audit: dict) -> Path:
    cid = audit.get("customer_id") or "unknown"
    folder = HISTORY_ROOT / cid
    folder.mkdir(parents=True, exist_ok=True)

    # The format has microsecond precision but the clock behind it does not.
    # On Windows `datetime.now()` advances in ~1ms steps, so five back-to-back
    # calls return the same value and a second save clobbers the first. Wait
    # for the clock to actually move rather than inventing a suffix, so the
    # filename shape stays parseable by the --diff timestamp shortcut.
    for _ in range(200):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        out = folder / f"{ts}.json"
        if not out.exists():
            break
        time.sleep(0.002)
    else:
        raise RuntimeError(f"could not allocate a unique audit filename in {folder}")
    out.write_text(json.dumps(audit, indent=2, default=str))
    return out


def list_audits(customer_id: str) -> list[Path]:
    folder = HISTORY_ROOT / customer_id
    if not folder.exists():
        return []
    return sorted(folder.glob("*.json"))


def diff_audits(a: Path, b: Path) -> dict:
    """Compare two persisted audits by finding text + agent."""
    findings_a = _findings(json.loads(a.read_text()))
    findings_b = _findings(json.loads(b.read_text()))
    keys_a = {_key(f) for f in findings_a}
    keys_b = {_key(f) for f in findings_b}
    return {
        "a": str(a),
        "b": str(b),
        "resolved": [f for f in findings_a if _key(f) not in keys_b],
        "new": [f for f in findings_b if _key(f) not in keys_a],
        "unchanged": [f for f in findings_b if _key(f) in keys_a],
    }


def _findings(audit: dict) -> list[dict]:
    out: list[dict] = []
    for agent, agent_out in audit.get("agents", {}).items():
        for f in agent_out.get("findings", []) or []:
            out.append({"agent": agent, **f})
    return out


def _key(f: dict) -> tuple:
    return (f.get("agent"), f.get("code") or f.get("message", ""))


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", help="for --changes and --list")
    p.add_argument("--days", type=int, default=7, help="days of change history")
    p.add_argument("--changes", action="store_true", help="pull change_event log")
    p.add_argument("--list", action="store_true", help="list saved audits for the customer")
    p.add_argument("--diff", nargs=2, metavar=("A", "B"),
                   help="paths or timestamps of two saved audits to compare")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.changes:
        if not args.customer:
            p.error("--changes requires --customer")
        gads_utils.emit(changes(args.customer, args.days), args.json)
        return 0

    if args.list:
        if not args.customer:
            p.error("--list requires --customer")
        cid = gads_utils.normalize_customer_id(args.customer)
        paths = list_audits(cid)
        gads_utils.emit({"customer_id": cid, "audits": [str(p) for p in paths]}, args.json)
        return 0

    if args.diff:
        a, b = (_resolve_audit(args.diff[0], args.customer),
                _resolve_audit(args.diff[1], args.customer))
        gads_utils.emit(diff_audits(a, b), args.json)
        return 0

    p.print_help()
    return 0


def _resolve_audit(token: str, customer: str | None) -> Path:
    """A path wins over a timestamp shortcut."""
    p = Path(token)
    if p.exists():
        return p
    if customer:
        cid = gads_utils.normalize_customer_id(customer)
        candidate = HISTORY_ROOT / cid / f"{token}.json"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not resolve audit: {token}")


if __name__ == "__main__":
    sys.exit(main())
