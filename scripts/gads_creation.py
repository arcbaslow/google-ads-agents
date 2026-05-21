"""Campaign creation wizard.

This script does not silently create campaigns. It collects context from the
caller (the agent will collect it from the user), validates it, and only
then proposes a mutate JSON. The final mutate is shown to the user before
anything is sent.

Required context (any missing field aborts):

  - business        free-form business / vertical
  - website         URL, reachability checked
  - goal            sales | leads | traffic | awareness | app_installs
  - analytics_ok    bool — gtag/GA4 verified by gads_gtag
  - conversions_ok  bool — at least one primary-for-goal conversion exists
  - budget          daily budget in account currency
  - bidding         e.g. MAXIMIZE_CONVERSIONS, TARGET_CPA, TARGET_ROAS
  - geos            list of country codes or geo target IDs
  - languages       list of ISO codes
  - channel         SEARCH | DISPLAY | VIDEO | SHOPPING | PERFORMANCE_MAX | APP

The agent populates these from user prompts. This script just refuses to
proceed when something is missing or contradictory.
"""

from __future__ import annotations

import argparse
import json
import sys

import gads_utils

REQUIRED_FIELDS = [
    "business", "website", "goal", "analytics_ok", "conversions_ok",
    "budget", "bidding", "geos", "languages", "channel",
]

VALID_GOALS = {"sales", "leads", "traffic", "awareness", "app_installs"}
VALID_CHANNELS = {"SEARCH", "DISPLAY", "VIDEO", "SHOPPING", "PERFORMANCE_MAX", "APP"}


def validate(ctx: dict) -> list[str]:
    errs: list[str] = []
    for f in REQUIRED_FIELDS:
        if f not in ctx or ctx[f] in (None, "", []):
            errs.append(f"missing: {f}")
    if "goal" in ctx and ctx["goal"] not in VALID_GOALS:
        errs.append(f"goal must be one of {sorted(VALID_GOALS)}")
    if "channel" in ctx and ctx["channel"] not in VALID_CHANNELS:
        errs.append(f"channel must be one of {sorted(VALID_CHANNELS)}")
    if ctx.get("analytics_ok") is False:
        errs.append("analytics_ok is false — install gtag/GA4 first (see /gads gtag)")
    if ctx.get("conversions_ok") is False and ctx.get("goal") in {"sales", "leads", "app_installs"}:
        errs.append("conversions_ok is false — define a primary conversion (see /gads conversions)")
    return errs


def propose_mutate(ctx: dict) -> dict:
    return {
        "campaign": {
            "name": ctx.get("name") or f"{ctx['business']} — {ctx['goal']}",
            "advertising_channel_type": ctx["channel"],
            "status": "PAUSED",
            "campaign_budget": {
                "amount_micros": int(float(ctx["budget"]) * 1_000_000),
                "delivery_method": "STANDARD",
            },
            "bidding_strategy": ctx["bidding"],
            "geo_target_constants": ctx["geos"],
            "language_constants": ctx["languages"],
        }
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--context-file", required=True, help="JSON file with required fields")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    with open(args.context_file) as f:
        ctx = json.load(f)

    errs = validate(ctx)
    if errs:
        gads_utils.emit({"status": "blocked", "errors": errs}, args.json)
        return 2

    proposed = propose_mutate(ctx)
    gads_utils.emit({
        "status": "ready",
        "customer_id": cid,
        "proposed_mutate": proposed,
        "next_step": "Review the JSON. Confirm with the user. Then call the GoogleAdsService.mutate.",
    }, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
