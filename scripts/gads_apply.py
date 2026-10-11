"""Reviewed keyword, placement and Display optimized-targeting writes."""

from __future__ import annotations

import argparse
import json
import sys

import gads_errors
import gads_utils
from gads_mutate import reviewed_mutate
from google.api_core.exceptions import NotFound


class WriteInputError(ValueError):
    pass


def numeric_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise WriteInputError(f"{label} must be a numeric string")
    return value


def read_campaign(client, customer_id: str, campaign_id: str):
    query = f"""SELECT campaign.resource_name, campaign.advertising_channel_type,
                      campaign.status
               FROM campaign WHERE campaign.id = {campaign_id}"""
    rows = list(client.get_service("GoogleAdsService").search(
        customer_id=customer_id, query=query))
    if not rows:
        raise NotFound(f"Campaign {campaign_id} not_found")
    return rows[0].campaign

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

    customer_id = numeric_id(gads_utils.normalize_customer_id(customer_id), "Customer ID")
    if (not isinstance(payload, dict) or not {"campaign_id", "terms"} <= payload.keys()
            or payload.keys() - {"campaign_id", "terms", "match_type"}):
        raise WriteInputError("Negatives require campaign_id, terms and optional match_type")
    campaign_id = numeric_id(payload["campaign_id"], "Campaign ID")
    terms = payload["terms"]
    match_type = payload.get("match_type", "EXACT")
    if (not isinstance(terms, list) or not terms
            or any(not isinstance(term, str) or not term.strip() for term in terms)
            or match_type not in ("EXACT", "PHRASE", "BROAD")):
        raise WriteInputError("Provide non-empty terms and EXACT, PHRASE or BROAD match_type")

    client = gads_client.build_client()
    campaign = read_campaign(client, customer_id, campaign_id)
    if campaign.advertising_channel_type.name == "VIDEO":
        raise WriteInputError("The API does not support Video campaign mutations")
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

    resp = reviewed_mutate(
        svc.mutate_campaign_criteria,
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


def apply_placement_exclusions(customer_id: str, payload: dict, validate_only: bool,
                               campaign_id: str | None = None) -> dict:
    import gads_client

    customer_id = numeric_id(gads_utils.normalize_customer_id(customer_id), "Customer ID")
    if campaign_id is not None:
        numeric_id(campaign_id, "Campaign ID")
    if not isinstance(payload, dict):
        raise WriteInputError("Placements must be an object of category arrays")
    placements: list[str] = []
    for _category, entries in payload.items():
        if not isinstance(entries, list):
            raise WriteInputError("Placement categories must contain arrays")
        for entry in entries:
            if not isinstance(entry, dict) or any(
                    entry.get(key) is not None and not isinstance(entry[key], str)
                    for key in ("target_url", "placement")):
                raise WriteInputError("Placement entries must contain string URLs")
            url = entry.get("target_url") or entry.get("placement")
            if url:
                placements.append(url)

    client = gads_client.build_client()
    if campaign_id is not None:
        campaign = read_campaign(client, customer_id, campaign_id)
        if campaign.advertising_channel_type.name != "DISPLAY":
            raise WriteInputError("Campaign placement exclusions require DISPLAY; got "
                             + campaign.advertising_channel_type.name)
        service = client.get_service("CampaignCriterionService")
        mutation = service.mutate_campaign_criteria
        operation_type = "CampaignCriterionOperation"
    else:
        service = client.get_service("CustomerNegativeCriterionService")
        mutation = service.mutate_customer_negative_criteria
        operation_type = "CustomerNegativeCriterionOperation"
    operations = []
    for url in placements:
        op = client.get_type(operation_type)
        crit = op.create
        if campaign_id is not None:
            crit.campaign = f"customers/{customer_id}/campaigns/{campaign_id}"
            crit.negative = True
        # Best-effort placement vs YouTube channel vs mobile-app routing.
        if url.startswith("mobileapp://"):
            crit.mobile_application.app_id = url.split("://", 1)[1]
        elif "youtube.com/channel" in url or url.startswith("UC"):
            crit.youtube_channel.channel_id = url.rstrip("/").rsplit("/", 1)[-1]
        else:
            crit.placement.url = url
        operations.append(op)

    resp = reviewed_mutate(
        mutation,
        customer_id=customer_id,
        operations=operations,
        validate_only=validate_only,
    )
    return {
        "excluded": len(resp.results),
        "validate_only": validate_only,
    }


def apply_optimized_targeting(customer_id: str, payload: dict, validate_only: bool) -> dict:
    import gads_client

    customer_id = numeric_id(gads_utils.normalize_customer_id(customer_id), "Customer ID")
    if not isinstance(payload, dict) or set(payload) != {"ad_group_id", "enabled"}:
        raise WriteInputError("Expected exactly ad_group_id and enabled")
    ad_group_id = numeric_id(payload["ad_group_id"], "Ad group ID")
    if type(payload["enabled"]) is not bool:
        raise WriteInputError("enabled must be a boolean")
    client = gads_client.build_client()
    query = f"""SELECT ad_group.resource_name, ad_group.optimized_targeting_enabled,
                      campaign.advertising_channel_type
               FROM ad_group WHERE ad_group.id = {ad_group_id}"""
    rows = list(client.get_service("GoogleAdsService").search(
        customer_id=customer_id, query=query))
    if not rows:
        raise NotFound(f"Ad group {ad_group_id} not_found")
    row = rows[0]
    if row.campaign.advertising_channel_type.name != "DISPLAY":
        raise WriteInputError("Optimized targeting requires DISPLAY; got "
                         + row.campaign.advertising_channel_type.name)
    previous = row.ad_group.optimized_targeting_enabled
    print(json.dumps({"ad_group_id": ad_group_id, "previous": previous,
                      "enabled": payload["enabled"]}), file=sys.stderr)
    op = client.get_type("AdGroupOperation")
    op.update.resource_name = row.ad_group.resource_name
    op.update.optimized_targeting_enabled = payload["enabled"]
    op.update_mask.paths.append("optimized_targeting_enabled")
    response = reviewed_mutate(client.get_service("AdGroupService").mutate_ad_groups,
                               customer_id=customer_id, operations=[op],
                               validate_only=validate_only)
    return {"ad_group_id": ad_group_id, "previous": previous, "enabled": payload["enabled"],
            "updated": len(response.results), "validate_only": validate_only}


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
    pla.add_argument("--campaign-id", help="Restrict exclusions to a DISPLAY campaign")
    opt = sub.add_parser("optimized-targeting", help="Set Display ad group optimized targeting")
    opt.add_argument("--input", required=True, help="JSON with ad_group_id and boolean enabled")

    for s in (neg, pla, opt):
        mode = s.add_mutually_exclusive_group()
        mode.add_argument("--validate-only", action="store_true")
        mode.add_argument("--apply", action="store_true")
        s.add_argument("--json", action="store_true")

    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    if not (args.validate_only or args.apply):
        gads_utils.emit({
            "status": "no_op",
            "hint": "Pass --validate-only for a dry-run or --apply to send the mutate.",
        }, getattr(args, "json", False))
        return 0

    try:
        with open(args.input) as f:
            payload = json.load(f)
        if args.action == "negatives":
            result = apply_negatives(cid, payload, validate_only=not args.apply)
        elif args.action == "optimized-targeting":
            result = apply_optimized_targeting(cid, payload, validate_only=not args.apply)
        else:
            result = apply_placement_exclusions(cid, payload, validate_only=not args.apply,
                                                campaign_id=args.campaign_id)
    except Exception as e:
        failure = {**gads_errors.describe(e), "action": args.action}
        if isinstance(e, WriteInputError):
            failure["error"] = str(e)
        failure["summary"] = f"{failure['error_code']}: {failure['error']}"
        gads_utils.emit(failure, args.json)
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
