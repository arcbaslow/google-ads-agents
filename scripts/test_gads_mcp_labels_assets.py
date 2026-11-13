"""Labels and assets through the real MCP schemas and offline Google Ads transport."""

import base64
import hashlib
import json
import logging
import re

import gads_mcp
import pytest
from test_gads_mcp import (
    CUSTOMER,
    TYPES,
    ads_error,
    home,  # noqa: F401
    install,
    stream,
)
from test_gads_mcp_writes import Account, Gate, build_writes, call, mutates

PNG = b"\x89PNG\r\n\x1a\nprivate-image-content"
IMAGE = base64.b64encode(PNG).decode()
LABEL = {"operation": "UPDATE", "label_id": "7", "name": "Reviewed"}
ASSOCIATION = {"operation": "CREATE", "association_type": "CAMPAIGN", "label_id": "7", "resource_ids": ["111"]}
ASSETS = [
    {"asset_type": "TEXT", "text": "Headline"},
    {"asset_type": "IMAGE", "image_data": IMAGE, "image_mime_type": "IMAGE_PNG"},
    {"asset_type": "YOUTUBE_VIDEO", "youtube_video_id": "abcdefghijk"},
    {"asset_type": "SITELINK", "sitelink_link_text": "Visit", "final_urls": ["https://example.com"],
     "sitelink_description1": "First", "sitelink_description2": "Second"},
    {"asset_type": "CALLOUT", "callout_text": "Free delivery"},
    {"asset_type": "STRUCTURED_SNIPPET", "structured_snippet_header": "Types",
     "structured_snippet_values": ["One", "Two", "Three"]},
]
WRITES = [("manage_labels", LABEL), ("manage_label_associations", ASSOCIATION)] + [
    ("create_asset", asset) for asset in ASSETS]
ENTITIES = [
    ("CAMPAIGN", "campaign", "Campaign", "campaigns", "campaignLabels", "111"),
    ("AD_GROUP", "ad_group", "AdGroup", "adGroups", "adGroupLabels", "222"),
    ("AD_GROUP_CRITERION", "ad_group_criterion", "AdGroupCriterion", "adGroupCriteria", "adGroupCriterionLabels", "222~11"),
]


class LabelAccount(Account):
    def __init__(self):
        super().__init__()
        self.label_name = "Original"
        self.label_status = "ENABLED"
        self.label_exists = True
        self.customer_name = "Example"
        self.customer_status = "ENABLED"
        self.linked = False
        self.target_exists = True

    def rows(self, query):
        resource = re.search(r"FROM (\w+)", query).group(1)
        if resource == "label":
            if not self.label_exists or "label.name =" in query and "'Original'" not in query:
                return []
            return [{"label": {"id": 7, "name": self.label_name, "status": self.label_status,
                               "text_label": {"background_color": "#112233", "description": "Old"}}}]
        if resource == "customer":
            if not self.target_exists:
                return []
            return [{"customer": {"id": int(CUSTOMER), "resource_name": f"customers/{CUSTOMER}",
                                  "descriptive_name": self.customer_name, "status": self.customer_status}}]
        for _, entity, _, plural, segment, identifier in ENTITIES:
            path = f"customers/{CUSTOMER}/{plural}/{identifier}"
            if resource == entity + "_label":
                return [{resource: {"resource_name": f"customers/{CUSTOMER}/{segment}/{identifier}~7",
                                    entity: path, "label": f"customers/{CUSTOMER}/labels/7"}}] if self.linked else []
            if resource == entity:
                if not self.target_exists:
                    return []
                fields = {"resource_name": path, "status": "ENABLED"}
                fields.update({"criterion_id": 11} if entity == "ad_group_criterion" else {"name": "Target"})
                return [{entity: fields, "campaign": {**(fields if entity == "campaign" else {}),
                                                       "advertising_channel_type": self.channel}}]
        return super().rows(query)

    def respond(self, service, method, kwargs):
        if method.startswith("mutate"):
            if self.mutate_error:
                raise self.mutate_error
            response = TYPES.get_type("Mutate" + service.removesuffix("Service") + "sResponse")
            if not kwargs["request"].validate_only:
                response.results.extend([{"resource_name": f"customers/{CUSTOMER}/created/{i}"}
                                         for i, _ in enumerate(kwargs["request"].operations)])
            return response
        return stream(self.rows(kwargs["query"]))


@pytest.fixture
def account(monkeypatch):
    account = LabelAccount()
    account.recorder = install(monkeypatch.setattr, account.respond)
    account.recorder.client_class.enums = TYPES.enums
    return account


def invoke(server, name, args, **extra):
    return call(server, name, customer_id=CUSTOMER, **args, **extra)


@pytest.mark.parametrize("name,args", WRITES)
def test_review_confirm_replay_and_gate(account, name, args):
    gate = Gate()
    server = build_writes(gate)
    dry = invoke(server, name, args)
    assert dry["validated"] and dry["dry_run"] and dry["confirm_expires_in"] == 600
    assert len(mutates(account)) == 1 and mutates(account)[0][2]["request"].validate_only
    gate.refusal = {"error": "host_refused", "detail": "unchanged"}
    assert invoke(server, name, args, confirm=dry["confirm"]) == gate.refusal
    assert len(mutates(account)) == 1
    gate.refusal = None
    applied = invoke(server, name, args, confirm=dry["confirm"])
    assert applied["applied"] == 1 and applied["dry_run"] is False
    assert [item[2]["request"].validate_only for item in mutates(account)] == [True, False]
    assert all(item[2]["retry"] is None for item in mutates(account))
    assert "already used" in invoke(server, name, args, confirm=dry["confirm"])["hint"]
    assert len(mutates(account)) == 2


@pytest.mark.parametrize("name,args,changed", [
    ("manage_labels", LABEL, {**LABEL, "name": "Different"}),
    ("manage_label_associations", ASSOCIATION, {**ASSOCIATION, "operation": "REMOVE"}),
    ("create_asset", ASSETS[0], {**ASSETS[0], "text": "Different"}),
    ("create_asset", ASSETS[1], {**ASSETS[1], "image_data": base64.b64encode(PNG + b"new").decode()}),
])
def test_changed_arguments_burn_token(account, name, args, changed):
    server = build_writes(Gate())
    dry = invoke(server, name, args)
    result = invoke(server, name, changed, confirm=dry["confirm"])
    assert result["error"] == "invalid_argument" and "different request" in result["hint"]
    assert len(mutates(account)) == 1


@pytest.mark.parametrize("name,args,field", [
    ("manage_labels", LABEL, "label_name"),
    ("manage_label_associations", ASSOCIATION, "label_name"),
    ("manage_label_associations", ASSOCIATION, "linked"),
    ("create_asset", ASSETS[0], "customer_status"),
])
def test_state_conflict(account, name, args, field):
    server = build_writes(Gate())
    dry = invoke(server, name, args)
    setattr(account, field, True if field == "linked" else "CANCELED" if field == "customer_status" else "Changed")
    assert invoke(server, name, args, confirm=dry["confirm"])["error"] == "conflict"
    assert len(mutates(account)) == 1


@pytest.mark.parametrize("operation", ["CREATE", "UPDATE", "REMOVE"])
def test_label_operation_fields(account, operation):
    args = {"operation": operation}
    if operation != "CREATE":
        args["label_id"] = "7"
    if operation != "REMOVE":
        args.update(name=" New ", background_color="#aAbB00", description="")
    out = invoke(build_writes(Gate()), "manage_labels", args)
    assert out["validated"]
    op = mutates(account)[0][2]["request"].operations[0]
    assert op._pb.WhichOneof("operation") == operation.lower()
    if operation == "REMOVE":
        assert op.remove == f"customers/{CUSTOMER}/labels/7"
        assert out["changes"] == [{"field": "status", "current": "ENABLED", "new": "REMOVED"}]
    else:
        label = getattr(op, operation.lower())
        assert label.name == "New" and label.text_label.background_color == "#aAbB00"
        assert label.text_label.description == ""
        if operation == "UPDATE":
            assert list(op.update_mask.paths) == ["name", "text_label.background_color", "text_label.description"]


def test_label_partial_update_and_escaped_name(account):
    server = build_writes(Gate())
    invoke(server, "manage_labels", {"operation": "UPDATE", "label_id": "7", "description": ""})
    op = mutates(account)[0][2]["request"].operations[0]
    assert list(op.update_mask.paths) == ["text_label.description"]
    assert {field.name for field, _ in op.update._pb.ListFields()} == {"resource_name", "text_label"}
    invoke(server, "manage_labels", {"operation": "CREATE", "name": "a'\\b"})
    queries = [kw["query"] for _, method, kw in account.recorder.requests if method == "search_stream"]
    assert "label.name = 'a\\'\\\\b'" in queries[-1]


@pytest.mark.parametrize("status", ["ENABLED", "REMOVED"])
def test_duplicate_label_create(account, status):
    account.label_status = status
    out = invoke(build_writes(Gate()), "manage_labels", {"operation": "CREATE", "name": "Original"})
    if status == "ENABLED":
        assert out["error"] == "invalid_argument" and "7" in out["hint"]
        assert not mutates(account)
    else:
        assert out["validated"]


@pytest.mark.parametrize("kind,entity,stem,plural,segment,identifier", ENTITIES)
@pytest.mark.parametrize("operation", ["CREATE", "REMOVE"])
def test_association_paths(account, kind, entity, stem, plural, segment, identifier, operation):
    account.linked = operation == "REMOVE"
    args = {"operation": operation, "association_type": kind, "label_id": "7",
            "resource_ids": [identifier]}
    out = invoke(build_writes(Gate()), "manage_label_associations", args)
    assert out["validated"]
    service, method, kwargs = mutates(account)[0]
    assert service == stem + "LabelService" and method == f"mutate_{entity}_labels"
    op = kwargs["request"].operations[0]
    if operation == "REMOVE":
        assert op.remove == f"customers/{CUSTOMER}/{segment}/{identifier}~7"
    else:
        assert getattr(op.create, entity) == f"customers/{CUSTOMER}/{plural}/{identifier}"
        assert op.create.label == f"customers/{CUSTOMER}/labels/7"
    assert out["changes"][0]["has_label"] is (operation == "REMOVE")
    assert out["changes"][0]["new_has_label"] is (operation == "CREATE")


@pytest.mark.parametrize("operation,linked,error", [("CREATE", True, "invalid_argument"), ("REMOVE", False, "not_found")])
def test_association_preconditions(account, operation, linked, error):
    account.linked = linked
    out = invoke(build_writes(Gate()), "manage_label_associations", {**ASSOCIATION, "operation": operation})
    assert out["error"] == error and "111" in out["hint"]
    assert not mutates(account)


@pytest.mark.parametrize("field,value", [("label_exists", False), ("label_status", "REMOVED"), ("target_exists", False)])
def test_missing_association_resources(account, field, value):
    setattr(account, field, value)
    out = invoke(build_writes(Gate()), "manage_label_associations", ASSOCIATION)
    assert out["error"] == "not_found" and not mutates(account)


def test_duplicate_label_appearing_after_dry_run_is_conflict(account):
    account.label_status = "REMOVED"
    server = build_writes(Gate())
    args = {"operation": "CREATE", "name": "Original"}
    dry = invoke(server, "manage_labels", args)
    account.label_status = "ENABLED"
    assert invoke(server, "manage_labels", args, confirm=dry["confirm"])["error"] == "conflict"
    assert len(mutates(account)) == 1


@pytest.mark.parametrize("kind,entity,stem,plural,segment,identifier", ENTITIES)
def test_video_associations_refused(account, kind, entity, stem, plural, segment, identifier):
    account.channel = "VIDEO"
    out = invoke(build_writes(Gate()), "manage_label_associations", {
        **ASSOCIATION, "association_type": kind, "resource_ids": [identifier]})
    assert out["error"] == "not_supported" and not mutates(account)


@pytest.mark.parametrize("args", [
    {"operation": "BAD"}, {"operation": "CREATE"}, {"operation": "CREATE", "name": "x", "label_id": "7"},
    {"operation": "UPDATE", "label_id": "7"}, {"operation": "UPDATE", "name": "x"},
    {"operation": "REMOVE", "label_id": "7", "name": "x"}, {"operation": "REMOVE", "label_id": "x"},
    {**LABEL, "name": " "}, {**LABEL, "name": "x" * 81}, {**LABEL, "description": "x" * 201},
    {**LABEL, "background_color": "#fffffg"}, {**LABEL, "background_color": "123456"},
])
def test_invalid_labels(account, args):
    assert invoke(build_writes(Gate()), "manage_labels", args)["error"] == "invalid_argument"
    assert account.recorder.requests == []


@pytest.mark.parametrize("patch", [
    {"operation": "UPDATE"}, {"association_type": "AD"}, {"label_id": "x"},
    {"resource_ids": []}, {"resource_ids": [str(i) for i in range(201)]},
    {"resource_ids": ["1", "1"]}, {"resource_ids": ["1 OR 1=1"]},
    {"association_type": "AD_GROUP_CRITERION", "resource_ids": ["11"]},
    {"association_type": "AD_GROUP_CRITERION", "resource_ids": ["1~2~3"]},
    {"association_type": "AD_GROUP_CRITERION", "resource_ids": ["x~2"]},
    {"association_type": "CUSTOMER", "resource_ids": [CUSTOMER]},
])
def test_invalid_associations(account, patch):
    assert invoke(build_writes(Gate()), "manage_label_associations", {**ASSOCIATION, **patch})["error"] == "invalid_argument"
    assert account.recorder.requests == []


@pytest.mark.parametrize("args", [
    {"asset_type": "BAD"}, *[{"asset_type": kind} for kind in ("TEXT", "IMAGE", "YOUTUBE_VIDEO", "SITELINK", "CALLOUT", "STRUCTURED_SNIPPET")],
    {**ASSETS[0], "callout_text": "wrong"}, {**ASSETS[2], "youtube_video_id": "short"},
    {**ASSETS[1], "image_data": "not base64!"}, {**ASSETS[1], "image_data": base64.b64encode(b"not an image").decode()},
    {**ASSETS[1], "image_mime_type": "IMAGE_JPEG"}, {**ASSETS[1], "image_mime_type": "IMAGE_WEBP"},
    {**ASSETS[1], "image_data": base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024 - 7)).decode()},
    {**ASSETS[3], "final_urls": []}, {**ASSETS[3], "sitelink_link_text": "x" * 26},
    {**ASSETS[3], "sitelink_description1": "x" * 36}, {**ASSETS[3], "sitelink_description2": "x" * 36},
    {**ASSETS[4], "callout_text": "x" * 26},
    {**ASSETS[5], "structured_snippet_values": ["a", "b"]},
    {**ASSETS[5], "structured_snippet_values": ["a"] * 11},
    {**ASSETS[5], "structured_snippet_values": ["a", "b", "x" * 26]},
    {**ASSETS[0], "final_urls": ["https://example.com"] * 11},
    {**ASSETS[0], "final_mobile_urls": ["file:///tmp/image"]},
    {**ASSETS[0], "final_urls": ["https://"]}, {**ASSETS[0], "final_urls": ["https://[bad"]},
], ids=lambda arg: str(arg.get("asset_type")))
def test_invalid_assets(account, args):
    assert invoke(build_writes(Gate()), "create_asset", args)["error"] == "invalid_argument"
    assert account.recorder.requests == []


@pytest.mark.parametrize("args", ASSETS)
def test_asset_request_fields(account, args):
    root = {"name": "Named", "final_urls": ["https://example.com"], "final_mobile_urls": ["http://m.example.com"],
            "tracking_url_template": "{lpurl}?tracking=1", "final_url_suffix": "source=ads"}
    out = invoke(build_writes(Gate()), "create_asset", {**args, **root})
    assert out["validated"]
    asset = mutates(account)[0][2]["request"].operations[0].create
    assert asset.name == "Named" and list(asset.final_urls) == root["final_urls"]
    assert list(asset.final_mobile_urls) == root["final_mobile_urls"]
    assert asset.tracking_url_template == root["tracking_url_template"] and asset.final_url_suffix == "source=ads"
    if args["asset_type"] == "IMAGE":
        assert asset.image_asset.data == PNG and asset.image_asset.mime_type.name == "IMAGE_PNG"
    else:
        info = getattr(asset, args["asset_type"].lower() + "_asset")
        for field, value in args.items():
            if field in ("asset_type", "final_urls"):
                continue
            api_field = field.removeprefix("sitelink_").removeprefix("structured_snippet_")
            assert getattr(info, api_field) == value


@pytest.mark.parametrize("mime,data", [("IMAGE_JPEG", b"\xff\xd8\xffdata"), ("IMAGE_GIF", b"GIF87adata"),
                                      ("IMAGE_GIF", b"GIF89adata")])
def test_other_image_signatures(account, mime, data):
    out = invoke(build_writes(Gate()), "create_asset", {"asset_type": "IMAGE", "image_mime_type": mime,
                                                       "image_data": base64.b64encode(data).decode()})
    assert out["validated"]


def test_image_digest_preview_and_logs_never_contain_bytes(account, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    seen = []
    original = gads_mcp._digest

    def digest(value):
        seen.append(value)
        return original(value)

    monkeypatch.setattr(gads_mcp, "_digest", digest)
    server = build_writes(Gate())
    dry = invoke(server, "create_asset", ASSETS[1])
    applied = invoke(server, "create_asset", ASSETS[1], confirm=dry["confirm"])
    serialized = json.dumps([dry, applied, seen]) + caplog.text
    assert IMAGE not in serialized and "private-image-content" not in serialized
    assert dry["changes"][0]["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert dry["changes"][0]["size_bytes"] == len(PNG)
    assert seen[0]["image_data"] == {"sha256": hashlib.sha256(PNG).hexdigest(), "size_bytes": len(PNG)}


def test_image_api_errors_do_not_echo_payload(account, caplog):
    caplog.set_level(logging.DEBUG)
    account.mutate_error = ads_error("asset_error", "UNKNOWN")
    account.mutate_error.failure.errors[0].message = IMAGE
    out = invoke(build_writes(Gate()), "create_asset", ASSETS[1])
    assert out["error"] == "invalid_argument"
    assert IMAGE not in json.dumps(out) + caplog.text


@pytest.mark.parametrize("operation", ["UPDATE", "REMOVE"])
@pytest.mark.parametrize("exists,status", [(False, "ENABLED"), (True, "REMOVED")])
def test_missing_or_removed_label(account, operation, exists, status):
    account.label_exists, account.label_status = exists, status
    args = {"operation": operation, "label_id": "7"}
    if operation == "UPDATE":
        args["description"] = "new"
    assert invoke(build_writes(Gate()), "manage_labels", args)["error"] == "not_found"
    assert not mutates(account)


def test_image_exact_size_limit(account):
    data = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024 - 8)
    out = invoke(build_writes(Gate()), "create_asset", {
        **ASSETS[1], "image_data": base64.b64encode(data).decode()})
    assert out["validated"] and out["changes"][0]["size_bytes"] == 5120 * 1024
