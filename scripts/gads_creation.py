"""Campaign planning and a bounded atomic PAUSED Search writer.

Legacy planning drafts remain non-executable; --search-spec uses a strict
owner-supplied contract documented in docs/WRITES.md.

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


def create_search_campaign(customer_id: str, spec: dict, validate_only: bool = True) -> dict:
    """Create a paused Search shell; ads and subsequent activation are separate work."""
    import gads_client
    from gads_mutate import reviewed_atomic_mutate

    expected = {"name", "budget_micros", "bidding", "geo_target_ids", "language_mode",
                "eu_political_advertising", "analytics_confirmed", "conversions_confirmed"}
    if not isinstance(spec, dict) or set(spec) != expected:
        raise ValueError("Search spec must contain exactly the documented fields")
    cid = gads_utils.normalize_customer_id(customer_id)
    if not cid.isascii() or not cid.isdigit():
        raise ValueError("Customer ID must be numeric")
    name = spec["name"]
    if not isinstance(name, str) or not name.strip() or any(c in name for c in "\x00\n\r"):
        raise ValueError("A non-empty campaign name without control characters is required")
    amount = spec["budget_micros"]
    if type(amount) is not int or not 0 < amount < 2**63:
        raise ValueError("budget_micros must be a positive integer")
    if spec["bidding"] != "MAXIMIZE_CONVERSIONS" or spec["language_mode"] != "AUTOMATIC":
        raise ValueError("Only MAXIMIZE_CONVERSIONS and AUTOMATIC language are supported")
    for key in ("analytics_confirmed", "conversions_confirmed"):
        if spec[key] is not True:
            raise ValueError(f"{key} must be explicitly true")
    if type(spec["eu_political_advertising"]) is not bool:
        raise ValueError("An explicit boolean EU political advertising declaration is required")
    geos = spec["geo_target_ids"]
    if (not isinstance(geos, list) or not geos or len(geos) > 100
            or any(not isinstance(g, str) or not g.isascii() or not g.isdigit() for g in geos)):
        raise ValueError("Provide 1–100 numeric geo target IDs as strings")

    client = gads_client.build_client()
    budget_name, campaign_name = f"customers/{cid}/campaignBudgets/-1", f"customers/{cid}/campaigns/-2"
    budget = client.get_type("MutateOperation")
    budget.campaign_budget_operation.create = {
        "resource_name": budget_name, "name": name + " budget", "amount_micros": amount,
        "delivery_method": "STANDARD", "explicitly_shared": False,
    }
    campaign = client.get_type("MutateOperation")
    campaign.campaign_operation.create = {
        "resource_name": campaign_name, "name": name, "status": "PAUSED",
        "advertising_channel_type": "SEARCH", "campaign_budget": budget_name,
        "maximize_conversions": {},
        "network_settings": {"target_google_search": True, "target_search_network": False,
                             "target_content_network": False, "target_partner_search_network": False},
        "geo_target_type_setting": {"positive_geo_target_type": "PRESENCE"},
        "contains_eu_political_advertising": (
            "CONTAINS_EU_POLITICAL_ADVERTISING" if spec["eu_political_advertising"]
            else "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"),
    }
    operations = [budget, campaign]
    for geo in sorted(set(geos)):
        op = client.get_type("MutateOperation")
        op.campaign_criterion_operation.create = {
            "campaign": campaign_name, "location": {"geo_target_constant": f"geoTargetConstants/{geo}"},
        }
        operations.append(op)
    response = reviewed_atomic_mutate(client, cid, operations, validate_only)
    return {"status": "validated" if validate_only else "applied", "customer_id": cid,
            "response": gads_client._msg_to_dict(response._pb),
            "limitations": ["PAUSED Search shell only; no ads, keywords or activation.",
                            "No idempotency guarantee: inspect account state before retrying an uncertain write."]}

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
    """Reject the incomplete writer before credentials or services are accessed."""
    raise NotImplementedError(
        "Campaign creation is unavailable: the planning draft is not a complete "
        "atomic API request. No budget or campaign was sent."
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--context-file", help="Legacy planning context; not executable")
    source.add_argument("--search-spec", help="Strict JSON spec for a PAUSED Search shell")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true", help="Review and validate a Search spec only")
    mode.add_argument("--apply", action="store_true", help="Review, validate and apply a Search spec")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    if args.search_spec:
        if not (args.validate_only or args.apply):
            gads_utils.emit({"status": "no_op", "hint": "Choose --validate-only or --apply"}, args.json)
            return 0
        import gads_errors
        try:
            with open(args.search_spec) as f:
                spec = json.load(f)
            result = create_search_campaign(cid, spec, validate_only=not args.apply)
        except Exception as exc:
            gads_utils.emit(gads_errors.describe(exc), args.json)
            return 3
        gads_utils.emit(result, args.json)
        return 0

    if args.validate_only or args.apply:
        try:
            send_mutate(cid, {}, validate_only=not args.apply)
        except NotImplementedError as exc:
            gads_utils.emit({"status": "unsupported", "error": str(exc)}, args.json)
            return 2

    with open(args.context_file) as f:
        ctx = json.load(f)

    errs = validate(ctx)
    if errs:
        gads_utils.emit({"status": "blocked", "errors": errs}, args.json)
        return 2

    proposed = propose_mutate(ctx)


    gads_utils.emit({
        "status": "planning_only",
        "customer_id": cid,
        "campaign_plan": proposed,
        "next_step": "Review this planning draft. API creation and validation are unavailable.",
    }, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
