"""Concrete entry point for /gads audit.

Runs every read-path agent in parallel against the same customer, merges
results into one document with the standard `summary / findings /
metrics` shape per agent, and (optionally) persists the merged document
under ~/.claude/gads-audit-history/<customer>/<timestamp>.json so later
runs can be diffed against it.

Subagent layers in Claude Code still wrap this for narrative analysis;
outside Claude Code this is the one-command driver.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import traceback
from typing import Any, Callable

import gads_bidstrategy
import gads_client
import gads_competitors
import gads_conversions
import gads_demographics
import gads_display
import gads_gtag
import gads_history
import gads_pacing
import gads_placements
import gads_pmax
import gads_quality
import gads_recommendations
import gads_search
import gads_shopping
import gads_uac
import gads_utils
import gads_youtube

# (agent_name, callable). Each callable takes (customer_id, days).
DEFAULT_AGENTS: list[tuple[str, Callable[..., Any]]] = [
    ("gads-conversions",    lambda cid, days: gads_conversions.health(cid)),
    ("gads-search",         lambda cid, days: gads_search.list_campaigns(cid, days)),
    ("gads-search-terms",   lambda cid, days: gads_search.negative_candidates(cid, days)),
    ("gads-pmax",           lambda cid, days: gads_pmax.asset_groups(cid, days)),
    ("gads-uac",            lambda cid, days: gads_uac.app_campaigns(cid, days)),
    ("gads-display",        lambda cid, days: gads_display.display_campaigns(cid, days)),
    ("gads-shopping",       lambda cid, days: gads_shopping.shopping_campaigns(cid, days)),
    ("gads-youtube",        lambda cid, days: gads_youtube.youtube_campaigns(cid, days)),
    ("gads-competitors",    lambda cid, days: gads_competitors.auction_insights(cid, days)),
    ("gads-placements",     lambda cid, days: gads_placements.scan(cid, days)),
    ("gads-recommendations", lambda cid, days: gads_recommendations.fetch(cid)),
    ("gads-bidstrategy",    lambda cid, days: gads_bidstrategy.analyze(cid, days)),
    ("gads-pacing",         lambda cid, days: gads_pacing.analyze(cid)),
    ("gads-quality",        lambda cid, days: gads_quality.audit(cid, days)),
    ("gads-demographics",   lambda cid, days: gads_demographics.all_breakdowns(cid, days)),
]


def run(customer_id: str, days: int = 28, site: str | None = None,
        max_workers: int = 6) -> dict:
    customer_id = gads_utils.normalize_customer_id(customer_id)
    start, end = gads_utils.date_range(days)

    work: list[tuple[str, Callable[[], Any]]] = []
    if site:
        work.append(("gads-gtag", lambda: {
            "customer_id": customer_id,
            "site_scan": gads_gtag.scan_site(site),
            "linked": gads_gtag.linked_accounts(customer_id),
        }))
    for name, fn in DEFAULT_AGENTS:
        work.append((name, lambda fn=fn: fn(customer_id, days)))

    agents: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_name = {pool.submit(_safe, fn): name for name, fn in work}
        for fut in concurrent.futures.as_completed(future_to_name):
            agents[future_to_name[fut]] = fut.result()

    return {
        "customer_id": customer_id,
        "date_range": {"start": start, "end": end},
        "agents": agents,
    }


def _safe(thunk: Callable[[], Any]) -> dict:
    """Run an agent thunk and capture API/auth errors as a `failed` block."""
    try:
        out = thunk()
        if not isinstance(out, dict):
            out = {"data": out}
        out.setdefault("status", "ok")
        return out
    except Exception as e:
        return {
            "status": "failed",
            "error": str(e),
            "traceback": traceback.format_exc(limit=2),
        }


def list_all_customers() -> list[str]:
    client = gads_client.build_client()
    svc = client.get_service("CustomerService")
    return [r.split("/")[-1] for r in svc.list_accessible_customers().resource_names]


def run_many(customer_ids: list[str], days: int, site: str | None,
             account_workers: int = 3, agent_workers: int = 6) -> dict:
    """Run audits across multiple customers, capping concurrent accounts."""
    results: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=account_workers) as pool:
        futures = {
            pool.submit(run, cid, days, site, agent_workers): cid
            for cid in customer_ids
        }
        for fut in concurrent.futures.as_completed(futures):
            results[futures[fut]] = fut.result()
    return {"accounts": results, "summary": f"audited {len(results)} accounts"}


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--customer", help="Single customer ID")
    g.add_argument("--all-customers", action="store_true",
                   help="Fan out across every accessible customer in parallel")
    p.add_argument("--days", type=int, default=28)
    p.add_argument("--site", help="Site URL for the gtag scan")
    p.add_argument("--output", help="Path to write merged JSON (default: stdout)")
    p.add_argument("--save-history", action="store_true",
                   help="Persist under ~/.claude/gads-audit-history/<customer>/")
    p.add_argument("--workers", type=int, default=6,
                   help="Concurrent agent workers per account (default 6)")
    p.add_argument("--account-workers", type=int, default=3,
                   help="Concurrent accounts when --all-customers (default 3)")
    args = p.parse_args()

    if args.all_customers:
        customer_ids = list_all_customers()
        data = run_many(customer_ids, args.days, args.site,
                        args.account_workers, args.workers)
    else:
        data = run(args.customer, args.days, args.site, args.workers)

    blob = json.dumps(data, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as f:
            f.write(blob)
    else:
        print(blob)

    if args.save_history:
        if args.all_customers:
            for _, audit in data.get("accounts", {}).items():
                saved = gads_history.save_audit(audit)
                print(f"history: {saved}", file=sys.stderr)
        else:
            saved = gads_history.save_audit(data)
            print(f"history: {saved}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
