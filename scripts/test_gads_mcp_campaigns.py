import copy
import hashlib
import json
import logging
import re

import gads_creation
import gads_mcp
import pytest
from google.api_core import exceptions as api_errors
from test_gads_campaign_writer import APP_SPEC, DG_SPEC, DISPLAY_SPEC, VIDEO_AD
from test_gads_mcp import (  # noqa: F401 (home is an autouse fixture)
    CUSTOMER,
    TYPES,
    ads_error,
    call,
    home,
    install,
    stream,
)
from test_gads_mcp_writes import Account, Gate, build_writes, mutates

VIDEO_SPEC = copy.deepcopy(DG_SPEC)
VIDEO_SPEC["ad"] = VIDEO_AD
VIDEO_SPEC["asset_automation"] = dict.fromkeys(
    gads_creation.DEMAND_GEN_ASSET_AUTOMATION_TYPES["VIDEO_RESPONSIVE"], "OPTED_OUT")
ENGAGEMENT_SPEC = {
    **APP_SPEC, "sub_type": "APP_CAMPAIGN_FOR_ENGAGEMENT",
    "goal_type": "OPTIMIZE_IN_APP_CONVERSIONS_TARGET_CONVERSION_COST",
    "selective_optimization_conversion_actions": ["customers/123/conversionActions/9"],
    "user_list": "customers/123/userLists/5",
}
CASES = [
    ("create_demand_gen_campaign", DG_SPEC), ("create_demand_gen_campaign", VIDEO_SPEC),
    ("create_display_campaign", DISPLAY_SPEC), ("create_app_campaign", APP_SPEC),
    ("create_app_campaign", ENGAGEMENT_SPEC),
]


class CampaignAccount(Account):
    def __init__(self):
        super().__init__()
        self.missing = set()
        self.asset_types = {}
        self.duplicate = False
        self.conversion_status = "ENABLED"
        self.reverse = False

    def rows(self, query):
        resource = re.search(r"FROM (\w+)", query).group(1)
        if resource == "campaign":
            assert "campaign.status != 'REMOVED'" in query
            return [{"campaign": {"id": 42, "name": "Duplicate", "status": "PAUSED"}}] if self.duplicate else []
        names = re.findall(r"'((?:customers/)[^']+)'", query)
        rows = []
        for name in names:
            if name in self.missing:
                continue
            fields = {"resource_name": name}
            if resource == "asset":
                fields["type_"] = self.asset_types.get(name, "YOUTUBE_VIDEO" if name.endswith("/12") else "IMAGE")
            if resource == "conversion_action":
                fields["status"] = self.conversion_status
            rows.append({resource: fields})
        return rows[::-1] if self.reverse else rows

    def respond(self, service, method, kwargs):
        if method == "mutate":
            assert service == "GoogleAdsService"
            if self.mutate_error:
                raise self.mutate_error
            response = TYPES.get_type("MutateGoogleAdsResponse")
            request = kwargs["request"]
            if not request["validate_only"]:
                for i, op in enumerate(request["mutate_operations"]):
                    kind = op._pb.WhichOneof("operation").removesuffix("_operation")
                    response.mutate_operation_responses.append({
                        kind + "_result": {"resource_name": f"customers/{CUSTOMER}/{kind}/{i + 1}"},
                    })
            return response
        return stream(self.rows(kwargs["query"]))


@pytest.fixture
def account(monkeypatch):
    account = CampaignAccount()
    account.recorder = install(monkeypatch.setattr, account.respond)
    return account


@pytest.fixture(params=CASES, ids=[name.removeprefix("create_") + str(i) for i, (name, _) in enumerate(CASES)])
def campaign(request):
    name, base = request.param
    return name, json.loads(json.dumps(base).replace("customers/123/", f"customers/{CUSTOMER}/"))


def invoke(server, campaign, **extra):
    name, spec = campaign
    return call(server, name, customer_id=CUSTOMER, spec=spec, **extra)


def test_dry_run_confirm_and_resource_names(account, campaign):
    gate = Gate()
    server = build_writes(gate)
    dry = invoke(server, campaign)
    assert dry["validated"] is True and dry["dry_run"] is True
    assert dry["confirm_expires_in"] == 600 and re.fullmatch(r"[0-9a-f]{32}", dry["confirm"])
    sent = mutates(account)
    assert len(sent) == 1 and sent[0][:2] == ("GoogleAdsService", "mutate")
    request = sent[0][2]["request"]
    assert request["validate_only"] is True and request["partial_failure"] is False
    assert request["customer_id"] == CUSTOMER
    assert gate.calls == 0
    applied = invoke(server, campaign, confirm=dry["confirm"])
    sent = mutates(account)
    assert len(sent) == 2 and sent[1][2]["request"]["validate_only"] is False
    assert sent[1][2]["request"]["partial_failure"] is False
    assert sent[1][2]["request"]["mutate_operations"] == request["mutate_operations"]
    assert all(kwargs["retry"] is None and kwargs["timeout"] == 60 for _, _, kwargs in sent)
    expected = [f"customers/{CUSTOMER}/{op._pb.WhichOneof('operation').removesuffix('_operation')}/{i + 1}"
                for i, op in enumerate(request["mutate_operations"])]
    assert applied["resource_names"] == expected and applied["applied"] == len(expected)
    assert applied["dry_run"] is False and gate.calls == 1
    assert invoke(server, campaign, confirm=dry["confirm"])["error"] == "invalid_argument"
    assert len(mutates(account)) == 2


def test_reference_row_order_is_not_a_conflict(account, campaign):
    server = build_writes(Gate())
    dry = invoke(server, campaign)
    account.reverse = True
    applied = invoke(server, campaign, confirm=dry["confirm"])
    assert applied["dry_run"] is False and len(mutates(account)) == 2


def test_review_summary(account, campaign):
    result = invoke(build_writes(Gate()), campaign)
    summary = result["changes"][0]
    name, spec = campaign
    assert summary["name"] == spec["name"] and summary["status"] == "PAUSED"
    assert summary["budget_micros"] == spec["budget_micros"] and summary["budget_period"] == "DAILY"
    assert summary["geo_count"] == 1 and summary["language_count"] == 1
    assert summary["ad"]["headlines"] == len(spec["ad"]["headlines"])
    assert summary["ad"]["descriptions"] == len(spec["ad"]["descriptions"])
    assert summary["target_cpa_micros"] == spec["target_cpa_micros"]
    assert summary["target_roas"] == spec["target_roas"]
    assert all(count == len(spec["ad"][slot] or []) for slot, count in summary["ad"]["assets"].items())
    if name == "create_demand_gen_campaign":
        assert summary["channel_controls"] == spec["channel_controls"]
        assert summary["ad"]["type"] == spec["ad"]["type"]
    if name == "create_app_campaign":
        for field in ("sub_type", "app_id", "app_store", "goal_type"):
            assert summary[field] == spec[field]


def test_changed_spec_rejected(account, campaign):
    server = build_writes(Gate())
    dry = invoke(server, campaign)
    campaign[1]["budget_micros"] += 1000000
    out = invoke(server, campaign, confirm=dry["confirm"])
    assert out["error"] == "invalid_argument" and "different request" in out["hint"]
    assert len(mutates(account)) == 1


@pytest.mark.parametrize("change", ["asset_deleted", "asset_type", "duplicate"])
def test_state_conflict(account, campaign, change):
    server = build_writes(Gate())
    dry = invoke(server, campaign)
    if change == "asset_deleted":
        account.missing.add(first_asset(campaign))
    elif change == "asset_type":
        account.asset_types[first_asset(campaign)] = "TEXT"
    else:
        account.duplicate = True
    assert invoke(server, campaign, confirm=dry["confirm"])["error"] == "conflict"
    assert len(mutates(account)) == 1


def test_gate_refusal_keeps_token(account, campaign):
    gate = Gate()
    server = build_writes(gate)
    dry = invoke(server, campaign)
    gate.refusal = {"error": "host_refused", "detail": "unchanged"}
    assert invoke(server, campaign, confirm=dry["confirm"]) == gate.refusal
    assert len(mutates(account)) == 1
    gate.refusal = None
    assert invoke(server, campaign, confirm=dry["confirm"])["applied"] > 0


def test_invalid_spec_sends_nothing(account, campaign):
    campaign[1]["budget_micros"] = 0
    out = invoke(build_writes(Gate()), campaign)
    assert out["error"] == "invalid_argument" and "budget_micros" in out["hint"]
    assert account.recorder.requests == []


def first_asset(campaign):
    return next(asset for key, assets in campaign[1]["ad"].items()
                if key in ("marketing_images", "logo_images", "images", "videos") for asset in assets or [])


def test_missing_asset(account, campaign):
    asset = first_asset(campaign)
    account.missing.add(asset)
    out = invoke(build_writes(Gate()), campaign)
    assert out["error"] == "not_found" and asset in out["hint"]
    assert not mutates(account)


def test_wrong_asset_type(account, campaign):
    asset = first_asset(campaign)
    account.asset_types[asset] = "TEXT"
    out = invoke(build_writes(Gate()), campaign)
    assert out["error"] == "invalid_argument" and asset in out["hint"]
    assert not mutates(account)


def test_existing_campaign(account, campaign):
    account.duplicate = True
    out = invoke(build_writes(Gate()), campaign)
    assert out["error"] == "invalid_argument" and "42" in out["hint"]
    assert not mutates(account)


def test_escaped_campaign_name(account, campaign):
    campaign[1]["name"] = "a'\\b"
    assert invoke(build_writes(Gate()), campaign)["validated"]
    queries = [kwargs["query"] for _, method, kwargs in account.recorder.requests if method == "search_stream"]
    assert "campaign.name = 'a\\'\\\\b'" in queries[-1]


@pytest.mark.parametrize("resource", ["conversionActions/9", "userLists/5"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_app_missing_references(account, resource, confirmed):
    campaign = ("create_app_campaign", json.loads(json.dumps(ENGAGEMENT_SPEC).replace(
        "customers/123/", f"customers/{CUSTOMER}/")))
    server = build_writes(Gate())
    dry = invoke(server, campaign) if confirmed else None
    account.missing.add(f"customers/{CUSTOMER}/{resource}")
    result = invoke(server, campaign, **({"confirm": dry["confirm"]} if confirmed else {}))
    assert result["error"] == ("conflict" if confirmed else "not_found")
    assert len(mutates(account)) == int(confirmed)


@pytest.mark.parametrize("confirmed", [False, True])
def test_app_removed_conversion(account, confirmed):
    campaign = ("create_app_campaign", json.loads(json.dumps(ENGAGEMENT_SPEC).replace(
        "customers/123/", f"customers/{CUSTOMER}/")))
    server = build_writes(Gate())
    dry = invoke(server, campaign) if confirmed else None
    account.conversion_status = "REMOVED"
    result = invoke(server, campaign, **({"confirm": dry["confirm"]} if confirmed else {}))
    assert result["error"] == ("conflict" if confirmed else "not_found")
    assert len(mutates(account)) == int(confirmed)


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("error,category", [
    (api_errors.DeadlineExceeded("private"), "upstream_error"),
    (api_errors.PermissionDenied("private"), "permission_denied"),
    (ads_error("asset_error", "UNKNOWN"), "invalid_argument"),
])
def test_atomic_error_classification(account, confirmed, error, category):
    campaign = ("create_display_campaign", json.loads(json.dumps(DISPLAY_SPEC).replace(
        "customers/123/", f"customers/{CUSTOMER}/")))
    server = build_writes(Gate())
    dry = invoke(server, campaign) if confirmed else None
    account.mutate_error = error
    result = invoke(server, campaign, **({"confirm": dry["confirm"]} if confirmed else {}))
    assert result["error"] == category and "private" not in json.dumps(result)
    if confirmed and category == "upstream_error":
        assert result["hint"] == gads_mcp._UNKNOWN_OUTCOME
    if category == "invalid_argument":
        assert result["errors"][0]["code"] == "asset_error.UNKNOWN"
    assert len(mutates(account)) == 1 + int(confirmed)


class Uploads:
    def __init__(self):
        self.data = b"\x89PNG\r\n\x1a\nexample"
        self.available = True
        self.mime_type = "IMAGE_PNG"
        self.reads = []
        self.discards = []

    def read(self, handle, profile, customer_id):
        self.reads.append((handle, profile, customer_id))
        if not self.available or handle != "image-handle":
            raise KeyError("private upload error")
        return {"data": self.data, "mime_type": self.mime_type, "size_bytes": len(self.data),
                "sha256": hashlib.sha256(self.data).hexdigest()}

    def discard(self, handles):
        self.discards.append(handles)


class ChangeSetAccount(CampaignAccount):
    def __init__(self):
        super().__init__()
        self.budget = 1000000
        self.campaign_name = "Generic"
        self.status = "ENABLED"
        self.reference_count = 1
        self.currency = "USD"
        self.removed = False
        self.shared = []

    def rows(self, query):
        table = re.search(r"FROM (\w+)", query).group(1)
        if table == "customer":
            return [{"customer": {"id": int(CUSTOMER), "currency_code": self.currency}}]
        if table == "campaign" and "campaign.name =" in query:
            return super().rows(query)
        if table in ("asset", "conversion_action", "user_list"):
            return super().rows(query)
        if self.removed:
            return []
        if "campaign.campaign_budget =" in query:
            assert f"'customers/{CUSTOMER}/campaignBudgets/555'" in query and "!= 'REMOVED'" in query
            return [{"campaign": {"id": i, "name": name}} for i, name in [(111, self.campaign_name), *self.shared]]
        campaign = {"id": 111, "resource_name": f"customers/{CUSTOMER}/campaigns/111",
                    "name": self.campaign_name, "status": self.status, "advertising_channel_type": self.channel,
                    "campaign_budget": f"customers/{CUSTOMER}/campaignBudgets/555"}
        if table == "campaign":
            budget = {"resource_name": campaign["campaign_budget"], "reference_count": self.reference_count}
            if self.budget is not None:
                budget["amount_micros"] = self.budget
            return [{"campaign": campaign, "campaign_budget": budget}]
        values = {
            "ad_group": {"id": 222, "resource_name": f"customers/{CUSTOMER}/adGroups/222", "name": "Group"},
            "ad_group_criterion": {"criterion_id": 11, "resource_name": f"customers/{CUSTOMER}/adGroupCriteria/222~11",
                                   "keyword": {"text": "example", "match_type": "EXACT"}},
            "ad_group_ad": {"ad": {"id": 21, "name": "Ad"},
                            "resource_name": f"customers/{CUSTOMER}/adGroupAds/222~21"},
        }
        return [{"campaign": campaign, table: {**values[table], "status": self.status}}]


@pytest.fixture
def changes(monkeypatch):
    account = ChangeSetAccount()
    account.recorder = install(monkeypatch.setattr, account.respond)
    uploads, gate = Uploads(), Gate()
    return account, uploads, gate, build_writes(gate, uploads=uploads)


def change_operations():
    spec = copy.deepcopy(DISPLAY_SPEC)
    spec["ad"].update(marketing_images=["$picture"], square_marketing_images=["$picture"],
                      logo_images=[], square_logo_images=[])
    return [
        {"op": "add_negative_keywords", "campaign_id": "$launch",
         "keywords": [{"text": "free", "match_type": "PHRASE"}]},
        {"op": "create_campaign", "id": "launch", "kind": "DISPLAY", "spec": spec,
         "exempt_policies": ["EXAMPLE_POLICY"]},
        {"op": "create_asset", "id": "picture", "type": "IMAGE", "name": "Picture", "upload": "image-handle"},
    ]


def plan(server, operations=None, **kwargs):
    return call(server, "plan_changes", customer_id=CUSTOMER,
                operations=change_operations() if operations is None else operations, **kwargs)


def test_change_set_wires_assets_and_applies_once(changes):
    account, uploads, gate, server = changes
    operations = change_operations()
    dry = plan(server, operations, profile="work")
    assert dry["validated"] and dry["currency"] == "USD" and gate.calls == 0
    assert [entry["op"] for entry in dry["diff"]] == [operation["op"] for operation in operations]
    assert dry["diff"][2]["sha256"] == hashlib.sha256(uploads.data).hexdigest()
    assert dry["diff"][2]["mime_type"] == "IMAGE_PNG"
    assert dry["diff"][2]["size_bytes"] == len(uploads.data)
    assert dry["diff"][1]["status"] == "PAUSED"
    assert "image-handle" not in json.dumps(dry)
    built = mutates(account)[0][2]["request"]["mutate_operations"]
    assert built[0].asset_operation.create.resource_name == f"customers/{CUSTOMER}/assets/-10"
    assert built[2].campaign_operation.create.status.name == "PAUSED"
    assert built[3].ad_group_operation.create.status.name == "ENABLED"
    ad = built[-2].ad_group_ad_operation
    assert ad.create.status.name == "ENABLED"
    assert ad.create.ad.responsive_display_ad.marketing_images[0].asset == built[0].asset_operation.create.resource_name
    assert list(ad.policy_validation_parameter.ignorable_policy_topics) == ["EXAMPLE_POLICY"]
    assert built[-1].campaign_criterion_operation.create.campaign == f"customers/{CUSTOMER}/campaigns/-2"
    operations[1]["spec"]["name"] = "Changed after planning"
    applied = call(server, "apply_changes", confirm=dry["confirm"], profile="work")
    assert applied["dry_run"] is False and applied["applied"] == len(built)
    assert applied["created"] == {"picture": f"customers/{CUSTOMER}/asset/1",
                                   "launch": f"customers/{CUSTOMER}/campaign/3"}
    assert gate.profile == "work" and gate.calls == 1
    assert uploads.reads == [("image-handle", "work", CUSTOMER)] * 2
    assert uploads.discards == [["image-handle"]]
    assert mutates(account)[1][2]["request"]["mutate_operations"] == built
    assert call(server, "apply_changes", confirm=dry["confirm"], profile="work")["error"] == "invalid_argument"
    assert len(mutates(account)) == 2 and uploads.discards == [["image-handle"]]


def test_change_set_upload_mime_type_binding(changes):
    account, uploads, _, server = changes
    dry = plan(server)
    uploads.mime_type = "IMAGE_JPEG"
    out = call(server, "apply_changes", confirm=dry["confirm"])
    assert out["error"] == "invalid_argument" and len(mutates(account)) == 1 and not uploads.discards


def test_change_set_built_request_cap(changes):
    account, _, _, server = changes
    operations = [{"op": "set_status", "resource": "campaign", "ids": [str(n) for n in range(100 * k, 100 * k + 100)],
                   "status": "PAUSED"} for k in range(1, 4)]
    out = plan(server, operations)
    assert out["error"] == "invalid_argument" and "more than 200 mutate operations" in out["hint"]
    assert account.recorder.requests == []


def test_change_set_apply_logs_apply_changes(changes, caplog):
    _, _, _, server = changes
    caplog.set_level(logging.INFO)
    dry = plan(server)
    assert not [r for r in caplog.records if "ads write" in r.getMessage()]
    call(server, "apply_changes", confirm=dry["confirm"])
    lines = [r.getMessage() for r in caplog.records if "ads write" in r.getMessage()]
    assert lines == [f"ads write apply_changes customers/{CUSTOMER} outcome=ok"]


def test_change_set_upload_digest(changes):
    account, uploads, _, server = changes
    dry = plan(server)
    uploads.data += b"changed"
    out = call(server, "apply_changes", confirm=dry["confirm"])
    assert out["error"] == "invalid_argument" and "different request" in out["hint"]
    assert len(mutates(account)) == 1 and not uploads.discards
    assert dry["confirm"] not in gads_mcp._pending


def test_change_set_gate_refusal_preserves_token(changes):
    account, uploads, gate, server = changes
    dry = plan(server, profile="work")
    gate.refusal = {"error": "host_closed", "hint": "review required"}
    assert call(server, "apply_changes", confirm=dry["confirm"], profile="work") == gate.refusal
    assert gate.profile == "work" and dry["confirm"] in gads_mcp._pending
    assert len(mutates(account)) == 1 and not uploads.discards
    gate.refusal = None
    assert call(server, "apply_changes", confirm=dry["confirm"], profile="work")["applied"]


@pytest.mark.parametrize("resource,ids", [("campaign", ["111"]), ("ad_group", ["222"]),
                                         ("keyword", ["222~11"]), ("ad", ["222~21"])])
def test_change_set_status_and_conflict(changes, resource, ids):
    account, _, _, server = changes
    dry = plan(server, [{"op": "set_status", "resource": resource, "ids": ids, "status": "PAUSED"}])
    change = dry["diff"][0]["changes"][0]
    assert change["from"] == "ENABLED" and change["to"] == "PAUSED"
    if resource == "keyword":
        assert change["text"] == "example" and change["match_type"] == "EXACT"
    else:
        assert change["name"]
    account.status = "PAUSED"
    assert call(server, "apply_changes", confirm=dry["confirm"])["error"] == "conflict"
    assert len(mutates(account)) == 1


@pytest.mark.parametrize("field,value", [("budget", 900000), ("reference_count", 2), ("currency", "EUR"),
                                        ("channel", "VIDEO"), ("removed", True)])
def test_change_set_budget_conflict(changes, field, value):
    account, _, _, server = changes
    dry = plan(server, [{"op": "update_budget", "campaign_id": "111", "amount_micros": 2000000}])
    assert dry["diff"][0]["from_micros"] == 1000000
    assert dry["diff"][0]["to_micros"] == 2000000
    assert dry["diff"][0]["currency"] == "USD" and dry["diff"][0]["reference_count"] == 1
    setattr(account, field, value)
    assert call(server, "apply_changes", confirm=dry["confirm"])["error"] == "conflict"
    assert len(mutates(account)) == 1


def test_change_set_brand_budget_guard_and_override(changes, monkeypatch):
    account, _, _, server = changes
    monkeypatch.setattr("gads_brandguard.is_brand_campaign", lambda name, rules: True)
    operation = {"op": "update_budget", "campaign_id": "111", "amount_micros": 2000000}
    assert plan(server, [operation])["error"] == "permission_denied"
    assert not mutates(account)
    dry = plan(server, [{**operation, "owner_approved_brand_scale": True}])
    assert dry["diff"][0]["brand"] is True
    assert call(server, "apply_changes", confirm=dry["confirm"])["applied"] == 1
    assert plan(server, [{**operation, "amount_micros": 500000}])["validated"]


def test_change_set_shared_budget_brand_guard(changes, monkeypatch):
    account, _, _, server = changes
    account.shared = [(112, "Paused brand")]
    monkeypatch.setattr("gads_brandguard.is_brand_campaign", lambda name, rules: name == "Paused brand")
    operation = {"op": "update_budget", "campaign_id": "111", "amount_micros": 2000000}
    assert plan(server, [operation])["error"] == "permission_denied"
    dry = plan(server, [{**operation, "owner_approved_brand_scale": True}])
    assert dry["diff"][0]["brand"] is True and dry["diff"][0]["shared_with"] == ["Paused brand"]
    account.shared.append((113, "Joined later"))
    assert call(server, "apply_changes", confirm=dry["confirm"])["error"] == "conflict"
    assert len(mutates(account)) == 1


def test_change_set_brand_by_search_term_share(changes, monkeypatch):
    account, _, _, server = changes
    monkeypatch.setattr("gads_brandguard.brand_shares", lambda cid, rules: {"111": {"share": 0.9}})
    operation = {"op": "update_budget", "campaign_id": "111", "amount_micros": 2000000}
    assert plan(server, [operation])["error"] == "permission_denied"
    assert plan(server, [{**operation, "owner_approved_brand_scale": True}])["diff"][0]["brand"] is True
    assert len(mutates(account)) == 1


def test_non_change_set_dry_run_stores_no_arguments(account, campaign):
    dry = invoke(build_writes(Gate()), campaign)
    assert gads_mcp._pending[dry["confirm"]][3] == {}


def test_change_set_budget_without_daily_amount(changes):
    account, _, _, server = changes
    account.budget = None
    out = plan(server, [{"op": "update_budget", "campaign_id": "111", "amount_micros": 2000000}])
    assert out["error"] == "not_supported" and out["hint"] == "Operation 0: this budget has no daily amount."
    assert not mutates(account)


def test_change_set_discard_failure_keeps_success(changes, caplog):
    account, uploads, _, server = changes

    def discard(handles):
        raise RuntimeError("private store error")

    uploads.discard = discard
    dry = plan(server)
    applied = call(server, "apply_changes", confirm=dry["confirm"])
    assert applied["dry_run"] is False and applied["created"]["launch"]
    assert "upload discard failed" in caplog.text and "private" not in caplog.text


def test_change_set_rejects_raw_temporary_asset_name(changes):
    account, _, _, server = changes
    operations = change_operations()
    operations[1]["spec"]["ad"]["marketing_images"] = [f"customers/{CUSTOMER}/assets/-10"]
    out = plan(server, operations)
    assert out["error"] == "invalid_argument" and "Operation 1" in out["hint"]
    assert not mutates(account)


def test_display_campaign_refuses_temporary_asset_name(account):
    spec = json.loads(json.dumps(DISPLAY_SPEC).replace("customers/123/", f"customers/{CUSTOMER}/"))
    spec["ad"]["marketing_images"] = [f"customers/{CUSTOMER}/assets/-10"]
    out = call(build_writes(Gate()), "create_display_campaign", customer_id=CUSTOMER, spec=spec)
    assert out["error"] == "invalid_argument" and account.recorder.requests == []


@pytest.mark.parametrize("resource,ids", [("campaign", ["111"]), ("ad_group", ["222"]),
                                         ("keyword", ["222~11"]), ("ad", ["222~21"])])
def test_change_set_video_refusal(changes, resource, ids):
    account, _, _, server = changes
    account.channel = "VIDEO"
    out = plan(server, [{"op": "set_status", "resource": resource, "ids": ids, "status": "PAUSED"}])
    assert out["error"] == "not_supported" and not mutates(account)


@pytest.mark.parametrize("change", ["unknown_op", "unknown_field", "unknown_spec_field", "bad_ref",
                                   "bad_id", "duplicate_id", "two_campaigns", "bad_keyword_id"])
def test_change_set_rejects_invalid_operation(changes, change):
    account, _, _, server = changes
    operations = change_operations()
    index = 1
    if change == "unknown_op":
        operations[index]["op"] = "private_invalid_op"
    elif change == "unknown_field":
        operations[index]["private_field"] = "private_value"
    elif change == "unknown_spec_field":
        operations[index]["spec"]["private_field"] = "private_value"
    elif change == "bad_ref":
        operations[index]["spec"]["ad"]["marketing_images"] = ["$private_reference"]
    elif change == "bad_id":
        operations[index]["id"] = "private invalid id"
    elif change == "duplicate_id":
        index = 2
        operations[index]["id"] = operations[1]["id"]
    elif change == "two_campaigns":
        index = 3
        operations.append({**operations[1], "id": "second"})
    else:
        operations[0]["campaign_id"] = "111"
        operations[index] = {"op": "set_status", "resource": "keyword", "ids": ["11"], "status": "PAUSED"}
    out = plan(server, operations)
    assert out["error"] == "invalid_argument" and f"Operation {index}" in out["hint"]
    assert "private" not in json.dumps(out) and not mutates(account)


@pytest.mark.parametrize("missing", ["unknown", "no_store", "expired_after_plan"])
def test_change_set_missing_upload(changes, missing):
    account, uploads, gate, server = changes
    if missing == "expired_after_plan":
        dry = plan(server)
        uploads.available = False
        out = call(server, "apply_changes", confirm=dry["confirm"])
    else:
        uploads.available = False
        if missing == "no_store":
            server = build_writes(gate)
        out = plan(server)
    assert out["error"] == ("invalid_argument" if missing == "no_store" else "not_found")
    assert "Operation 2" in out["hint"] and "image-handle" not in json.dumps(out)
    if missing == "no_store":
        assert "this host has no upload store" in out["hint"]
    assert len(mutates(account)) == int(missing == "expired_after_plan") and not uploads.discards


def test_change_set_maps_api_errors_and_policy_details(changes):
    account, _, _, server = changes
    error = ads_error("policy_finding_error", "POLICY_FINDING", "private request values")
    item = error.failure.errors[0]
    item.location.field_path_elements.extend([{"field_name": "mutate_operations", "index": 6},
                                              {"field_name": "ad_group_ad_operation"}])
    item.details.policy_finding_details.policy_topic_entries.append({"topic": "EXAMPLE_POLICY", "type_": "LIMITED"})
    account.mutate_error = error
    before = set(gads_mcp._pending)
    out = plan(server)
    assert out["error"] == "invalid_argument"
    assert out["errors"] == [{"code": "policy_finding_error.POLICY_FINDING",
                               "field_path": "mutate_operations[6].ad_group_ad_operation", "op_index": 1,
                               "exemptible": True, "policy_topics": ["EXAMPLE_POLICY"]}]
    assert "private" not in json.dumps(out) and set(gads_mcp._pending) == before


def test_change_set_youtube_asset_without_store(changes):
    account, _, gate, _ = changes
    server = build_writes(gate)
    dry = plan(server, [{"op": "create_asset", "id": "video", "type": "YOUTUBE_VIDEO",
                         "name": "Video", "youtube_video_id": "abcdefghijk"}])
    assert dry["validated"]
    op = mutates(account)[0][2]["request"]["mutate_operations"][0]
    assert op.asset_operation.create.youtube_video_asset.youtube_video_id == "abcdefghijk"
    assert call(server, "apply_changes", confirm=dry["confirm"])["created"]["video"]


@pytest.mark.parametrize("case", ["expired", "wrong_profile", "wrong_tool"])
def test_change_set_token_binding(changes, monkeypatch, case):
    account, uploads, _, server = changes
    dry = plan(server, profile="work")
    profile = "work"
    if case == "expired":
        now = gads_mcp.time.monotonic()
        monkeypatch.setattr(gads_mcp.time, "monotonic", lambda: now + 601)
    elif case == "wrong_profile":
        profile = "other"
    else:
        entry = gads_mcp._pending[dry["confirm"]]
        gads_mcp._pending[dry["confirm"]] = (*entry[:3], {**entry[3], "tool": "create_asset"})
    out = call(server, "apply_changes", confirm=dry["confirm"], profile=profile)
    assert out["error"] == "invalid_argument" and len(mutates(account)) == 1
    assert not uploads.discards


@pytest.mark.parametrize("kind", ["APP", "DEMAND_GEN"])
def test_change_set_other_campaign_builders(changes, kind):
    account, _, _, server = changes
    spec = json.loads(json.dumps(APP_SPEC if kind == "APP" else DG_SPEC).replace(
        "customers/123/", f"customers/{CUSTOMER}/"))
    dry = plan(server, [{"op": "create_campaign", "id": "launch", "kind": kind, "spec": spec}])
    assert dry["validated"] and dry["diff"][0]["campaign_type"] == kind
    built = mutates(account)[0][2]["request"]["mutate_operations"]
    assert built[2].ad_group_operation.create.status.name == "ENABLED"
    assert built[-1].ad_group_ad_operation.create.status.name == "ENABLED"


def test_change_set_video_campaign_creation_is_unsupported(changes):
    account, _, _, server = changes
    operations = change_operations()
    operations[1]["kind"] = "VIDEO"
    assert plan(server, operations)["error"] == "not_supported" and not mutates(account)


def test_policy_violation_details_do_not_echo_text():
    error = ads_error("policy_violation_error", "POLICY_ERROR", "private message")
    detail = error.failure.errors[0].details.policy_violation_details
    detail.is_exemptible = True
    detail.key.policy_name = "EXAMPLE_POLICY"
    detail.key.violating_text = "private text"
    out = gads_mcp._api_errors(error)
    assert out == [{"code": "policy_violation_error.POLICY_ERROR", "field_path": None, "op_index": None,
                    "exemptible": True, "policy_topics": ["EXAMPLE_POLICY"]}]
    assert "private" not in json.dumps(out)
