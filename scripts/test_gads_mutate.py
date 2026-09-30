"""Exercise every supported writer with real message types and mocked services."""

import json
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import gads_apply
import gads_client
import gads_creative
import pytest
from gads_mutate import MutationCancelled
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials


@pytest.fixture(params=["negatives", "placements", "upload", "pmax"])
def writer(request, monkeypatch, tmp_path):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                           use_proto_plus=True)
    service = Mock()
    service.campaign_path.side_effect = lambda c, i: f"customers/{c}/campaigns/{i}"
    service.asset_group_path.side_effect = lambda c, i: f"customers/{c}/assetGroups/{i}"
    client = Mock(get_type=types.get_type, enums=types.enums)
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", lambda: client)
    asset = "customers/123/assets/7"
    kind = request.param
    if kind == "negatives":
        call = partial(gads_apply.apply_negatives,
            "123", {"campaign_id": "9", "terms": ["unwanted query"]})
        mutation = service.mutate_campaign_criteria
    elif kind == "placements":
        call = partial(gads_apply.apply_placement_exclusions,
            "123", {"scam": [{"placement": "example.test"}]})
        mutation = service.mutate_customer_negative_criteria
    elif kind == "upload":
        path = tmp_path / "image.png"
        path.write_bytes(b"mock-image")
        call = partial(gads_creative.upload_image_asset, "123", path, "Hero")
        mutation = service.mutate_assets
    elif kind == "pmax":
        call = partial(gads_creative.attach_to_asset_group,
            "123", "9", asset, "MARKETING_IMAGE")
        mutation = service.mutate_asset_group_assets
    else:
        call = partial(gads_creative.attach_to_search_campaign,
            "123", "9", asset, "IMAGE")
        mutation = service.mutate_campaign_assets
    mutation.return_value = SimpleNamespace(results=[SimpleNamespace(resource_name=asset)])
    return call, mutation


@pytest.mark.parametrize("answer", ["", "n", "yes", EOFError(), OSError()])
def test_writer_rejects_without_explicit_y(writer, monkeypatch, answer):
    call, mutation = writer
    monkeypatch.setattr("builtins.input", Mock(
        side_effect=answer if isinstance(answer, Exception) else None, return_value=answer))
    with pytest.raises(MutationCancelled):
        call(False)
    mutation.assert_not_called()


@pytest.mark.parametrize("dry", [True, False])
def test_writer_previews_before_input_and_validates_before_apply(writer, monkeypatch, capsys, dry):
    call, mutation = writer
    previews = []

    def approve():
        mutation.assert_not_called()
        captured = capsys.readouterr()
        assert captured.out == ""
        document, prompt = captured.err.rsplit("\n", 2)[:2]
        previews.append(json.loads(document))
        assert prompt.endswith("y/N")
        return "y"

    monkeypatch.setattr("builtins.input", approve)
    call(dry)
    assert [c.kwargs["validate_only"] for c in mutation.call_args_list] == (
        [True] if dry else [True, False])
    from google.protobuf.json_format import MessageToDict
    for c in mutation.call_args_list:
        assert c.kwargs["customer_id"] == previews[0]["customer_id"]
        assert [MessageToDict(op._pb, preserving_proto_field_name=True)
                for op in c.kwargs["operations"]] == previews[0]["operations"]


def test_validation_failure_never_applies(writer, monkeypatch):
    call, mutation = writer
    monkeypatch.setattr("builtins.input", lambda: "y")
    mutation.side_effect = ValueError("invalid operation")
    with pytest.raises(ValueError, match="invalid operation"):
        call(False)
    assert mutation.call_count == 1
    assert mutation.call_args.kwargs["validate_only"] is True


@pytest.mark.parametrize("module,args", [
    (gads_apply, ["--customer", "123", "negatives", "--input", "unused.json"]),
    (gads_apply, ["--customer", "123", "placements", "--input", "unused.json"]),
    (gads_creative, ["upload", "--customer", "123", "--image", "unused.png"]),
    (gads_creative, ["attach", "--customer", "123", "--asset-resource", "a",
                     "--asset-group-id", "9", "--field-type", "MARKETING_IMAGE"]),
])
def test_conflicting_modes_rejected_before_io(module, args, monkeypatch):
    monkeypatch.setattr("sys.argv", [module.__name__, *args, "--apply", "--validate-only"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


