"""Classify brand campaigns and the recommendations that would scale them.

Brand Search campaigns report the best CPA and ROAS in most accounts because
they intercept users who were already looking for the advertiser. Those
numbers are mostly not incremental, so any read adapter that could lead to
"raise the budget" or "loosen the target" on a brand campaign tags it here
and the agents hold that step until the owner asks for it explicitly.

Classification is by campaign name against `brand_rules.json`. The file is
conservative and editable; add a client's brand terms there rather than
hard-coding them in an agent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_RULES = Path(__file__).parent / "brand_rules.json"

HOLD_REASON = (
    "Brand campaign: CPA and ROAS here are mostly non-incremental, so they do "
    "not justify more spend on their own. Held unless the owner explicitly "
    "asks to scale brand."
)


def load_rules(path: Path = DEFAULT_RULES) -> dict:
    data = json.loads(path.read_text())
    return {
        "patterns": [re.compile(p) for p in data.get("campaign_name_patterns", [])],
        "spend_expanding": set(data.get("spend_expanding_recommendation_types", [])),
    }


def is_brand_campaign(name: str | None, rules: dict) -> bool:
    if not name:
        return False
    return any(p.search(name) for p in rules["patterns"])


def is_spend_expanding(recommendation_type: str | None, rules: dict) -> bool:
    return (recommendation_type or "") in rules["spend_expanding"]
