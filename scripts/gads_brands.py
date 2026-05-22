"""Brand suggestions and brand-exclusion writes.

Two subcommands:

  suggest  — call BrandSuggestionService for one or more brand-name
             queries. Returns brand IDs with name and primary URL so
             the agent can confirm with the user before excluding.

  exclude  — attach a brand exclusion (CampaignCriterion with the
             brand criterion, negative=true) to one or more PMax
             campaigns. Standard --validate-only / --apply gates.

Brand exclusions are PMax-specific (the API rejects them on other
channels), and Google's brand-suggestion catalogue isn't exhaustive —
the agent should warn the user that the suggestion call may return
nothing for niche or new brands.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import gads_utils


def suggest(customer_id: str, queries: list[str]) -> dict:
    import gads_client

    client = gads_client.build_client()
    svc = client.get_service("BrandSuggestionService")
    suggestions: list[dict] = []
    for q in queries:
        req = client.get_type("SuggestBrandsRequest")
        req.customer_id = customer_id
        req.brand_prefix = q
        resp = svc.suggest_brands(request=req)
        for brand in resp.brands:
            suggestions.append({
                "query": q,
                "id": brand.id,
                "name": brand.name,
                "urls": list(getattr(brand, "urls", [])),
                "state": getattr(brand, "entity_status", None),
            })
    return {"queries": queries, "suggestions": suggestions, "summary": f"{len(suggestions)} brand suggestion(s)"}


def exclude(customer_id: str, campaign_ids: list[str], brand_ids: list[str],
            validate_only: bool) -> dict:
    import gads_client

    client = gads_client.build_client()
    svc = client.get_service("CampaignCriterionService")
    campaign_svc = client.get_service("CampaignService")

    operations = []
    for campaign_id in campaign_ids:
        for brand_id in brand_ids:
            op = client.get_type("CampaignCriterionOperation")
            crit = op.create
            crit.campaign = campaign_svc.campaign_path(customer_id, campaign_id)
            crit.negative = True
            crit.brand.entity_id = brand_id
            operations.append(op)

    resp = svc.mutate_campaign_criteria(
        customer_id=customer_id,
        operations=operations,
        validate_only=validate_only,
    )
    return {
        "campaigns": campaign_ids,
        "brand_ids": brand_ids,
        "excluded": len(resp.results),
        "validate_only": validate_only,
    }


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("suggest", help="Search the brand catalogue by name prefix")
    s.add_argument("--query", nargs="+", required=True, help="One or more brand names to look up")

    e = sub.add_parser("exclude", help="Attach brand exclusions to PMax campaigns")
    e.add_argument("--input", help="JSON file with {campaign_ids, brand_ids}")
    e.add_argument("--campaign-ids", nargs="+", help="Override input file")
    e.add_argument("--brand-ids", nargs="+", help="Override input file")
    e.add_argument("--validate-only", action="store_true")
    e.add_argument("--apply", action="store_true")

    for sp in (s, e):
        sp.add_argument("--json", action="store_true")

    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    if args.action == "suggest":
        try:
            data = suggest(cid, args.query)
        except Exception as ex:
            gads_utils.emit({"status": "api_error", "error": str(ex)}, args.json)
            return 3
        gads_utils.emit(data, args.json)
        return 0

    # exclude
    if not (args.validate_only or args.apply):
        gads_utils.emit({
            "status": "no_op",
            "hint": "Pass --validate-only for a dry-run or --apply to send the mutate.",
        }, args.json)
        return 0

    if args.input:
        with open(args.input) as f:
            payload = json.load(f)
        campaign_ids = payload["campaign_ids"]
        brand_ids = payload["brand_ids"]
    else:
        if not (args.campaign_ids and args.brand_ids):
            p.error("Either --input or both --campaign-ids and --brand-ids are required")
        campaign_ids = args.campaign_ids
        brand_ids = args.brand_ids

    try:
        result = exclude(cid, campaign_ids, brand_ids, validate_only=not args.apply)
    except Exception as ex:
        gads_utils.emit({"status": "api_error", "error": str(ex)}, args.json)
        return 3
    gads_utils.emit({
        "status": "validated" if not args.apply else "applied",
        "customer_id": cid,
        "result": result,
    }, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
