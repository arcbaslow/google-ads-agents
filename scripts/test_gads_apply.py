import json
from unittest.mock import Mock

import gads_apply
import gads_client
import gads_creative
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.api_core.exceptions import NotFound
from google.auth.credentials import AnonymousCredentials


@pytest.fixture
def api(monkeypatch):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                           use_proto_plus=True, version="v25")
    services = {}

    def service(name):
        return services.setdefault(name, Mock())

    client = Mock(get_type=types.get_type, enums=types.enums, get_service=service)
    monkeypatch.setattr(gads_client, "build_client", Mock(return_value=client))
    monkeypatch.setattr("builtins.input", lambda: "y")
    row = types.get_type("GoogleAdsRow")
    row.campaign.advertising_channel_type = "DISPLAY"
    row.campaign.resource_name = "customers/123/campaigns/9"
    row.ad_group.resource_name = "customers/123/adGroups/8"
    row.ad_group.optimized_targeting_enabled = True
    service("GoogleAdsService").search.return_value = [row]
    service("CampaignService").campaign_path.return_value = "customers/123/campaigns/9"
    for name, method, response_type in [
        ("AdGroupService", "mutate_ad_groups", "MutateAdGroupsResponse"),
        ("CampaignCriterionService", "mutate_campaign_criteria", "MutateCampaignCriteriaResponse"),
        ("CustomerNegativeCriterionService", "mutate_customer_negative_criteria",
         "MutateCustomerNegativeCriteriaResponse"),
        ("CampaignAssetService", "mutate_campaign_assets", "MutateCampaignAssetsResponse"),
    ]:
        getattr(service(name), method).return_value = types.get_type(response_type)
    return client, row, service


@pytest.mark.parametrize("enabled", [True, False])
def test_optimized_targeting(api, capsys, enabled):
    _, row, service = api
    result = gads_apply.apply_optimized_targeting("123", {"ad_group_id": "8", "enabled": enabled}, False)
    calls = service("AdGroupService").mutate_ad_groups.call_args_list
    assert [c.kwargs["validate_only"] for c in calls] == [True, False]
    op = calls[-1].kwargs["operations"][0]
    assert op.update.resource_name == row.ad_group.resource_name
    assert op.update.optimized_targeting_enabled is enabled
    assert list(op.update_mask.paths) == ["optimized_targeting_enabled"]
    assert result["previous"] is True
    assert result["enabled"] is enabled
    preview = capsys.readouterr().err
    assert '"previous": true' in preview
    assert '"enabled": ' + json.dumps(enabled) in preview


@pytest.mark.parametrize("channel", ["VIDEO", "SEARCH", "PERFORMANCE_MAX"])
def test_optimized_targeting_channel_guard(api, channel):
    _, row, service = api
    row.campaign.advertising_channel_type = channel
    with pytest.raises(ValueError, match=channel):
        gads_apply.apply_optimized_targeting("123", {"ad_group_id": "8", "enabled": False}, False)
    service("AdGroupService").mutate_ad_groups.assert_not_called()


@pytest.mark.parametrize("campaign_id", [None, "9"])
def test_placement_routing_and_scope(api, campaign_id):
    _, _, service = api
    payload = {"scam": [{"placement": "example.test", "target_url": None},
                         {"target_url": "https://youtube.com/channel/UCabc/"},
                         {"placement": "UCdef"}, {"placement": "mobileapp://2-com.example"}]}
    gads_apply.apply_placement_exclusions("123", payload, False, campaign_id)
    if campaign_id:
        mutation = service("CampaignCriterionService").mutate_campaign_criteria
        service("CustomerNegativeCriterionService").mutate_customer_negative_criteria.assert_not_called()
    else:
        mutation = service("CustomerNegativeCriterionService").mutate_customer_negative_criteria
        service("GoogleAdsService").search.assert_not_called()
    assert [c.kwargs["validate_only"] for c in mutation.call_args_list] == [True, False]
    operations = mutation.call_args.kwargs["operations"]
    assert operations[0].create.placement.url == "example.test"
    assert operations[1].create.youtube_channel.channel_id == "UCabc"
    assert operations[2].create.youtube_channel.channel_id == "UCdef"
    assert operations[3].create.mobile_application.app_id == "2-com.example"
    if campaign_id:
        assert all(op.create.negative and op.create.campaign == "customers/123/campaigns/9"
                   for op in operations)


@pytest.mark.parametrize("channel", ["SEARCH", "VIDEO", "PERFORMANCE_MAX"])
def test_placements_reject_other_channels(api, channel):
    _, row, service = api
    row.campaign.advertising_channel_type = channel
    with pytest.raises(ValueError, match=channel):
        gads_apply.apply_placement_exclusions("123", {"x": [{"placement": "a.test"}]}, False, "9")
    service("CampaignCriterionService").mutate_campaign_criteria.assert_not_called()


@pytest.mark.parametrize("channel", ["SEARCH", "DISPLAY", "VIDEO"])
def test_negatives_guard(api, channel):
    _, row, service = api
    row.campaign.advertising_channel_type = channel
    mutation = service("CampaignCriterionService").mutate_campaign_criteria
    if channel == "VIDEO":
        with pytest.raises(ValueError, match="API does not support Video campaign mutations"):
            gads_apply.apply_negatives("123", {"campaign_id": "9", "terms": ["term"]}, False)
        mutation.assert_not_called()
    else:
        gads_apply.apply_negatives("123", {"campaign_id": "9", "terms": ["term"]}, False)
        assert mutation.call_count == 2


@pytest.mark.parametrize("channel", ["SEARCH", "DISPLAY", "VIDEO"])
def test_attach_guard(api, channel):
    _, row, service = api
    row.campaign.advertising_channel_type = channel
    mutation = service("CampaignAssetService").mutate_campaign_assets
    if channel == "SEARCH":
        service("CampaignService").campaign_path.return_value = "customers/123/campaigns/9"
        gads_creative.attach_to_search_campaign("123", "9", "customers/123/assets/1", "AD_IMAGE", False)
        assert mutation.call_count == 2
    else:
        with pytest.raises(ValueError, match=channel):
            gads_creative.attach_to_search_campaign("123", "9", "customers/123/assets/1", "AD_IMAGE", False)
        mutation.assert_not_called()


@pytest.mark.parametrize("writer", ["negatives", "placements", "optimized", "attach"])
def test_missing_resource_no_mutation(api, writer):
    _, _, service = api
    service("GoogleAdsService").search.return_value = []
    with pytest.raises(NotFound, match="not_found"):
        if writer == "negatives":
            gads_apply.apply_negatives("123", {"campaign_id": "9", "terms": ["term"]}, False)
        elif writer == "placements":
            gads_apply.apply_placement_exclusions("123", {}, False, "9")
        elif writer == "optimized":
            gads_apply.apply_optimized_targeting("123", {"ad_group_id": "8", "enabled": False}, False)
        else:
            gads_creative.attach_to_search_campaign("123", "9", "customers/123/assets/1", "AD_IMAGE", False)
    service("CampaignCriterionService").mutate_campaign_criteria.assert_not_called()
    service("AdGroupService").mutate_ad_groups.assert_not_called()
    service("CampaignAssetService").mutate_campaign_assets.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"ad_group_id": "8", "enabled": 1},
                                      {"ad_group_id": "8 OR 1=1", "enabled": True}])
def test_optimized_invalid_input_before_client(api, payload):
    with pytest.raises(ValueError):
        gads_apply.apply_optimized_targeting("123", payload, False)
    gads_client.build_client.assert_not_called()


@pytest.mark.parametrize("action", ["negatives", "placements", "optimized-targeting"])
def test_apply_cli_noop_and_bad_json(api, monkeypatch, tmp_path, capsys, action):
    path = tmp_path / "bad.json"
    path.write_text("{")
    args = ["gads_apply", "--customer", "123", action, "--input", str(path), "--json"]
    monkeypatch.setattr("sys.argv", args)
    assert gads_apply.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_op"
    monkeypatch.setattr("sys.argv", [*args, "--apply"])
    assert gads_apply.main() == 3
    assert json.loads(capsys.readouterr().out)["error_code"] == "invalid_request"
    gads_client.build_client.assert_not_called()
