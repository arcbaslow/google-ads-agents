"""Look up brand catalogue entries. Brand-list exclusion writes are unavailable."""

from __future__ import annotations

import argparse
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
    raise NotImplementedError(
        "Brand exclusions require a BRANDS shared set and a campaign brand_list "
        "criterion. This writer is unavailable; no exclusion was sent."
    )


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("suggest", help="Search the brand catalogue by name prefix")
    s.add_argument("--query", nargs="+", required=True, help="One or more brand names to look up")

    e = sub.add_parser("exclude", help="Unsupported brand-list write")
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

    if args.action == "suggest":
        try:
            data = suggest(cid, args.query)
        except Exception as ex:
            gads_utils.emit({"status": "api_error", "error": str(ex)}, args.json)
            return 3
        gads_utils.emit(data, args.json)
        return 0

    try:
        exclude(cid, [], [], validate_only=not args.apply)
    except NotImplementedError as exc:
        gads_utils.emit({"status": "unsupported", "error": str(exc)}, args.json)
        return 2



if __name__ == "__main__":
    sys.exit(main())
