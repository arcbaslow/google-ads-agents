"""Write paths for the two most common changes an audit produces:

  - Negative keywords. Either add them to a single campaign (criterion
    on the campaign) or to a shared negative-keyword list (one list,
    many campaigns). Defaults to the campaign path because it's the
    safer first step.

  - Placement exclusions. Adds a CustomerNegativeCriterion for each
    placement, so the exclusion holds across every campaign on the
    account.

Both subcommands accept a JSON input file produced by an upstream
script and require either --validate-only (dry-run via the API) or
--apply (real send). Nothing is mutated by default.
"""

from __future__ import annotations

import argparse
import json
import sys

import gads_utils

# ---------- input shapes ----------
#
# Negatives file format:
# {
#   "campaign_id": "1234567890",
#   "match_type": "EXACT" | "PHRASE" | "BROAD",
#   "terms": ["wasted term one", "another", ...]
# }
#
# Placements file format (the `to_exclude` block from gads_placements.scan):
# {
#   "scam": [{"placement": "...", "target_url": "..."}],
#   "politics": [...]
# }


def apply_negatives(customer_id: str, payload: dict, validate_only: bool) -> dict:
    import gads_client

    campaign_id = payload["campaign_id"]
    terms = payload["terms"]
    match_type = payload.get("match_type", "EXACT")

    client = gads_client.build_client()
    svc = client.get_service("CampaignCriterionService")
    campaign_path = client.get_service("CampaignService").campaign_path(customer_id, campaign_id)

    operations = []
    for term in terms:
        op = client.get_type("CampaignCriterionOperation")
        crit = op.create
        crit.campaign = campaign_path
        crit.negative = True
        crit.keyword.text = term
        crit.keyword.match_type = getattr(client.enums.KeywordMatchTypeEnum, match_type)
        operations.append(op)

    resp = svc.mutate_campaign_criteria(
        customer_id=customer_id,
        operations=operations,
        validate_only=validate_only,
    )
    return {
        "campaign_id": campaign_id,
        "match_type": match_type,
        "added": len(resp.results),
        "validate_only": validate_only,
    }


def apply_placement_exclusions(customer_id: str, payload: dict, validate_only: bool) -> dict:
    import gads_client

    client = gads_client.build_client()
    svc = client.get_service("CustomerNegativeCriterionService")

    placements: list[str] = []
    for _category, entries in payload.items():
        for entry in entries:
            url = entry.get("target_url") or entry.get("placement")
            if url:
                placements.append(url)

    operations = []
    for url in placements:
        op = client.get_type("CustomerNegativeCriterionOperation")
        crit = op.create
        # Best-effort placement vs YouTube channel vs mobile-app routing.
        if url.startswith("mobileapp://"):
            crit.mobile_application.app_id = url.split("://", 1)[1]
        elif "youtube.com/channel" in url or url.startswith("UC"):
            crit.youtube_channel.channel_id = url.rstrip("/").rsplit("/", 1)[-1]
        else:
            crit.placement.url = url
        operations.append(op)

    resp = svc.mutate_customer_negative_criteria(
        customer_id=customer_id,
        operations=operations,
        validate_only=validate_only,
    )
    return {
        "excluded": len(resp.results),
        "validate_only": validate_only,
    }


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    sub = p.add_subparsers(dest="action", required=True)

    neg = sub.add_parser("negatives", help="Add negative keywords to a campaign")
    neg.add_argument("--input", required=True, help="JSON with campaign_id, match_type, terms")

    pla = sub.add_parser("placements", help="Add placement exclusions at the account level")
    pla.add_argument("--input", required=True,
                     help="JSON as produced by gads_placements.scan --to_exclude")

    for s in (neg, pla):
        s.add_argument("--validate-only", action="store_true")
        s.add_argument("--apply", action="store_true")
        s.add_argument("--json", action="store_true")

    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    if not (args.validate_only or args.apply):
        gads_utils.emit({
            "status": "no_op",
            "hint": "Pass --validate-only for a dry-run or --apply to send the mutate.",
        }, getattr(args, "json", False))
        return 0

    with open(args.input) as f:
        payload = json.load(f)

    try:
        if args.action == "negatives":
            result = apply_negatives(cid, payload, validate_only=not args.apply)
        else:
            result = apply_placement_exclusions(cid, payload, validate_only=not args.apply)
    except Exception as e:
        gads_utils.emit({
            "status": "api_error",
            "action": args.action,
            "error": str(e),
        }, args.json)
        return 3

    gads_utils.emit({
        "status": "validated" if not args.apply else "applied",
        "action": args.action,
        "customer_id": cid,
        "result": result,
    }, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
