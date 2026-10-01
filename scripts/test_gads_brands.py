from unittest.mock import Mock

import gads_brands
import gads_client
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials


def test_suggest_reads_real_brand_response_fields(monkeypatch):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                           use_proto_plus=True)
    response = types.get_type("SuggestBrandsResponse")
    brand = types.get_type("BrandSuggestion")
    brand.id = "/m/acme"
    brand.name = "Acme"
    brand.urls.append("https://example.test")
    response.brands.append(brand)
    service = Mock()
    service.suggest_brands.return_value = response
    client = Mock(get_type=types.get_type)
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", lambda: client)
    result = gads_brands.suggest("123", ["Acme"])
    assert result["suggestions"] == [{"query": "Acme", "id": "/m/acme",
        "name": "Acme", "urls": ["https://example.test"], "state": "UNSPECIFIED"}]
    request = service.suggest_brands.call_args.kwargs["request"]
    assert request.customer_id == "123"
    assert request.brand_prefix == "Acme"


@pytest.fixture
def writer(monkeypatch):
    import hashlib
    import json

    types = GoogleAdsClient(credentials=AnonymousCredentials(), version="v25", use_proto_plus=True)
    service = Mock()
    service.mutate.return_value = types.get_type("MutateGoogleAdsResponse")
    client = Mock(get_type=types.get_type)
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", lambda: client)
    name = "gads-agents-brands-" + hashlib.sha256(json.dumps(["/m/acme"], separators=(",", ":")).encode()).hexdigest()[:24]
    rows = {
        "campaign": [{"campaign": {"id": "9", "status": "PAUSED", "advertising_channel_type": "PERFORMANCE_MAX"}}],
        "shared_set": [], "shared_criterion": [], "campaign_criterion": [],
    }

    def search(cid, query):
        assert cid == "123"
        return rows[query.split("FROM ")[1].split()[0]]

    monkeypatch.setattr(gads_client, "search_stream", search)
    monkeypatch.setattr("builtins.input", lambda: "y")
    return service, rows, name


@pytest.mark.parametrize("dry", [True, False])
def test_brand_create_and_attach_atomic(writer, capsys, monkeypatch, dry):
    service, rows, name = writer

    def approve():
        assert not service.mutate.called
        preview = capsys.readouterr().err
        assert '"entity_id": "/m/acme"' in preview and '"negative": true' in preview
        return "y"

    monkeypatch.setattr("builtins.input", approve)
    result = gads_brands.exclude("123", ["9", "9"], ["/m/acme"], dry)
    assert result["managed_list_name"] == name
    assert [c.kwargs["validate_only"] for c in service.mutate.call_args_list] == ([True] if dry else [True, False])
    for call in service.mutate.call_args_list:
        assert call.kwargs["retry"] is None and call.kwargs["partial_failure"] is False
        ops = call.kwargs["mutate_operations"]
        assert len(ops) == 3
        assert ops[0].shared_set_operation.create.type_.name == "BRANDS"
        ref = ops[0].shared_set_operation.create.resource_name
        assert ops[1].shared_criterion_operation.create.shared_set == ref
        assert ops[2].campaign_criterion_operation.create.brand_list.shared_set == ref
        assert ops[2].campaign_criterion_operation.create.campaign == "customers/123/campaigns/9"


def existing(rows, name):
    ref = "customers/123/sharedSets/7"
    rows["shared_set"] = [{"shared_set": {"name": name, "resource_name": ref, "status": "ENABLED"}}]
    rows["shared_criterion"] = [{"shared_criterion": {"brand": {"entity_id": "/m/acme"}}}]
    return ref


def test_brand_reuse_never_edits_list(writer):
    service, rows, name = writer
    existing(rows, name)
    gads_brands.exclude("123", ["9"], ["/m/acme"], False)
    ops = service.mutate.call_args.kwargs["mutate_operations"]
    assert len(ops) == 1
    assert ops[0].campaign_criterion_operation.create.brand_list.shared_set == "customers/123/sharedSets/7"


def test_brand_already_attached_is_noop(writer):
    service, rows, name = writer
    ref = existing(rows, name)
    rows["campaign_criterion"] = [{"campaign": {"id": "9"}, "campaign_criterion": {"negative": True, "brand_list": {"shared_set": ref}}}]
    assert gads_brands.exclude("123", ["9"], ["/m/acme"], False)["status"] == "no_op"
    service.mutate.assert_not_called()


@pytest.mark.parametrize("problem", ["drift", "duplicate", "foreign", "search", "removed", "missing"])
def test_brand_ambiguous_or_unsupported_scope_rejected(writer, problem):
    service, rows, name = writer
    existing(rows, name)
    if problem == "drift":
        rows["shared_criterion"] = []
    elif problem == "duplicate":
        rows["shared_set"] *= 2
    elif problem == "foreign":
        rows["shared_set"][0]["shared_set"]["resource_name"] = "customers/456/sharedSets/7"
    elif problem == "search":
        rows["campaign"][0]["campaign"]["advertising_channel_type"] = "SEARCH"
    elif problem == "removed":
        rows["campaign"][0]["campaign"]["status"] = "REMOVED"
    else:
        rows["campaign"] = []
    with pytest.raises(ValueError):
        gads_brands.exclude("123", ["9"], ["/m/acme"], False)
    service.mutate.assert_not_called()


def test_brand_cancel_and_validation_failure(writer, monkeypatch):
    service, _, _ = writer
    monkeypatch.setattr("builtins.input", lambda: "n")
    with pytest.raises(RuntimeError):
        gads_brands.exclude("123", ["9"], ["/m/acme"], False)
    service.mutate.assert_not_called()
    monkeypatch.setattr("builtins.input", lambda: "y")
    service.mutate.side_effect = ValueError("invalid brand")
    with pytest.raises(ValueError):
        gads_brands.exclude("123", ["9"], ["/m/acme"], False)
    assert service.mutate.call_count == 1
    assert service.mutate.call_args.kwargs["validate_only"] is True


@pytest.mark.parametrize("campaigns,brands", [([], ["/m/acme"]), (["9"], []), (["9 OR 1=1"], ["x"])])
def test_brand_input_rejected_before_credentials(monkeypatch, campaigns, brands):
    build = Mock()
    monkeypatch.setattr(gads_client, "build_client", build)
    with pytest.raises(ValueError):
        gads_brands.exclude("123", campaigns, brands, False)
    build.assert_not_called()


def test_brand_cli_default_does_not_read_input(monkeypatch, capsys):
    import json
    monkeypatch.setattr("sys.argv", ["gads_brands", "--customer", "123", "exclude", "--input", "missing.json", "--json"])
    assert gads_brands.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_op"
