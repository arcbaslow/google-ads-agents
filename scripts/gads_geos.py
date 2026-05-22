"""Geo target lookup.

Maps free-text location queries ("California", "London", "Bavaria") to
Google Ads GeoTargetConstant IDs, which is what the creation wizard
and campaign mutates actually need.

Backed by GeoTargetConstantService.suggest_geo_target_constants — the
same source the Google Ads UI uses.
"""

from __future__ import annotations

import argparse
import sys

import gads_utils


def suggest(customer_id: str, queries: list[str], locale: str = "en",
            country_code: str = "US") -> dict:
    import gads_client

    client = gads_client.build_client()
    svc = client.get_service("GeoTargetConstantService")

    req = client.get_type("SuggestGeoTargetConstantsRequest")
    req.locale = locale
    req.country_code = country_code
    req.location_names.names.extend(queries)

    resp = svc.suggest_geo_target_constants(request=req)
    rows = []
    for s in resp.geo_target_constant_suggestions:
        gtc = s.geo_target_constant
        rows.append({
            "query": s.search_term,
            "id": gtc.id,
            "name": gtc.name,
            "canonical_name": gtc.canonical_name,
            "country_code": gtc.country_code,
            "target_type": gtc.target_type,
            "reach": getattr(s, "reach", None),
            "locale": getattr(s, "locale", None),
        })
    return {
        "queries": queries,
        "locale": locale,
        "country_code": country_code,
        "results": rows,
        "summary": f"{len(rows)} geo match(es)",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--query", nargs="+", required=True, help="One or more location names")
    p.add_argument("--locale", default="en")
    p.add_argument("--country", default="US",
                   help="ISO country code to bias suggestions (default US)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    try:
        data = suggest(cid, args.query, args.locale, args.country)
    except Exception as ex:
        gads_utils.emit({"status": "api_error", "error": str(ex)}, args.json)
        return 3
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
