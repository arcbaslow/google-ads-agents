"""Keyword research via KeywordPlanIdeaService."""

from __future__ import annotations

import argparse
import sys

import gads_client
import gads_utils


def keyword_ideas(customer_id: str, seeds: list[str], language: str = "en", geo: str = "US") -> dict:
    client = gads_client.build_client()
    svc = client.get_service("KeywordPlanIdeaService")
    constants = client.get_service("GoogleAdsService")

    # Language and geo are constants; the IDs below are common ones.
    language_id = {"en": "1000", "es": "1003", "de": "1001", "fr": "1002"}.get(language, "1000")
    geo_id = {"US": "2840", "GB": "2826", "CA": "2124", "AU": "2036"}.get(geo, "2840")

    req = client.get_type("GenerateKeywordIdeasRequest")
    req.customer_id = customer_id
    req.language = constants.language_constant_path(language_id)
    req.geo_target_constants.append(constants.geo_target_constant_path(geo_id))
    req.keyword_seed.keywords.extend(seeds)
    req.include_adult_keywords = False

    response = svc.generate_keyword_ideas(request=req)
    ideas = []
    for idea in response:
        ideas.append({
            "text": idea.text,
            "avg_monthly_searches": idea.keyword_idea_metrics.avg_monthly_searches,
            "competition": idea.keyword_idea_metrics.competition.name,
            "low_top_of_page_bid": gads_utils.micros_to_currency(
                idea.keyword_idea_metrics.low_top_of_page_bid_micros
            ),
            "high_top_of_page_bid": gads_utils.micros_to_currency(
                idea.keyword_idea_metrics.high_top_of_page_bid_micros
            ),
        })
    ideas.sort(key=lambda x: x["avg_monthly_searches"] or 0, reverse=True)
    return {"seeds": seeds, "language": language, "geo": geo, "ideas": ideas}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--seeds", nargs="+", required=True)
    p.add_argument("--language", default="en")
    p.add_argument("--geo", default="US")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)
    gads_utils.emit(keyword_ideas(cid, args.seeds, args.language, args.geo), args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
