"""Campaign planning and reviewed, bounded campaign writes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from urllib.parse import urlsplit

import gads_utils


def _exact_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} must contain exactly the documented fields")


def _customer_id(customer_id):
    if not isinstance(customer_id, str):
        raise ValueError("Customer ID must be numeric")
    cid = gads_utils.normalize_customer_id(customer_id)
    if not cid.isascii() or not cid.isdigit():
        raise ValueError("Customer ID must be numeric")
    return cid


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\x00\n\r"):
        raise ValueError(f"{label} must be non-empty text without control characters")


def _positive_micros(value, label):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError(f"{label} must be a positive integer below 2**63")


def _numeric_ids(value, label, minimum, maximum):
    if (not isinstance(value, list) or not minimum <= len(value) <= maximum
            or any(not isinstance(v, str) or not v.isascii() or not v.isdigit() for v in value)):
        raise ValueError(f"Provide {minimum}–{maximum} numeric {label} as strings")


def _creation_fields(customer_id, spec):
    cid = _customer_id(customer_id)
    _text(spec["name"], "Campaign name")
    _positive_micros(spec["budget_micros"], "budget_micros")
    _numeric_ids(spec["geo_target_ids"], "geo target IDs", 1, 100)
    if spec["conversions_confirmed"] is not True:
        raise ValueError("conversions_confirmed must be explicitly true")
    if type(spec["eu_political_advertising"]) is not bool:
        raise ValueError("An explicit boolean EU political advertising declaration is required")
    return cid


def create_search_campaign(customer_id: str, spec: dict, validate_only: bool = True) -> dict:
    """Create a paused Search shell; ads and subsequent activation are separate work."""
    import gads_client
    from gads_mutate import reviewed_atomic_mutate

    expected = {"name", "budget_micros", "bidding", "geo_target_ids", "language_mode",
                "eu_political_advertising", "analytics_confirmed", "conversions_confirmed"}
    _exact_keys(spec, expected, "Search spec")
    cid = _creation_fields(customer_id, spec)
    name = spec["name"]
    amount = spec["budget_micros"]
    if spec["bidding"] != "MAXIMIZE_CONVERSIONS" or spec["language_mode"] != "AUTOMATIC":
        raise ValueError("Only MAXIMIZE_CONVERSIONS and AUTOMATIC language are supported")
    if spec["analytics_confirmed"] is not True:
        raise ValueError("analytics_confirmed must be explicitly true")
    geos = spec["geo_target_ids"]

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

# Source: v25 AssetAutomationTypeEnum.AssetAutomationType docstrings naming Demand Gen ads.
DEMAND_GEN_ASSET_AUTOMATION_TYPES = {
    "VIDEO_RESPONSIVE": (
        "GENERATE_VERTICAL_YOUTUBE_VIDEOS", "GENERATE_SHORTER_YOUTUBE_VIDEOS",
        "GENERATE_LANDING_PAGE_TEXT",
    ),
    "MULTI_ASSET": (
        "GENERATE_DESIGN_VERSIONS_FOR_IMAGES", "GENERATE_VIDEOS_FROM_OTHER_ASSETS",
        "GENERATE_ANIMATED_IMAGES_FROM_OTHER_ASSETS",
    ),
}
DEMAND_GEN_CHANNELS = (
    "youtube_in_stream", "youtube_in_feed", "youtube_shorts", "discover", "gmail", "display", "maps",
)
APP_GOAL_STRATEGIES = {
    "OPTIMIZE_INSTALLS_TARGET_INSTALL_COST": "target_cpa",
    "OPTIMIZE_INSTALLS_WITHOUT_TARGET_INSTALL_COST": "maximize_conversions",
    "OPTIMIZE_IN_APP_CONVERSIONS_TARGET_INSTALL_COST": "target_cpa",
    "OPTIMIZE_IN_APP_CONVERSIONS_TARGET_CONVERSION_COST": "target_cpa",
    "OPTIMIZE_IN_APP_CONVERSIONS_WITHOUT_TARGET_CPA": "maximize_conversions",
    "OPTIMIZE_RETURN_ON_ADVERTISING_SPEND": "target_roas",
    "OPTIMIZE_TOTAL_VALUE_WITHOUT_TARGET_ROAS": "maximize_conversion_value",
}


def _choice(value, choices, label):
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{label} must be one of {', '.join(choices)}")


def _targets(spec, target):
    for field in ("target_cpa_micros", "target_roas"):
        value = spec[field]
        if field != target:
            if value is not None:
                raise ValueError(f"{field} must be null for this strategy")
        elif field == "target_cpa_micros":
            _positive_micros(value, field)
        elif (type(value) not in (int, float) or not 0 < value <= sys.float_info.max):
            raise ValueError("target_roas must be a finite positive number")


def _resource_list(value, cid, resource, label, required=False):
    if value is None and not required:
        return []
    if (not isinstance(value, list) or (required and not value)
            or any(not isinstance(v, str)
                   or re.fullmatch(rf"customers/{cid}/{resource}/[0-9]+", v) is None for v in value)):
        raise ValueError(f"{label} must contain existing {resource} resource names for customer {cid}")
    return value


def _text_assets(value, label):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty text list")
    for text in value:
        _text(text, label)
    return [{"text": text} for text in value]


def _demand_gen_ad(ad, cid):
    if not isinstance(ad, dict):
        raise ValueError("ad must be an object")
    _choice(ad.get("type"), ("MULTI_ASSET", "VIDEO_RESPONSIVE"), "ad.type")
    common = {"type", "final_url", "business_name", "headlines", "descriptions", "logo_images"}
    multi = ad["type"] == "MULTI_ASSET"
    _exact_keys(ad, common | ({"marketing_images", "square_marketing_images"} if multi
                             else {"videos", "long_headlines"}), "Demand Gen ad")
    _text(ad["final_url"], "final_url")
    url = urlsplit(ad["final_url"])
    if url.scheme not in ("http", "https") or not url.netloc or any(c.isspace() for c in ad["final_url"]):
        raise ValueError("final_url must be an absolute HTTP(S) URL")
    _text(ad["business_name"], "business_name")
    info = {key: _text_assets(ad[key], key) for key in ("headlines", "descriptions")}
    info["business_name"] = ad["business_name"] if multi else {"text": ad["business_name"]}
    fields = ("marketing_images", "square_marketing_images", "logo_images") if multi else ("videos", "logo_images")
    for field in fields:
        assets = _resource_list(ad[field], cid, "assets", field, required=field in ("videos", "logo_images"))
        info[field] = [{"asset": asset} for asset in assets]
    if multi and not (info["marketing_images"] or info["square_marketing_images"]):
        raise ValueError("At least one marketing_images or square_marketing_images asset is required")
    if not multi:
        info["long_headlines"] = _text_assets(ad["long_headlines"], "long_headlines")
    kind = "demand_gen_multi_asset_ad" if multi else "demand_gen_video_responsive_ad"
    return {"final_urls": [ad["final_url"]], kind: info}


def _app_ad(ad, cid, engagement):
    _exact_keys(ad, {"headlines", "descriptions", "images", "youtube_videos"}, "App ad")
    info = {key: _text_assets(ad[key], key) for key in ("headlines", "descriptions")}
    for field in ("images", "youtube_videos"):
        destination = "videos" if engagement and field == "youtube_videos" else field
        info[destination] = [{"asset": asset} for asset in _resource_list(ad[field], cid, "assets", field)]
    return {"app_engagement_ad" if engagement else "app_ad": info}


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{label} must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label} must be a valid calendar date") from None


def _create_with_ad(cid, spec, budget_fields, campaign_fields, ad_group_fields, ad_fields,
                    ad_group_targeting, automation, validate_only, user_list=None):
    import gads_client
    from gads_mutate import reviewed_atomic_mutate

    client = gads_client.build_client()
    budget_name = f"customers/{cid}/campaignBudgets/-1"
    campaign_name = f"customers/{cid}/campaigns/-2"
    group_name = f"customers/{cid}/adGroups/-3"
    operations = []

    def create(kind, fields):
        op = client.get_type("MutateOperation")
        getattr(op, kind + "_operation").create = fields
        operations.append(op)

    create("campaign_budget", {
        "resource_name": budget_name, "name": spec["name"] + " budget",
        "delivery_method": "STANDARD", "explicitly_shared": False, **budget_fields,
    })
    create("campaign", {
        "resource_name": campaign_name, "name": spec["name"], "status": "PAUSED",
        "campaign_budget": budget_name,
        "contains_eu_political_advertising": (
            "CONTAINS_EU_POLITICAL_ADVERTISING" if spec["eu_political_advertising"]
            else "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"),
        **campaign_fields,
    })
    create("ad_group", {
        "resource_name": group_name, "campaign": campaign_name,
        "name": spec["name"] + " ad group", "status": "ENABLED", **ad_group_fields,
    })
    for field, ids, constant in (
        ("location", spec["geo_target_ids"], "geoTargetConstants"),
        ("language", spec["language_ids"], "languageConstants"),
    ):
        for value in sorted(set(ids)):
            parent = "ad_group" if ad_group_targeting else "campaign"
            create(parent + "_criterion", {
                parent: group_name if ad_group_targeting else campaign_name,
                field: {"geo_target_constant" if field == "location" else "language_constant":
                        f"{constant}/{value}"},
            })
    if user_list:
        create("ad_group_criterion", {"ad_group": group_name, "user_list": {"user_list": user_list}})
    create("ad_group_ad", {
        "ad_group": group_name, "status": "ENABLED",
        "ad": ad_fields,
        "ad_group_ad_asset_automation_settings": automation,
    })
    response = reviewed_atomic_mutate(client, cid, operations, validate_only)
    return {"status": "validated" if validate_only else "applied", "customer_id": cid,
            "response": gads_client._msg_to_dict(response._pb),
            "limitations": ["PAUSED campaign, one ad group and one ad; no activation or edits after creation.",
                            "Existing assets only; server validation determines eligibility and asset limits.",
                            "No idempotency guarantee: inspect account state before retrying an uncertain write."]}


def create_demand_gen_campaign(customer_id: str, spec: dict, validate_only: bool = True) -> dict:
    _exact_keys(spec, {"name", "budget_micros", "budget_period", "start_date", "end_date", "bidding",
                       "target_cpa_micros", "target_roas", "geo_target_ids", "language_ids",
                       "channel_controls", "asset_automation", "ad", "eu_political_advertising",
                       "conversions_confirmed"}, "Demand Gen spec")
    cid = _creation_fields(customer_id, spec)
    _numeric_ids(spec["language_ids"], "language IDs", 0, 50)
    _choice(spec["budget_period"], ("DAILY", "CAMPAIGN_TOTAL"), "budget_period")
    if spec["budget_period"] == "DAILY":
        if spec["start_date"] is not None or spec["end_date"] is not None:
            raise ValueError("start_date and end_date must be null for a DAILY budget")
        budget, schedule = {"amount_micros": spec["budget_micros"]}, {}
    else:
        start, end = _date(spec["start_date"], "start_date"), _date(spec["end_date"], "end_date")
        if end < start:
            raise ValueError("end_date must not be before start_date")
        # A campaign-total budget spends over the campaign's own start and end dates.
        budget = {"total_amount_micros": spec["budget_micros"], "period": "CUSTOM_PERIOD"}
        schedule = {"start_date_time": f"{start} 00:00:00", "end_date_time": f"{end} 23:59:59"}
    _choice(spec["bidding"], ("MAXIMIZE_CLICKS", "MAXIMIZE_CONVERSIONS", "TARGET_CPA", "TARGET_ROAS"), "bidding")
    target = {"TARGET_CPA": "target_cpa_micros", "TARGET_ROAS": "target_roas"}.get(spec["bidding"])
    _targets(spec, target)
    strategy = {"MAXIMIZE_CLICKS": "target_spend", "MAXIMIZE_CONVERSIONS": "maximize_conversions",
                "TARGET_CPA": "maximize_conversions", "TARGET_ROAS": "maximize_conversion_value"}[spec["bidding"]]
    channels = spec["channel_controls"]
    if channels == "ALL_CHANNELS":
        controls = {"channel_strategy": "ALL_CHANNELS"}
    else:
        _exact_keys(channels, DEMAND_GEN_CHANNELS, "channel_controls")
        if any(type(v) is not bool for v in channels.values()) or not any(channels.values()):
            raise ValueError("channel_controls requires boolean flags with at least one true")
        controls = {"selected_channels": dict(channels)}
    ad = _demand_gen_ad(spec["ad"], cid)
    automation_types = DEMAND_GEN_ASSET_AUTOMATION_TYPES[spec["ad"]["type"]]
    _exact_keys(spec["asset_automation"], automation_types, "asset_automation")
    automation = []
    for kind in automation_types:
        status = spec["asset_automation"][kind]
        _choice(status, ("OPTED_IN", "OPTED_OUT"), kind)
        automation.append({"asset_automation_type": kind, "asset_automation_status": status})
    return _create_with_ad(cid, spec, budget, {
        "advertising_channel_type": "DEMAND_GEN",
        "demand_gen_campaign_settings": {"upgraded_targeting": True},
        strategy: {target: spec[target]} if target else {},
        **schedule,
    }, {"demand_gen_ad_group_settings": {"channel_controls": controls}}, ad, True, automation, validate_only)


def create_app_campaign(customer_id: str, spec: dict, validate_only: bool = True) -> dict:
    _exact_keys(spec, {"name", "sub_type", "app_id", "app_store", "goal_type", "target_cpa_micros",
                       "target_roas", "budget_micros", "geo_target_ids", "language_ids",
                       "selective_optimization_conversion_actions", "user_list", "ad",
                       "eu_political_advertising", "conversions_confirmed"}, "App spec")
    cid = _creation_fields(customer_id, spec)
    _numeric_ids(spec["language_ids"], "language IDs", 0, 50)
    _choice(spec["sub_type"], ("APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT"), "sub_type")
    _choice(spec["app_store"], ("GOOGLE_APP_STORE", "APPLE_APP_STORE"), "app_store")
    _text(spec["app_id"], "app_id")
    _choice(spec["goal_type"], APP_GOAL_STRATEGIES, "goal_type")
    goal = spec["goal_type"]
    engagement = spec["sub_type"] == "APP_CAMPAIGN_FOR_ENGAGEMENT"
    if engagement and (goal.startswith("OPTIMIZE_INSTALLS_") or goal.endswith("_TARGET_INSTALL_COST")):
        raise ValueError("Engagement campaigns optimize in-app actions or value, not installs")
    strategy = APP_GOAL_STRATEGIES[goal]
    target = {"target_cpa": "target_cpa_micros", "target_roas": "target_roas"}.get(strategy)
    _targets(spec, target)
    required = engagement or not goal.startswith("OPTIMIZE_INSTALLS_")
    actions = spec["selective_optimization_conversion_actions"]
    if not isinstance(actions, list):
        raise ValueError("selective_optimization_conversion_actions must be a list")
    _resource_list(actions, cid, "conversionActions", "selective_optimization_conversion_actions", required)
    # Engagement ad groups must target one audience (the Firebase all-users list
    # qualifies); without a deep link the ad opens the app's main screen.
    if engagement:
        _resource_list([spec["user_list"]], cid, "userLists", "user_list", True)
    elif spec["user_list"] is not None:
        raise ValueError("user_list must be null for APP_CAMPAIGN")
    ad = _app_ad(spec["ad"], cid, engagement)
    return _create_with_ad(cid, spec, {"amount_micros": spec["budget_micros"]}, {
        "advertising_channel_type": "MULTI_CHANNEL", "advertising_channel_sub_type": spec["sub_type"],
        "app_campaign_setting": {"app_id": spec["app_id"], "app_store": spec["app_store"],
                                 "bidding_strategy_goal_type": goal},
        "selective_optimization": {"conversion_actions": actions},
        strategy: {target: spec[target]} if target else {},
    }, {}, ad, False, [], validate_only, user_list=spec["user_list"])


APP_TARGET_QUERY = """
SELECT campaign.id, campaign.resource_name, campaign.advertising_channel_type,
       campaign.status, campaign.app_campaign_setting.bidding_strategy_goal_type,
       campaign.bidding_strategy_type, campaign.bidding_strategy,
       campaign.target_cpa.target_cpa_micros, campaign.target_roas.target_roas
FROM campaign
WHERE campaign.id = {campaign_id}
"""


def update_app_target(customer_id: str, spec: dict, validate_only: bool = True) -> dict:
    import gads_client
    from gads_mutate import reviewed_mutate

    _exact_keys(spec, {"campaign_id", "target_cpa_micros", "target_roas"}, "App target")
    cid = _customer_id(customer_id)
    _numeric_ids([spec["campaign_id"]], "campaign ID", 1, 1)
    targets = [key for key in ("target_cpa_micros", "target_roas") if spec[key] is not None]
    if len(targets) != 1:
        raise ValueError("Exactly one App target must be non-null")
    target = targets[0]
    _targets(spec, target)
    strategy = "target_cpa" if target == "target_cpa_micros" else "target_roas"
    client = gads_client.build_client()
    rows = list(client.get_service("GoogleAdsService").search(
        customer_id=cid, query=APP_TARGET_QUERY.format(campaign_id=spec["campaign_id"])))
    if len(rows) != 1:
        raise ValueError("App target requires exactly one existing campaign")
    campaign = rows[0].campaign
    goal = campaign.app_campaign_setting.bidding_strategy_goal_type.name
    if campaign.advertising_channel_type.name != "MULTI_CHANNEL" or campaign.status.name == "REMOVED":
        raise ValueError(f"App target requires a non-REMOVED MULTI_CHANNEL campaign; goal is {goal}")
    if APP_GOAL_STRATEGIES.get(goal) != strategy:
        raise ValueError(f"Goal {goal} does not support a {strategy} edit")
    # Writing a target onto a different scheme would switch the campaign's bidding.
    current = campaign.bidding_strategy_type.name
    if current != strategy.upper() or campaign.bidding_strategy:
        raise ValueError(f"Campaign bidding is {current}; only an existing standard {strategy} is editable")
    previous = getattr(getattr(campaign, strategy), target)
    operation = client.get_type("CampaignOperation")
    operation.update = {"resource_name": f"customers/{cid}/campaigns/{spec['campaign_id']}",
                        strategy: {target: spec[target]}}
    operation.update_mask.paths.append(f"{strategy}.{target}")
    response = reviewed_mutate(client.get_service("CampaignService").mutate_campaigns,
                               customer_id=cid, operations=[operation], validate_only=validate_only)
    return {"status": "validated" if validate_only else "applied", "customer_id": cid,
            "campaign_id": spec["campaign_id"], "field": f"{strategy}.{target}",
            "previous_value": previous, "new_value": spec[target],
            "response": gads_client._msg_to_dict(response._pb),
            "limitations": ["Only an existing App CPA or ROAS target is editable; the bidding goal is unchanged.",
                            "Read and update are not locked; inspect account state after an uncertain response."]}


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
    source.add_argument("--demand-gen-spec", help="Strict JSON spec for a PAUSED Demand Gen campaign")
    source.add_argument("--app-spec", help="Strict JSON spec for a PAUSED App campaign")
    source.add_argument("--app-target", help="Strict JSON spec for an existing App CPA or ROAS target")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true", help="Review and validate a strict spec only")
    mode.add_argument("--apply", action="store_true", help="Review, validate and apply a strict spec")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    writers = ((args.search_spec, create_search_campaign),
               (args.demand_gen_spec, create_demand_gen_campaign),
               (args.app_spec, create_app_campaign), (args.app_target, update_app_target))
    selected = next(((path, writer) for path, writer in writers if path), None)
    if selected:
        if not (args.validate_only or args.apply):
            gads_utils.emit({"status": "no_op", "hint": "Choose --validate-only or --apply"}, args.json)
            return 0
        import gads_errors
        try:
            path, writer = selected
            with open(path, encoding="utf-8") as f:
                spec = json.load(f)
            result = writer(cid, spec, validate_only=not args.apply)
        except Exception as exc:
            failure = gads_errors.describe(exc)
            # Spec checks raise plain ValueError with our own text naming the field.
            if type(exc) is ValueError:
                failure["error"] = str(exc)
            gads_utils.emit(failure, args.json)
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
