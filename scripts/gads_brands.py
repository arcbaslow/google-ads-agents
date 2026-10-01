"""Look up brands and review bounded PMax brand-list exclusions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

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
                "urls": list(brand.urls),
                "state": brand.state.name,
            })
    return {"queries": queries, "suggestions": suggestions, "summary": f"{len(suggestions)} brand suggestion(s)"}


def exclude(customer_id: str, campaign_ids: list[str], brand_ids: list[str],
            validate_only: bool) -> dict:
    import gads_client
    from gads_mutate import reviewed_atomic_mutate

    cid = gads_utils.normalize_customer_id(customer_id)
    if not re.fullmatch(r"[0-9]+", cid):
        raise ValueError("Customer ID must be numeric")
    if (not isinstance(campaign_ids, list) or not 1 <= len(campaign_ids) <= 100
            or any(not isinstance(c, str) or not re.fullmatch(r"[0-9]+", c) for c in campaign_ids)):
        raise ValueError("Provide 1–100 numeric campaign IDs")
    if (not isinstance(brand_ids, list) or not 1 <= len(brand_ids) <= 100
            or any(not isinstance(b, str) or not b.strip() or len(b) > 256
                   or any(ord(c) < 32 for c in b) for b in brand_ids)):
        raise ValueError("Provide 1–100 catalogue brand IDs")
    campaigns, brands = sorted(set(campaign_ids)), sorted(set(brand_ids))
    digest = hashlib.sha256(json.dumps(brands, separators=(",", ":")).encode()).hexdigest()[:24]
    name = f"gads-agents-brands-{digest}"
    client = gads_client.build_client()

    def read(query):
        return gads_client.search_stream(cid, query)

    rows = read("SELECT campaign.id, campaign.status, campaign.advertising_channel_type "
                f"FROM campaign WHERE campaign.id IN ({','.join(campaigns)})")
    found = {str(r["campaign"]["id"]): r["campaign"] for r in rows}
    if set(found) != set(campaigns) or any(
        c.get("status") not in {"ENABLED", "PAUSED"}
        or c.get("advertising_channel_type") != "PERFORMANCE_MAX" for c in found.values()
    ):
        raise ValueError("Every selected campaign must be an existing active or paused PMax campaign")
    lists = read("SELECT shared_set.resource_name, shared_set.name, shared_set.status "
                 "FROM shared_set WHERE shared_set.type = 'BRANDS' AND shared_set.status != 'REMOVED'")
    matches = [r["shared_set"] for r in lists if r["shared_set"].get("name") == name]
    if len(matches) > 1:
        raise ValueError("Duplicate managed list names require manual review")
    operations = []
    if matches:
        shared_set = matches[0]["resource_name"]
        if not re.fullmatch(rf"customers/{cid}/sharedSets/[0-9]+", shared_set):
            raise ValueError("Shared list must belong to this customer")
        if matches[0].get("status") != "ENABLED":
            raise ValueError("Managed list is not enabled")
        contents = read("SELECT shared_criterion.brand.entity_id FROM shared_criterion "
                        f"WHERE shared_criterion.shared_set = '{shared_set}'")
        if {r["shared_criterion"].get("brand", {}).get("entity_id") for r in contents} != set(brands):
            raise ValueError("Managed list contents changed; review it before reuse")
    else:
        shared_set = f"customers/{cid}/sharedSets/-1"
        op = client.get_type("MutateOperation")
        op.shared_set_operation.create = {"resource_name": shared_set, "name": name, "type_": "BRANDS"}
        operations.append(op)
        for brand in brands:
            op = client.get_type("MutateOperation")
            op.shared_criterion_operation.create = {"shared_set": shared_set, "brand": {"entity_id": brand}}
            operations.append(op)

    links = read("SELECT campaign.id, campaign_criterion.brand_list.shared_set, campaign_criterion.negative "
                 "FROM campaign_criterion WHERE campaign_criterion.type = 'BRAND_LIST' "
                 "AND campaign_criterion.status != 'REMOVED' "
                 f"AND campaign.id IN ({','.join(campaigns)})")
    attached = {str(r["campaign"]["id"]) for r in links
                if r["campaign_criterion"].get("negative") is True
                and r["campaign_criterion"].get("brand_list", {}).get("shared_set") == shared_set}
    for campaign in campaigns:
        if campaign not in attached:
            op = client.get_type("MutateOperation")
            op.campaign_criterion_operation.create = {
                "campaign": f"customers/{cid}/campaigns/{campaign}", "negative": True,
                "brand_list": {"shared_set": shared_set},
            }
            operations.append(op)
    result = {"customer_id": cid, "managed_list_name": name, "campaign_ids": campaigns,
              "brand_ids": brands, "limitations": [
                  "No edits, removals or cross-account lists; PMax exclusions only.",
                  "Concurrent changes are not locked; inspect account state after an uncertain apply."]}
    if not operations:
        return {**result, "status": "no_op"}
    response = reviewed_atomic_mutate(client, cid, operations, validate_only)
    return {**result, "status": "validated" if validate_only else "applied",
            "response": gads_client._msg_to_dict(response._pb)}


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("suggest", help="Search the brand catalogue by name prefix")
    s.add_argument("--query", nargs="+", required=True, help="One or more brand names to look up")

    e = sub.add_parser("exclude", help="Review and attach a PMax brand exclusion list")
    e.add_argument("--input", help="JSON file with {campaign_ids, brand_ids}")
    e.add_argument("--campaign-ids", nargs="+", help="Override input file")
    e.add_argument("--brand-ids", nargs="+", help="Override input file")
    mode = e.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--apply", action="store_true")

    for sp in (s, e):
        sp.add_argument("--json", action="store_true")

    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    import gads_errors

    if args.action == "suggest":
        try:
            data = suggest(cid, args.query)
        except Exception as ex:
            gads_utils.emit(gads_errors.describe(ex), args.json)
            return 3
        gads_utils.emit(data, args.json)
        return 0

    if not (args.apply or args.validate_only):
        gads_utils.emit({"status": "no_op", "hint": "Choose --validate-only or --apply"}, args.json)
        return 0
    try:
        data = {}
        if args.input:
            with open(args.input) as f:
                data = json.load(f)
            if not isinstance(data, dict) or set(data) != {"campaign_ids", "brand_ids"}:
                raise ValueError("Input requires exactly campaign_ids and brand_ids")
        result = exclude(cid, args.campaign_ids or data.get("campaign_ids"),
                         args.brand_ids or data.get("brand_ids"), validate_only=not args.apply)
    except Exception as exc:
        gads_utils.emit(gads_errors.describe(exc), args.json)
        return 3
    gads_utils.emit(result, args.json)
    return 0



if __name__ == "__main__":
    sys.exit(main())
