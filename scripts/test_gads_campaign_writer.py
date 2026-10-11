import copy
import re
from unittest.mock import Mock

import gads_client
import gads_creation
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials

SPEC = {"name": "Reviewed campaign", "budget_micros": 50000000,
        "bidding": "MAXIMIZE_CONVERSIONS", "geo_target_ids": ["2840"],
        "language_mode": "AUTOMATIC", "eu_political_advertising": False,
        "analytics_confirmed": True, "conversions_confirmed": True}


@pytest.fixture
def service(monkeypatch):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), version="v25", use_proto_plus=True)
    service = Mock()
    service.mutate.return_value = types.get_type("MutateGoogleAdsResponse")
    client = Mock(get_type=types.get_type)
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", Mock(return_value=client))
    return service


@pytest.mark.parametrize("dry", [True, False])
def test_search_writer_validates_atomic_paused_request(service, monkeypatch, capsys, dry):
    def approve():
        assert not service.mutate.called
        preview = capsys.readouterr().err
        assert '"PAUSED"' in preview and '"amount_micros": "50000000"' in preview
        return "y"

    monkeypatch.setattr("builtins.input", approve)
    gads_creation.create_search_campaign("123", SPEC, dry)
    assert [c.kwargs["validate_only"] for c in service.mutate.call_args_list] == ([True] if dry else [True, False])
    for call in service.mutate.call_args_list:
        assert call.kwargs["partial_failure"] is False
        assert call.kwargs["retry"] is None
        ops = call.kwargs["mutate_operations"]
        campaign = ops[1].campaign_operation.create
        assert campaign.status.name == "PAUSED"
        assert campaign._pb.WhichOneof("campaign_bidding_strategy") == "maximize_conversions"
        assert campaign.campaign_budget == ops[0].campaign_budget_operation.create.resource_name
        assert ops[2].campaign_criterion_operation.create.campaign == campaign.resource_name
        assert ops[2].campaign_criterion_operation.create.location.geo_target_constant == "geoTargetConstants/2840"
        assert campaign.contains_eu_political_advertising.name == "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"


@pytest.mark.parametrize("answer", ["n", "", "yes"])
def test_search_writer_cancellation_sends_nothing(service, monkeypatch, answer):
    monkeypatch.setattr("builtins.input", lambda: answer)
    with pytest.raises(RuntimeError):
        gads_creation.create_search_campaign("123", SPEC, False)
    service.mutate.assert_not_called()


def test_search_validation_failure_cannot_leave_budget(service, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "y")
    service.mutate.side_effect = ValueError("validation failed")
    with pytest.raises(ValueError):
        gads_creation.create_search_campaign("123", SPEC, False)
    assert service.mutate.call_count == 1
    assert service.mutate.call_args.kwargs["validate_only"] is True


@pytest.mark.parametrize("key,value", [("budget_micros", -1), ("budget_micros", True),
    ("bidding", "TARGET_ROAS"), ("language_mode", "en"), ("analytics_confirmed", "true"),
    ("geo_target_ids", []), ("geo_target_ids", ["US"]), ("eu_political_advertising", None),
    ("status", "ENABLED")])
def test_unsupported_spec_rejected_before_credentials(monkeypatch, key, value):
    spec = copy.deepcopy(SPEC)
    spec[key] = value
    build = Mock()
    monkeypatch.setattr(gads_client, "build_client", build)
    with pytest.raises(ValueError):
        gads_creation.create_search_campaign("123", spec, False)
    build.assert_not_called()


DG_SPEC = {
    "name": "Demand Gen", "budget_micros": 50000000, "budget_period": "DAILY",
    "start_date": None, "end_date": None, "bidding": "MAXIMIZE_CONVERSIONS",
    "target_cpa_micros": None, "target_roas": None, "geo_target_ids": ["2840"],
    "language_ids": ["1000"], "channel_controls": "ALL_CHANNELS",
    "asset_automation": {kind: "OPTED_OUT" for kind in gads_creation.DEMAND_GEN_ASSET_AUTOMATION_TYPES["MULTI_ASSET"]},
    "ad": {"type": "MULTI_ASSET", "final_url": "https://example.com", "business_name": "Example",
           "headlines": ["Headline"], "descriptions": ["Description"],
           "marketing_images": ["customers/123/assets/10"], "square_marketing_images": None,
           "logo_images": ["customers/123/assets/11"]},
    "eu_political_advertising": False, "conversions_confirmed": True,
}
VIDEO_AD = {
    "type": "VIDEO_RESPONSIVE", "final_url": "https://example.com", "business_name": "Example",
    "headlines": ["Headline"], "long_headlines": ["Long headline"], "descriptions": ["Description"],
    "videos": ["customers/123/assets/12"], "logo_images": ["customers/123/assets/11"],
}
APP_SPEC = {
    "name": "App", "sub_type": "APP_CAMPAIGN", "app_id": "com.example.app",
    "app_store": "GOOGLE_APP_STORE", "goal_type": "OPTIMIZE_INSTALLS_TARGET_INSTALL_COST",
    "target_cpa_micros": 1000000, "target_roas": None, "budget_micros": 50000000,
    "geo_target_ids": ["2840"], "language_ids": ["1000"],
    "selective_optimization_conversion_actions": [], "user_list": None,
    "ad": {"headlines": ["Install now"], "descriptions": ["Try our app"],
           "images": ["customers/123/assets/10"], "youtube_videos": ["customers/123/assets/12"]},
    "eu_political_advertising": True, "conversions_confirmed": True,
}
TARGET_SPEC = {"campaign_id": "42", "target_cpa_micros": 2000000, "target_roas": None}
WRITERS = [(gads_creation.create_demand_gen_campaign, DG_SPEC), (gads_creation.create_app_campaign, APP_SPEC)]


@pytest.fixture
def api(monkeypatch):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), version="v25", use_proto_plus=True)
    ads, campaigns = Mock(), Mock()
    ads.mutate.return_value = types.get_type("MutateGoogleAdsResponse")
    campaigns.mutate_campaigns.return_value = types.get_type("MutateCampaignsResponse")
    row = types.get_type("GoogleAdsRow")
    row.campaign = {
        "resource_name": "customers/123/campaigns/42", "id": 42, "status": "PAUSED",
        "advertising_channel_type": "MULTI_CHANNEL",
        "app_campaign_setting": {"bidding_strategy_goal_type": APP_SPEC["goal_type"]},
        "bidding_strategy_type": "TARGET_CPA", "target_cpa": {"target_cpa_micros": 1000000},
    }
    ads.search.return_value = [row]
    client = Mock(get_type=types.get_type)
    client.get_service.side_effect = {"GoogleAdsService": ads, "CampaignService": campaigns}.__getitem__
    monkeypatch.setattr(gads_client, "build_client", Mock(return_value=client))
    monkeypatch.setattr("builtins.input", lambda: "y")
    return ads, campaigns, row


def test_automation_contract_matches_installed_enum_docstrings():
    from google.ads.googleads.v25.enums.types.asset_automation_type import AssetAutomationTypeEnum

    doc = AssetAutomationTypeEnum.AssetAutomationType.__doc__
    entries = re.findall(r"            ([A-Z_]+) \(\d+\):(.*?)(?=\n            [A-Z_]+ \(|\Z)", doc, re.S)
    derived = {
        ad_type: {name for name, description in entries if info_type in description}
        for ad_type, info_type in {
            "VIDEO_RESPONSIVE": "DemandGenVideoResponsiveAdInfo",
            "MULTI_ASSET": "DemandGenMultiAssetAd",
        }.items()
    }
    assert derived == {ad_type: set(kinds) for ad_type, kinds in gads_creation.DEMAND_GEN_ASSET_AUTOMATION_TYPES.items()}
    assert all("GENERATE_LANDING_PAGE_PREVIEW" not in kinds for kinds in derived.values())


@pytest.mark.parametrize("writer,base", WRITERS)
@pytest.mark.parametrize("dry", [True, False])
def test_creation_operation_order_and_gate(api, writer, base, dry, capsys):
    ads, campaigns, _ = api
    result = writer("1-23", copy.deepcopy(base), dry)
    assert result == {"status": "validated" if dry else "applied", "customer_id": "123",
                      "response": {}, "limitations": result["limitations"]}
    assert '"PAUSED"' in capsys.readouterr().err
    assert [c.kwargs["validate_only"] for c in ads.mutate.call_args_list] == ([True] if dry else [True, False])
    campaigns.mutate_campaigns.assert_not_called()
    dg = base is DG_SPEC
    criterion_kind = "ad_group_criterion_operation" if dg else "campaign_criterion_operation"
    for call in ads.mutate.call_args_list:
        assert call.kwargs["customer_id"] == "123"
        assert call.kwargs["partial_failure"] is False
        assert call.kwargs["retry"] is None
        ops = call.kwargs["mutate_operations"]
        assert [op._pb.WhichOneof("operation") for op in ops] == [
            "campaign_budget_operation", "campaign_operation", "ad_group_operation",
            criterion_kind, criterion_kind, "ad_group_ad_operation",
        ]
        budget = ops[0].campaign_budget_operation.create
        campaign = ops[1].campaign_operation.create
        group = ops[2].ad_group_operation.create
        ad = ops[-1].ad_group_ad_operation.create
        assert budget.resource_name == "customers/123/campaignBudgets/-1"
        assert budget.amount_micros == base["budget_micros"]
        assert budget.explicitly_shared is False and budget._pb.HasField("explicitly_shared")
        assert budget.delivery_method.name == "STANDARD"
        assert campaign.resource_name == "customers/123/campaigns/-2"
        assert campaign.campaign_budget == budget.resource_name
        assert campaign.status.name == "PAUSED"
        assert not campaign.bidding_strategy
        assert group.resource_name == "customers/123/adGroups/-3"
        assert group.campaign == campaign.resource_name
        assert group.type_.name == "UNSPECIFIED" and group.status.name == "ENABLED"
        assert ad.ad_group == group.resource_name and ad.status.name == "ENABLED"
        assert not ad.ad.resource_name
        assert "resource_name" not in gads_client._msg_to_dict(ad.ad._pb)
        assert campaign.contains_eu_political_advertising.name == (
            "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING" if dg else "CONTAINS_EU_POLITICAL_ADVERTISING")
        for index, field, constant in [(3, "location", "geoTargetConstants/2840"),
                                       (4, "language", "languageConstants/1000")]:
            criterion = getattr(ops[index], criterion_kind).create
            assert not criterion.resource_name
            assert "resource_name" not in gads_client._msg_to_dict(criterion._pb)
            assert getattr(criterion, "ad_group" if dg else "campaign") == (group.resource_name if dg else campaign.resource_name)
            assert getattr(getattr(criterion, field), "geo_target_constant" if field == "location" else "language_constant") == constant
        if dg:
            assert campaign.advertising_channel_type.name == "DEMAND_GEN"
            assert campaign.advertising_channel_sub_type.name == "UNSPECIFIED"
            assert "advertising_channel_sub_type" not in gads_client._msg_to_dict(campaign._pb)
            assert campaign.demand_gen_campaign_settings.upgraded_targeting is True
            assert campaign.demand_gen_campaign_settings._pb.HasField("upgraded_targeting")
        else:
            assert campaign.advertising_channel_type.name == "MULTI_CHANNEL"
            assert campaign.advertising_channel_sub_type.name == "APP_CAMPAIGN"


@pytest.mark.parametrize("bidding,field,target,value", [
    ("MAXIMIZE_CLICKS", "target_spend", None, None),
    ("MAXIMIZE_CONVERSIONS", "maximize_conversions", None, None),
    ("TARGET_CPA", "maximize_conversions", "target_cpa_micros", 3000000),
    ("TARGET_ROAS", "maximize_conversion_value", "target_roas", 2.5),
])
def test_demand_gen_bidding(api, bidding, field, target, value):
    spec = copy.deepcopy(DG_SPEC)
    spec["bidding"] = bidding
    if target:
        spec[target] = value
    gads_creation.create_demand_gen_campaign("123", spec)
    campaign = api[0].mutate.call_args.kwargs["mutate_operations"][1].campaign_operation.create
    assert campaign._pb.WhichOneof("campaign_bidding_strategy") == field
    assert gads_client._msg_to_dict(getattr(campaign, field)._pb) == (
        {target: str(value) if target == "target_cpa_micros" else value} if target else {})


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("video", [False, True])
def test_demand_gen_channels_ads_and_automation(api, selected, video):
    spec = copy.deepcopy(DG_SPEC)
    if selected:
        spec["channel_controls"] = {key: key in ("gmail", "maps") for key in gads_creation.DEMAND_GEN_CHANNELS}
    if video:
        spec["ad"] = copy.deepcopy(VIDEO_AD)
    automation_types = gads_creation.DEMAND_GEN_ASSET_AUTOMATION_TYPES[spec["ad"]["type"]]
    spec["asset_automation"] = {key: "OPTED_IN" if i % 2 else "OPTED_OUT"
                                for i, key in enumerate(automation_types)}
    gads_creation.create_demand_gen_campaign("123", spec)
    ops = api[0].mutate.call_args.kwargs["mutate_operations"]
    assert not ops[1].campaign_operation.create.asset_automation_settings
    controls = ops[2].ad_group_operation.create.demand_gen_ad_group_settings.channel_controls
    assert controls.channel_config.name == "UNSPECIFIED"
    assert controls._pb.WhichOneof("channel_configuration") == ("selected_channels" if selected else "channel_strategy")
    if selected:
        for key, value in spec["channel_controls"].items():
            assert getattr(controls.selected_channels, key) is value
    else:
        assert controls.channel_strategy.name == "ALL_CHANNELS"
    aga = ops[-1].ad_group_ad_operation.create
    assert len(aga.ad_group_ad_asset_automation_settings) == 3
    assert {item.asset_automation_type.name: item.asset_automation_status.name
            for item in aga.ad_group_ad_asset_automation_settings} == spec["asset_automation"]
    assert list(aga.ad.final_urls) == [spec["ad"]["final_url"]]
    info = aga.ad.demand_gen_video_responsive_ad if video else aga.ad.demand_gen_multi_asset_ad
    assert info.headlines[0].text == "Headline"
    assert info.descriptions[0].text == "Description"
    assert info.logo_images[0].asset == "customers/123/assets/11"
    if video:
        assert info.business_name.text == "Example"
        assert info.long_headlines[0].text == "Long headline"
        assert info.videos[0].asset == "customers/123/assets/12"
    else:
        assert info.business_name == "Example"
        assert info.marketing_images[0].asset == "customers/123/assets/10"


APP_GOALS = [
    ("OPTIMIZE_INSTALLS_TARGET_INSTALL_COST", "target_cpa", False),
    ("OPTIMIZE_INSTALLS_WITHOUT_TARGET_INSTALL_COST", "maximize_conversions", False),
    ("OPTIMIZE_IN_APP_CONVERSIONS_TARGET_INSTALL_COST", "target_cpa", True),
    ("OPTIMIZE_IN_APP_CONVERSIONS_TARGET_CONVERSION_COST", "target_cpa", True),
    ("OPTIMIZE_IN_APP_CONVERSIONS_WITHOUT_TARGET_CPA", "maximize_conversions", True),
    ("OPTIMIZE_RETURN_ON_ADVERTISING_SPEND", "target_roas", True),
    ("OPTIMIZE_TOTAL_VALUE_WITHOUT_TARGET_ROAS", "maximize_conversion_value", True),
]


@pytest.mark.parametrize("goal,strategy,needs_actions", APP_GOALS)
@pytest.mark.parametrize("app_store,app_id", [("GOOGLE_APP_STORE", "com.example.app"), ("APPLE_APP_STORE", "12345")])
def test_app_goals_and_ads(api, goal, strategy, needs_actions, app_store, app_id):
    spec = copy.deepcopy(APP_SPEC)
    spec.update(goal_type=goal, target_cpa_micros=1000000 if strategy == "target_cpa" else None,
                target_roas=2.5 if strategy == "target_roas" else None, app_store=app_store, app_id=app_id)
    if needs_actions:
        spec["selective_optimization_conversion_actions"] = ["customers/123/conversionActions/9"]
    gads_creation.create_app_campaign("123", spec)
    ops = api[0].mutate.call_args.kwargs["mutate_operations"]
    campaign = ops[1].campaign_operation.create
    assert campaign._pb.WhichOneof("campaign_bidding_strategy") == strategy
    if strategy == "target_cpa":
        assert campaign.target_cpa.target_cpa_micros == 1000000
    if strategy == "target_roas":
        assert campaign.target_roas.target_roas == 2.5
    assert campaign.app_campaign_setting.bidding_strategy_goal_type.name == goal
    assert campaign.app_campaign_setting.app_id == spec["app_id"]
    assert campaign.app_campaign_setting.app_store.name == spec["app_store"]
    assert campaign.advertising_channel_sub_type.name == spec["sub_type"]
    assert list(campaign.selective_optimization.conversion_actions) == spec["selective_optimization_conversion_actions"]
    info = ops[-1].ad_group_ad_operation.create.ad.app_ad
    assert info.headlines[0].text == "Install now" and info.descriptions[0].text == "Try our app"
    assert info.images[0].asset == "customers/123/assets/10"
    assert info.youtube_videos[0].asset == "customers/123/assets/12"
    assert len(ops) == 6


ENGAGEMENT_GOALS = [g for g in APP_GOALS
                    if not g[0].startswith("OPTIMIZE_INSTALLS_") and not g[0].endswith("_TARGET_INSTALL_COST")]


@pytest.mark.parametrize("goal,strategy,needs_actions", ENGAGEMENT_GOALS)
def test_app_engagement_targets_user_list(api, goal, strategy, needs_actions):
    spec = copy.deepcopy(APP_SPEC)
    spec.update(sub_type="APP_CAMPAIGN_FOR_ENGAGEMENT", goal_type=goal,
                target_cpa_micros=1000000 if strategy == "target_cpa" else None,
                target_roas=2.5 if strategy == "target_roas" else None,
                selective_optimization_conversion_actions=["customers/123/conversionActions/9"],
                user_list="customers/123/userLists/5")
    gads_creation.create_app_campaign("123", spec)
    ops = api[0].mutate.call_args.kwargs["mutate_operations"]
    assert ops[1].campaign_operation.create.advertising_channel_sub_type.name == "APP_CAMPAIGN_FOR_ENGAGEMENT"
    audience = ops[-2].ad_group_criterion_operation.create
    assert audience.ad_group == "customers/123/adGroups/-3"
    assert audience.user_list.user_list == "customers/123/userLists/5" and not audience.negative
    info = ops[-1].ad_group_ad_operation.create.ad.app_engagement_ad
    assert info.headlines[0].text == "Install now" and info.images[0].asset == "customers/123/assets/10"
    assert info.videos[0].asset == "customers/123/assets/12"
    assert not ops[-1].ad_group_ad_operation.create.ad.final_urls
    assert len(ops) == 7


@pytest.mark.parametrize("change", [
    {"user_list": None}, {"user_list": ""}, {"user_list": "customers/456/userLists/5"},
    {"user_list": "customers/123/conversionActions/5"}, {"user_list": ["customers/123/userLists/5"]},
    {"selective_optimization_conversion_actions": []},
    {"goal_type": "OPTIMIZE_INSTALLS_TARGET_INSTALL_COST", "target_cpa_micros": 1000000, "target_roas": None},
    {"goal_type": "OPTIMIZE_IN_APP_CONVERSIONS_TARGET_INSTALL_COST", "target_cpa_micros": 1000000, "target_roas": None},
])
def test_app_engagement_rejections_before_client(monkeypatch, change):
    spec = copy.deepcopy(APP_SPEC)
    spec.update(sub_type="APP_CAMPAIGN_FOR_ENGAGEMENT", goal_type="OPTIMIZE_IN_APP_CONVERSIONS_WITHOUT_TARGET_CPA",
                target_cpa_micros=None, user_list="customers/123/userLists/5",
                selective_optimization_conversion_actions=["customers/123/conversionActions/9"])
    spec.update(change)
    reject_before_client(monkeypatch, gads_creation.create_app_campaign, spec)


def test_demand_gen_campaign_total_budget(api):
    spec = copy.deepcopy(DG_SPEC)
    spec.update(budget_period="CAMPAIGN_TOTAL", start_date="2026-11-01", end_date="2026-11-30")
    gads_creation.create_demand_gen_campaign("123", spec)
    ops = api[0].mutate.call_args.kwargs["mutate_operations"]
    budget = ops[0].campaign_budget_operation.create
    assert budget.period.name == "CUSTOM_PERIOD" and budget.total_amount_micros == 50000000
    assert not budget._pb.HasField("amount_micros")
    campaign = ops[1].campaign_operation.create
    assert campaign.start_date_time == "2026-11-01 00:00:00"
    assert campaign.end_date_time == "2026-11-30 23:59:59"


@pytest.mark.parametrize("change", [
    {"start_date": "2026-11-01"}, {"end_date": "2026-11-30"}, {"budget_period": "MONTHLY"},
    {"budget_period": "CAMPAIGN_TOTAL"},
    {"budget_period": "CAMPAIGN_TOTAL", "start_date": "2026-11-01", "end_date": None},
    {"budget_period": "CAMPAIGN_TOTAL", "start_date": "2026-11-30", "end_date": "2026-11-01"},
    {"budget_period": "CAMPAIGN_TOTAL", "start_date": "2026-02-30", "end_date": "2026-03-01"},
    {"budget_period": "CAMPAIGN_TOTAL", "start_date": "20261101", "end_date": "2026-11-30"},
])
def test_demand_gen_budget_period_rejections_before_client(monkeypatch, change):
    spec = copy.deepcopy(DG_SPEC)
    spec.update(change)
    reject_before_client(monkeypatch, gads_creation.create_demand_gen_campaign, spec)


@pytest.mark.parametrize("writer,base", WRITERS)
def test_creation_deduplicates_criteria_and_all_languages(api, writer, base):
    spec = copy.deepcopy(base)
    spec.update(geo_target_ids=["2840", "2840"], language_ids=[])
    if base is APP_SPEC:
        spec["ad"].update(images=None, youtube_videos=None)
    else:
        spec["ad"].update(marketing_images=None, square_marketing_images=["customers/123/assets/10"])
    writer("123", spec)
    ops = api[0].mutate.call_args.kwargs["mutate_operations"]
    assert len(ops) == 5
    assert not ops[-1].ad_group_ad_operation.create.ad.resource_name
    assert "resource_name" not in gads_client._msg_to_dict(ops[-1].ad_group_ad_operation.create.ad._pb)


def reject_before_client(monkeypatch, writer, spec, cid="123"):
    build = Mock(side_effect=AssertionError("credentials must not be accessed"))
    monkeypatch.setattr(gads_client, "build_client", build)
    with pytest.raises(ValueError):
        writer(cid, spec, False)
    build.assert_not_called()


@pytest.mark.parametrize("writer,base", WRITERS)
@pytest.mark.parametrize("key,value", [
    ("name", ""), ("name", "\nname"), ("name", 1), ("budget_micros", 0), ("budget_micros", -1),
    ("budget_micros", True), ("budget_micros", 1.5), ("budget_micros", 2**63),
    ("geo_target_ids", []), ("geo_target_ids", ["1"] * 101), ("geo_target_ids", ["US"]),
    ("geo_target_ids", [123]), ("geo_target_ids", ["１２"]), ("geo_target_ids", None),
    ("language_ids", ["1"] * 51), ("language_ids", ["en"]), ("language_ids", [True]), ("language_ids", None),
    ("eu_political_advertising", None), ("eu_political_advertising", 0),
    ("conversions_confirmed", False), ("conversions_confirmed", 1),
    ("target_cpa_micros", "1"), ("target_cpa_micros", True), ("target_cpa_micros", -1),
    ("target_roas", True), ("target_roas", "2"), ("target_roas", -1), ("target_roas", float("nan")),
    ("extra", None), ("ad", []),
])
def test_creation_invalid_fields_before_client(monkeypatch, writer, base, key, value):
    spec = copy.deepcopy(base)
    spec[key] = value
    reject_before_client(monkeypatch, writer, spec)


@pytest.mark.parametrize("writer,base", WRITERS + [(gads_creation.update_app_target, TARGET_SPEC)])
def test_exact_keys_and_customer_ids_before_client(monkeypatch, writer, base):
    for key in base:
        spec = copy.deepcopy(base)
        del spec[key]
        reject_before_client(monkeypatch, writer, spec)
    for value in (None, [], "spec"):
        reject_before_client(monkeypatch, writer, value)
    for cid in (None, "", "１２３", "abc", "123/456"):
        reject_before_client(monkeypatch, writer, base, cid)


@pytest.mark.parametrize("key,value", [
    ("bidding", "TARGET_SPEND"), ("bidding", []), ("channel_controls", "SELECTED_CHANNELS"),
    ("channel_controls", {}), ("channel_controls", {k: False for k in gads_creation.DEMAND_GEN_CHANNELS}),
    ("channel_controls", {k: 1 for k in gads_creation.DEMAND_GEN_CHANNELS}),
    ("asset_automation", {}), ("asset_automation", None),
    ("asset_automation", {k: "UNSPECIFIED" for k in gads_creation.DEMAND_GEN_ASSET_AUTOMATION_TYPES["MULTI_ASSET"]}),
])
def test_demand_gen_invalid_controls(monkeypatch, key, value):
    spec = copy.deepcopy(DG_SPEC)
    spec[key] = value
    reject_before_client(monkeypatch, gads_creation.create_demand_gen_campaign, spec)


@pytest.mark.parametrize("video", [False, True])
@pytest.mark.parametrize("invalid", ["missing", "other_type", "all_six", "unknown", "status"])
def test_demand_gen_automation_requires_ad_specific_keys(monkeypatch, video, invalid):
    spec = copy.deepcopy(DG_SPEC)
    if video:
        spec["ad"] = copy.deepcopy(VIDEO_AD)
    kinds = gads_creation.DEMAND_GEN_ASSET_AUTOMATION_TYPES[spec["ad"]["type"]]
    other_kinds = gads_creation.DEMAND_GEN_ASSET_AUTOMATION_TYPES["MULTI_ASSET" if video else "VIDEO_RESPONSIVE"]
    automation = dict.fromkeys(kinds, "OPTED_OUT")
    if invalid == "missing":
        del automation[kinds[0]]
    elif invalid == "other_type":
        automation = dict.fromkeys(other_kinds, "OPTED_OUT")
    elif invalid == "all_six":
        automation.update(dict.fromkeys(other_kinds, "OPTED_OUT"))
    elif invalid == "unknown":
        automation["GENERATE_LANDING_PAGE_PREVIEW"] = "OPTED_OUT"
    else:
        automation[kinds[0]] = "UNSPECIFIED"
    spec["asset_automation"] = automation
    reject_before_client(monkeypatch, gads_creation.create_demand_gen_campaign, spec)


def test_demand_gen_validates_ad_before_automation(monkeypatch):
    spec = copy.deepcopy(DG_SPEC)
    spec["ad"]["headlines"] = []
    spec["asset_automation"] = {}
    build = Mock()
    monkeypatch.setattr(gads_client, "build_client", build)
    with pytest.raises(ValueError, match="headlines"):
        gads_creation.create_demand_gen_campaign("123", spec)
    build.assert_not_called()


@pytest.mark.parametrize("writer,base", WRITERS)
def test_nested_ad_contracts_before_client(monkeypatch, writer, base):
    ads = [base["ad"], VIDEO_AD] if base is DG_SPEC else [base["ad"]]
    for ad in ads:
        for key in ad:
            spec = copy.deepcopy(base)
            spec["ad"] = copy.deepcopy(ad)
            del spec["ad"][key]
            reject_before_client(monkeypatch, writer, spec)
        invalid = {"headlines": [None, [], [1], [""], ["bad\ntext"]],
                   "descriptions": [None, [], "text"], "extra": [None]}
        if base is DG_SPEC:
            invalid.update(type=["CAROUSEL", None], final_url=[None, "relative", "ftp://example.com", "https://ex ample.com"],
                           business_name=[None, ""], logo_images=[[], None, ["customers/456/assets/11"]])
            if ad["type"] == "VIDEO_RESPONSIVE":
                invalid.update(videos=[[], None], long_headlines=[[], None])
        resource_fields = set(ad) & {"images", "youtube_videos", "marketing_images", "square_marketing_images", "logo_images", "videos"}
        for field in resource_fields:
            invalid.setdefault(field, []).extend(["customers/123/assets/10", ["customers/456/assets/10"],
                                                   ["customers/123/assets/-1"], ["customers/123/assets/1/extra"], [1]])
        for key, values in invalid.items():
            for value in values:
                spec = copy.deepcopy(base)
                spec["ad"] = copy.deepcopy(ad)
                spec["ad"][key] = value
                reject_before_client(monkeypatch, writer, spec)


def test_demand_gen_requires_marketing_image(monkeypatch):
    spec = copy.deepcopy(DG_SPEC)
    spec["ad"].update(marketing_images=None, square_marketing_images=[])
    reject_before_client(monkeypatch, gads_creation.create_demand_gen_campaign, spec)


@pytest.mark.parametrize("writer,base,strategy_key,strategies", [
    (gads_creation.create_demand_gen_campaign, DG_SPEC, "bidding", [("TARGET_CPA", "target_cpa_micros"), ("TARGET_ROAS", "target_roas")]),
    (gads_creation.create_app_campaign, APP_SPEC, "goal_type", [("OPTIMIZE_INSTALLS_TARGET_INSTALL_COST", "target_cpa_micros"), ("OPTIMIZE_RETURN_ON_ADVERTISING_SPEND", "target_roas")]),
])
def test_target_requirements_before_client(monkeypatch, writer, base, strategy_key, strategies):
    for strategy, target in strategies:
        for invalid in (None, True, 0, -1, "1", float("inf"), float("nan"), [], 10**400, 2**63 if target == "target_cpa_micros" else -0.5):
            spec = copy.deepcopy(base)
            spec.update(target_cpa_micros=None, target_roas=None)
            spec[strategy_key] = strategy
            spec[target] = invalid
            reject_before_client(monkeypatch, writer, spec)


@pytest.mark.parametrize("key,value", [
    ("sub_type", "APP_CAMPAIGN_FOR_PRE_REGISTRATION"), ("user_list", "customers/123/userLists/5"),
    ("sub_type", []), ("app_store", "UNSPECIFIED"), ("app_store", []), ("app_id", ""), ("app_id", 123),
    ("goal_type", "OPTIMIZE_PRE_REGISTRATION_CONVERSION_VOLUME"), ("goal_type", []),
    ("selective_optimization_conversion_actions", None), ("selective_optimization_conversion_actions", ["customers/456/conversionActions/1"]),
    ("selective_optimization_conversion_actions", ["customers/123/assets/1"]),
])
def test_app_invalid_settings(monkeypatch, key, value):
    spec = copy.deepcopy(APP_SPEC)
    spec[key] = value
    reject_before_client(monkeypatch, gads_creation.create_app_campaign, spec)


@pytest.mark.parametrize("goal,strategy,needs_actions", APP_GOALS)
def test_app_selective_optimization_and_wrong_targets(monkeypatch, goal, strategy, needs_actions):
    spec = copy.deepcopy(APP_SPEC)
    spec.update(goal_type=goal, target_cpa_micros=1000000 if strategy == "target_cpa" else None,
                target_roas=2 if strategy == "target_roas" else None)
    if needs_actions:
        reject_before_client(monkeypatch, gads_creation.create_app_campaign, spec)
    spec["selective_optimization_conversion_actions"] = ["customers/123/conversionActions/1"]
    spec["target_roas" if strategy == "target_cpa" else "target_cpa_micros"] = 1
    reject_before_client(monkeypatch, gads_creation.create_app_campaign, spec)


@pytest.mark.parametrize("writer,base", WRITERS + [(gads_creation.update_app_target, TARGET_SPEC)])
@pytest.mark.parametrize("answer", ["n", "", "yes", None])
def test_new_writers_cancel_without_mutating(api, monkeypatch, writer, base, answer):
    def respond():
        if answer is None:
            raise EOFError
        return answer
    monkeypatch.setattr("builtins.input", respond)
    with pytest.raises(RuntimeError, match="cancelled"):
        writer("123", copy.deepcopy(base), False)
    api[0].mutate.assert_not_called()
    api[1].mutate_campaigns.assert_not_called()


@pytest.mark.parametrize("writer,base", WRITERS + [(gads_creation.update_app_target, TARGET_SPEC)])
def test_validation_failure_stops_apply(api, writer, base):
    mutation = api[1].mutate_campaigns if base is TARGET_SPEC else api[0].mutate
    mutation.side_effect = ValueError("API validation failed")
    with pytest.raises(ValueError, match="API validation failed"):
        writer("123", copy.deepcopy(base), False)
    assert mutation.call_count == 1
    assert mutation.call_args.kwargs["validate_only"] is True


@pytest.mark.parametrize("dry", [True, False])
@pytest.mark.parametrize("roas", [True, False])
def test_app_target_update(api, dry, roas):
    ads, campaigns, row = api
    spec = copy.deepcopy(TARGET_SPEC)
    if roas:
        spec.update(target_cpa_micros=None, target_roas=3.0)
        row.campaign.app_campaign_setting.bidding_strategy_goal_type = "OPTIMIZE_RETURN_ON_ADVERTISING_SPEND"
        row.campaign.bidding_strategy_type = "TARGET_ROAS"
        row.campaign.target_roas = {"target_roas": 2.0}
    result = gads_creation.update_app_target("123", spec, dry)
    assert result["status"] == ("validated" if dry else "applied")
    assert result["previous_value"] == (2.0 if roas else 1000000)
    assert result["new_value"] == (3.0 if roas else 2000000)
    assert result["response"] == {} and result["customer_id"] == "123"
    assert "WHERE campaign.id = 42" in ads.search.call_args.kwargs["query"]
    ads.mutate.assert_not_called()
    field = "target_roas.target_roas" if roas else "target_cpa.target_cpa_micros"
    assert result["field"] == field
    assert [c.kwargs["validate_only"] for c in campaigns.mutate_campaigns.call_args_list] == ([True] if dry else [True, False])
    for call in campaigns.mutate_campaigns.call_args_list:
        assert call.kwargs["customer_id"] == "123"
        assert len(call.kwargs["operations"]) == 1
        op = call.kwargs["operations"][0]
        assert list(op.update_mask.paths) == [field]
        assert gads_client._msg_to_dict(op.update._pb) == {
            "resource_name": "customers/123/campaigns/42",
            "target_roas" if roas else "target_cpa": {"target_roas" if roas else "target_cpa_micros": 3.0 if roas else "2000000"},
        }


@pytest.mark.parametrize("key,value", [
    ("campaign_id", 42), ("campaign_id", "42 OR 1=1"), ("campaign_id", "-1"),
    ("target_roas", 2), ("target_cpa_micros", None), ("target_cpa_micros", True),
    ("target_cpa_micros", 0), ("target_cpa_micros", 2**63), ("extra", None),
])
def test_app_target_input_rejected_before_client(monkeypatch, key, value):
    spec = copy.deepcopy(TARGET_SPEC)
    spec[key] = value
    reject_before_client(monkeypatch, gads_creation.update_app_target, spec)


@pytest.mark.parametrize("value", [True, 0, -1, "2", float("nan"), float("inf"), 10**400])
def test_app_target_invalid_roas_before_client(monkeypatch, value):
    spec = {"campaign_id": "42", "target_cpa_micros": None, "target_roas": value}
    reject_before_client(monkeypatch, gads_creation.update_app_target, spec)


@pytest.mark.parametrize("goal,strategy,needs_actions", APP_GOALS + [("UNKNOWN", None, False)])
@pytest.mark.parametrize("roas", [False, True])
def test_app_target_rejects_incompatible_goals(api, goal, strategy, needs_actions, roas):
    api[2].campaign.app_campaign_setting.bidding_strategy_goal_type = goal
    api[2].campaign.bidding_strategy_type = "TARGET_ROAS" if roas else "TARGET_CPA"
    spec = {"campaign_id": "42", "target_cpa_micros": None if roas else 2000000,
            "target_roas": 2 if roas else None}
    matching = strategy == ("target_roas" if roas else "target_cpa")
    if matching:
        gads_creation.update_app_target("123", spec)
    else:
        with pytest.raises(ValueError, match=goal):
            gads_creation.update_app_target("123", spec)
        api[1].mutate_campaigns.assert_not_called()


@pytest.mark.parametrize("case", ["wrong_channel", "removed", "missing", "duplicate",
                                  "other_strategy", "portfolio"])
def test_app_target_read_rejections(api, case):
    if case == "wrong_channel":
        api[2].campaign.advertising_channel_type = "SEARCH"
    elif case == "removed":
        api[2].campaign.status = "REMOVED"
    elif case == "other_strategy":
        api[2].campaign.bidding_strategy_type = "MAXIMIZE_CONVERSIONS"
    elif case == "portfolio":
        api[2].campaign.bidding_strategy = "customers/123/biddingStrategies/7"
    else:
        api[0].search.return_value = [] if case == "missing" else [api[2], api[2]]
    with pytest.raises(ValueError):
        gads_creation.update_app_target("123", TARGET_SPEC)
    api[1].mutate_campaigns.assert_not_called()
