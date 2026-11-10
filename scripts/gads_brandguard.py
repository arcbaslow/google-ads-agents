"""Classify brand campaigns and the recommendations that would scale them.

Brand Search campaigns report the best CPA and ROAS in most accounts because
they intercept users who were already looking for the advertiser. Those
numbers are mostly not incremental, so any read adapter that could lead to
"raise the budget" or "loosen the target" on a brand campaign tags it here
and the agents hold that step until the owner asks for it explicitly.

Two signals, either one is enough:

  - campaign name matches a pattern in `brand_rules.json`
  - the campaign's share of clicks on search terms containing one of the
    customer's brand terms is at or above `brand_share_threshold`

The share needs `brand_terms` for the customer ID in the rules file; without
them no search-terms query is sent. The query result is cached for the
usual 15 minutes so pacing and recommendations share one request.

The rules file is conservative and editable; add a client's brand terms
there rather than hard-coding them in an agent. Brand terms are matched
against search terms only, not campaign names, because many accounts put
the client name in every campaign.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import gads_utils

DEFAULT_RULES = Path(__file__).parent / "brand_rules.json"
DEFAULT_THRESHOLD = 0.7

HOLD_REASON = (
    "Brand campaign: CPA and ROAS here are mostly non-incremental, so they do "
    "not justify more spend on their own. Held unless the owner explicitly "
    "asks to scale brand."
)

SEARCH_TERMS_QUERY = """
    SELECT
      campaign.id,
      search_term_view.search_term,
      metrics.clicks
    FROM search_term_view
    WHERE segments.date BETWEEN '{start}' AND '{end}'
      AND metrics.clicks > 0
"""


def load_rules(path: Path | None = None) -> dict:
    data = json.loads((path or DEFAULT_RULES).read_text(encoding="utf-8"))
    terms = {
        gads_utils.normalize_customer_id(cid): [t.lower() for t in values if t]
        for cid, values in (data.get("brand_terms") or {}).items()
    }
    return {
        "patterns": [re.compile(p) for p in data.get("campaign_name_patterns", [])],
        "spend_expanding": set(data.get("spend_expanding_recommendation_types", [])),
        "brand_terms": terms,
        "threshold": float(data.get("brand_share_threshold", DEFAULT_THRESHOLD)),
    }


def is_brand_campaign(name: str | None, rules: dict) -> bool:
    if not name:
        return False
    return any(p.search(name) for p in rules["patterns"])


def is_spend_expanding(recommendation_type: str | None, rules: dict) -> bool:
    return (recommendation_type or "") in rules["spend_expanding"]


def brand_terms_for(customer_id: str, rules: dict) -> list[str]:
    return rules["brand_terms"].get(gads_utils.normalize_customer_id(customer_id), [])


def brand_shares(customer_id: str, rules: dict, days: int = 28) -> dict[str, dict]:
    """Per-campaign share of clicks on brand search terms, keyed by campaign ID.

    Returns {} when the customer has no brand terms configured, without
    sending a query.
    """
    import gads_client

    customer_id = gads_utils.normalize_customer_id(customer_id)
    terms = brand_terms_for(customer_id, rules)
    if not terms:
        return {}
    start, end = gads_utils.date_range(days)
    cache_key = ["brand_shares", customer_id, start, end, ",".join(sorted(terms))]
    cached = gads_utils.cache_get(cache_key)
    if cached is not None:
        return cached

    rows = gads_client.search_stream(customer_id, SEARCH_TERMS_QUERY.format(start=start, end=end))
    totals: dict[str, dict] = {}
    for row in rows:
        cid_ = str(row.get("campaign", {}).get("id") or "")
        if not cid_:
            continue
        clicks = int(row.get("metrics", {}).get("clicks", 0) or 0)
        term = (row.get("search_term_view", {}).get("search_term") or "").lower()
        entry = totals.setdefault(cid_, {"clicks": 0, "brand_clicks": 0})
        entry["clicks"] += clicks
        if any(t in term for t in terms):
            entry["brand_clicks"] += clicks
    shares = {
        cid_: {**e, "share": round(e["brand_clicks"] / e["clicks"], 3)}
        for cid_, e in totals.items() if e["clicks"] > 0
    }
    gads_utils.cache_set(cache_key, shares)
    return shares


def classify(name: str | None, campaign_id: str | None, shares: dict[str, dict], rules: dict) -> dict:
    """Return brand, brand_share and brand_reason for one campaign."""
    share_entry = shares.get(str(campaign_id or ""))
    share = share_entry["share"] if share_entry else None
    if is_brand_campaign(name, rules):
        reason = "name"
    elif share is not None and share >= rules["threshold"]:
        reason = "search_terms"
    else:
        reason = None
    return {"brand": reason is not None, "brand_share": share, "brand_reason": reason}
