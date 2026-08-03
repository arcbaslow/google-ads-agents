"""Campaign creation wizard.

This script does not silently create campaigns. The flow is:

  1. Collect context from the caller (the agent collects it from the
     user). All required fields must be present.
  2. Propose a mutate JSON. Show it to the user.
  3. Optional --validate-only: send a real validate_only=True mutate so
     the API can reject obvious mistakes (bad geo IDs, invalid bidding
     strategy for the channel, etc.) without creating anything.
  4. With --apply, send the actual mutate. The campaign is created
     PAUSED regardless.

Required context, any missing field aborts:

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


def send_mutate(customer_id: str, proposed: dict, validate_only: bool) -> dict:
    """Send the proposed mutate against the live API.

    With validate_only=True the API returns the same errors it would on
    a real mutate but does not create the campaign.
    """
    import gads_client

    client = gads_client.build_client()
    budget_svc = client.get_service("CampaignBudgetService")
    campaign_svc = client.get_service("CampaignService")

    # Step 1: budget. The campaign references it by resource name.
    budget_op = client.get_type("CampaignBudgetOperation")
    budget = budget_op.create
    budget.name = f"{proposed['campaign']['name']} budget"
    budget.amount_micros = proposed["campaign"]["campaign_budget"]["amount_micros"]
    budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD

    budget_resp = budget_svc.mutate_campaign_budgets(
        customer_id=customer_id,
        operations=[budget_op],
        validate_only=validate_only,
    )
    budget_resource = budget_resp.results[0].resource_name if budget_resp.results else None

    # Step 2: campaign.
    campaign_op = client.get_type("CampaignOperation")
    c = campaign_op.create
    c.name = proposed["campaign"]["name"]
    c.advertising_channel_type = getattr(
        client.enums.AdvertisingChannelTypeEnum, proposed["campaign"]["advertising_channel_type"]
    )
    c.status = client.enums.CampaignStatusEnum.PAUSED
    # Required on create since the EU political advertising rules; omitting it
    # fails with field_error: REQUIRED on contains_eu_political_advertising.
    c.contains_eu_political_advertising = (
        client.enums.EuPoliticalAdvertisingStatusEnum
        .DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
    )
    if budget_resource:
        c.campaign_budget = budget_resource

    campaign_resp = campaign_svc.mutate_campaigns(
        customer_id=customer_id,
        operations=[campaign_op],
        validate_only=validate_only,
    )

    return {
        "validate_only": validate_only,
        "budget_resource": budget_resource,
        "campaign_resource": (
            campaign_resp.results[0].resource_name if campaign_resp.results else None
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--context-file", required=True, help="JSON file with required fields")
    p.add_argument("--validate-only", action="store_true",
                   help="Dry-run the mutate against the API; nothing is created")
    p.add_argument("--apply", action="store_true",
                   help="Send the real mutate. Campaign is created PAUSED.")
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

    if args.validate_only or args.apply:
        try:
            result = send_mutate(cid, proposed, validate_only=not args.apply)
        except Exception as e:  # surface API errors as JSON, don't crash the wizard
            gads_utils.emit({
                "status": "api_error",
                "customer_id": cid,
                "proposed_mutate": proposed,
                "error": str(e),
            }, args.json)
            return 3
        gads_utils.emit({
            "status": "validated" if not args.apply else "applied",
            "customer_id": cid,
            "proposed_mutate": proposed,
            "result": result,
        }, args.json)
        return 0

    gads_utils.emit({
        "status": "ready",
        "customer_id": cid,
        "proposed_mutate": proposed,
        "next_step": "Review the JSON. Re-run with --validate-only for a dry-run, then --apply to send.",
    }, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
