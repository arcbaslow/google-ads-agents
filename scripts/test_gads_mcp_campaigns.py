import copy
import json
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
