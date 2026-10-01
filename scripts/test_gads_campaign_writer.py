import copy
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
