"""MCP read tools for keywords, ads, search terms and asset groups, and the gated write tools."""

from __future__ import annotations

import asyncio
import json
import logging
import re

import gads_mcp
import pytest
from google.api_core import exceptions as api_errors
from mcp.server.fastmcp import FastMCP
from test_gads_mcp import (  # noqa: F401  (home is an autouse fixture)
    CUSTOMER,
    SECRETS,
    TYPES,
    FakeProvider,
    ads_error,
    call,
    home,
    install,
    stream,
)

AD_GROUP = "222"
CAMPAIGN = "111"
RESPONSES = {
    "mutate_ad_group_criteria": "MutateAdGroupCriteriaResponse",
    "mutate_ad_group_ads": "MutateAdGroupAdsResponse",
    "mutate_campaigns": "MutateCampaignsResponse",
    "mutate_conversion_actions": "MutateConversionActionsResponse",
    "mutate_campaign_criteria": "MutateCampaignCriteriaResponse",
    "mutate_asset_group_assets": "MutateAssetGroupAssetsResponse",
}

WRITES = [
    ("set_keyword_status",
     {"customer_id": CUSTOMER, "ad_group_id": AD_GROUP, "criterion_ids": ["11", "12"],
      "status": "PAUSED"},
     "AdGroupCriterionService", "mutate_ad_group_criteria", 2),
    ("set_ad_status",
     {"customer_id": CUSTOMER, "ad_group_id": AD_GROUP, "ad_ids": ["21"], "status": "PAUSED"},
     "AdGroupAdService", "mutate_ad_group_ads", 1),
    ("update_campaign_schedule",
     {"customer_id": CUSTOMER, "campaign_id": CAMPAIGN, "end_date": "2027-01-31"},
     "CampaignService", "mutate_campaigns", 1),
    ("set_conversion_action_goal",
     {"customer_id": CUSTOMER, "conversion_action_id": "31", "primary": False},
     "ConversionActionService", "mutate_conversion_actions", 1),
    ("add_placement_exclusions",
     {"customer_id": CUSTOMER, "campaign_id": CAMPAIGN, "placements": ["example.com"],
      "youtube_channel_ids": ["UCexample0000000000000001"], "youtube_video_ids": ["abcdefghijk"],
      "mobile_app_ids": ["2-com.example.app"]},
     "CampaignCriterionService", "mutate_campaign_criteria", 4),
    ("update_asset_group_assets",
     {"customer_id": CUSTOMER, "asset_group_id": "41",
      "add": [{"asset_id": "52", "field_type": "HEADLINE"}],
      "remove": [{"asset_id": "51", "field_type": "HEADLINE"}]},
     "AssetGroupAssetService", "mutate_asset_group_assets", 2),
]
WRITE_NAMES = [name for name, *_ in WRITES]


class Account:
    """Fake account state behind the GoogleAdsService reads and the mutate services."""

    def __init__(self):
        self.channel = "DEMAND_GEN"
        self.keyword_status = "ENABLED"
        self.mutate_error: Exception | None = None

    def rows(self, query):
        resource = re.search(r"FROM (\w+)", query).group(1)
        campaign = {"id": int(CAMPAIGN), "advertising_channel_type": self.channel}
        if resource == "ad_group_criterion":
            return [{"campaign": campaign, "ad_group": {"id": int(AD_GROUP)},
                     "ad_group_criterion": {"criterion_id": n, "status": self.keyword_status,
                                            "keyword": {"text": f"example term {n}",
                                                        "match_type": "PHRASE"}}}
                    for n in (11, 12)]
        if resource == "ad_group_ad":
            return [{"campaign": campaign, "ad_group": {"id": int(AD_GROUP)},
                     "ad_group_ad": {"status": "ENABLED",
                                     "ad": {"id": 21, "type_": "RESPONSIVE_SEARCH_AD",
                                            "final_urls": ["https://example.com/"]},
                                     "policy_summary": {"approval_status": "APPROVED"}}}]
        if resource == "campaign":
            return [{"campaign": {**campaign, "status": "ENABLED",
                                  "start_date_time": "2026-10-01 00:00:00",
                                  "end_date_time": "2026-12-31 23:59:59"}}]
        if resource == "conversion_action":
            return [{"conversion_action": {"id": 31, "name": "Example purchase",
                                           "status": "ENABLED", "category": "PURCHASE",
                                           "primary_for_goal": True}}]
        if resource == "asset_group":
            return [{"campaign": {**campaign, "advertising_channel_type": "PERFORMANCE_MAX"},
                     "asset_group": {"id": 41, "status": "ENABLED"}}]
        if resource == "asset_group_asset":
            return [{"campaign": {"id": int(CAMPAIGN)}, "asset_group": {"id": 41},
                     "asset": {"id": 51, "type_": "TEXT", "text_asset": {"text": "Example"}},
                     "asset_group_asset": {"field_type": "HEADLINE", "status": "ENABLED",
                                           "primary_status": "ELIGIBLE"}}]
        if resource == "search_term_view":
            return [{"search_term_view": {"search_term": "example query", "status": "NONE"},
                     "campaign": {"id": int(CAMPAIGN)}, "ad_group": {"id": int(AD_GROUP)},
                     "segments": {"keyword": {
                         "ad_group_criterion": f"customers/{CUSTOMER}/adGroupCriteria/222~11",
                         "info": {"text": "example term 11", "match_type": "PHRASE"}}},
                     "metrics": {"cost_micros": 1_500_000, "clicks": 3, "impressions": 40,
                                 "conversions": 1.0}}] * 3
        return []

    def respond(self, service, method, kwargs):
        if method in RESPONSES:
            if self.mutate_error is not None:
                raise self.mutate_error
            request = kwargs["request"]
            response = TYPES.get_type(RESPONSES[method])
            if not request.validate_only:
                response.results.extend([{"resource_name": f"customers/{CUSTOMER}/x/{n}"}
                                         for n in range(len(request.operations))])
            return response
        return stream(self.rows(kwargs["query"]))


@pytest.fixture
def account(monkeypatch):
    state = Account()
    recorder = install(monkeypatch.setattr, state.respond)
    recorder.client_class.enums = TYPES.enums
    state.recorder = recorder
    return state


class Gate:
    def __init__(self, refusal=None):
        self.calls = 0
        self.refusal = refusal

    def __call__(self):
        self.calls += 1
        return self.refusal


def build_writes(gate, provider_factory=lambda profile: FakeProvider(), prefix=""):
    server = FastMCP("test")
    gads_mcp.register_writes(server, gate, prefix=prefix, provider_factory=provider_factory)
    return server


def mutates(account):
    return [(service, method, kwargs) for service, method, kwargs in account.recorder.requests
            if method.startswith("mutate")]


def test_keywords_return_ids_for_status_changes(account):
    server = FastMCP("reads")
    gads_mcp.register(server, provider_factory=lambda profile: FakeProvider())
    out = call(server, "keywords", customer_id=CUSTOMER, ad_group_id=AD_GROUP, limit=1)
    query = account.recorder.requests[0][2]["query"]
    assert "ad_group_criterion.type = 'KEYWORD'" in query and "negative = FALSE" in query
    assert "status != 'REMOVED'" in query and f"ad_group.id = {AD_GROUP}" in query
    assert query.endswith("LIMIT 2")
    assert out["keywords"] == [{"criterion_id": "11", "ad_group_id": AD_GROUP,
                                "campaign_id": CAMPAIGN, "text": "example term 11",
                                "match_type": "PHRASE", "status": "ENABLED"}]
    assert out["rows_returned"] == 1 and out["complete"] is False
    paused = call(server, "keywords", customer_id=CUSTOMER, status="PAUSED")
    assert "ad_group_criterion.status = 'PAUSED'" in account.recorder.requests[1][2]["query"]
    assert paused["complete"] is True


def test_ads_shape(account):
    server = FastMCP("reads")
    gads_mcp.register(server, provider_factory=lambda profile: FakeProvider())
    out = call(server, "ads", customer_id=CUSTOMER, campaign_id=CAMPAIGN)
    assert f"campaign.id = {CAMPAIGN}" in account.recorder.requests[0][2]["query"]
    assert out["ads"] == [{"ad_id": "21", "ad_group_id": AD_GROUP, "campaign_id": CAMPAIGN,
                           "type": "RESPONSIVE_SEARCH_AD", "status": "ENABLED",
                           "approval_status": "APPROVED",
                           "final_urls": ["https://example.com/"]}]
    assert out["complete"] is True


def test_search_terms_report(account):
    server = FastMCP("reads")
    gads_mcp.register(server, provider_factory=lambda profile: FakeProvider())
    out = call(server, "search_terms", customer_id=CUSTOMER, date_from="2026-10-01",
               date_to="2026-10-07", limit=2)
    query = account.recorder.requests[0][2]["query"]
    assert "segments.date BETWEEN '2026-10-01' AND '2026-10-07'" in query
    assert "ORDER BY metrics.cost_micros DESC LIMIT 3" in query
    assert out["search_terms"][0] == {
        "search_term": "example query", "status": "NONE", "campaign_id": CAMPAIGN,
        "ad_group_id": AD_GROUP, "keyword_text": "example term 11",
        "keyword_match_type": "PHRASE", "keyword_criterion_id": "11", "cost_micros": 1_500_000,
        "clicks": 3, "impressions": 40, "conversions": 1.0}
    assert out["rows_returned"] == 2 and out["complete"] is False


@pytest.mark.parametrize("args", [
    {"date_from": "2026-10-08", "date_to": "2026-10-07"},
    {"date_from": "yesterday", "date_to": "2026-10-07"},
    {"date_from": "2026-02-30", "date_to": "2026-03-01"},
])
def test_search_terms_reject_bad_dates(account, args):
    server = FastMCP("reads")
    gads_mcp.register(server, provider_factory=lambda profile: FakeProvider())
    out = call(server, "search_terms", customer_id=CUSTOMER, **args)
    assert out["error"] == "invalid_argument"
    assert account.recorder.requests == []


def test_asset_group_assets_shape(account):
    server = FastMCP("reads")
    gads_mcp.register(server, provider_factory=lambda profile: FakeProvider())
    out = call(server, "asset_group_assets", customer_id=CUSTOMER, asset_group_id="41")
    query = account.recorder.requests[0][2]["query"]
    assert "PERFORMANCE_MAX" in query and "asset_group.id = 41" in query
    assert out["assets"] == [{"campaign_id": CAMPAIGN, "asset_group_id": "41",
                              "field_type": "HEADLINE", "asset_id": "51", "asset_type": "TEXT",
                              "name": None, "text": "Example", "status": "ENABLED",
                              "primary_status": "ELIGIBLE"}]


@pytest.mark.parametrize("name,args", [
    ("keywords", {"status": "DELETED"}),
    ("keywords", {"ad_group_id": "1 OR 1=1"}),
    ("ads", {"campaign_id": "x"}),
    ("asset_group_assets", {"limit": 501}),
])
def test_read_filters_are_validated(account, name, args):
    server = FastMCP("reads")
    gads_mcp.register(server, provider_factory=lambda profile: FakeProvider())
    assert call(server, name, customer_id=CUSTOMER, **args)["error"] == "invalid_argument"
    assert account.recorder.requests == []


@pytest.mark.parametrize("prefix", ["", "ads_"])
def test_write_inventory(prefix):
    server = FastMCP("test")
    assert gads_mcp.register_writes(server, Gate(), prefix=prefix) == len(WRITES)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == {prefix + name for name in WRITE_NAMES}
    for name, tool in tools.items():
        assert tool.title and tool.description
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.idempotentHint is False
        assert tool.annotations.openWorldHint is True
        assert tool.annotations.destructiveHint is (name == prefix + "update_asset_group_assets")
        assert {"profile", "confirm"} <= set(tool.inputSchema["properties"])
        assert "gate" not in tool.inputSchema["properties"]


def test_register_writes_needs_a_callable_gate():
    with pytest.raises(TypeError):
        gads_mcp.register_writes(FastMCP("test"), None)


@pytest.mark.parametrize("name,args,service,method,count", WRITES, ids=WRITE_NAMES)
def test_dry_run_validates_and_confirm_sends_once(account, caplog, name, args, service, method,
                                                  count):
    caplog.set_level(logging.INFO)
    gate = Gate()
    server = build_writes(gate)
    dry = call(server, name, **args)
    assert dry["dry_run"] is True and dry["validated"] is True
    assert re.fullmatch(r"[0-9a-f]{32}", dry["confirm"]) and dry["confirm_expires_in"] == 600
    assert gate.calls == 0
    sent = mutates(account)
    assert [(s, m) for s, m, _ in sent] == [(service, method)]
    request = sent[0][2]["request"]
    assert request.validate_only is True and len(request.operations) == count
    assert sent[0][2]["retry"] is None
    assert sent[0][2]["timeout"] == gads_mcp._WRITE_TIMEOUT_SECONDS

    done = call(server, name, **args, confirm=dry["confirm"])
    assert done["dry_run"] is False and done["applied"] == count
    assert gate.calls == 1
    sent = mutates(account)
    assert len(sent) == 2 and sent[1][2]["request"].validate_only is False
    assert sent[1][2]["retry"] is None
    assert sent[1][2]["timeout"] == gads_mcp._WRITE_TIMEOUT_SECONDS
    assert sent[1][2]["request"].operations == request.operations
    lines = [r.getMessage() for r in caplog.records if " write " in r.getMessage()]
    assert lines == [f"gads write {name} {lines[0].split()[3]} outcome=ok"]

    again = call(server, name, **args, confirm=dry["confirm"])
    assert again["error"] == "invalid_argument"
    assert len(mutates(account)) == 2 and gate.calls == 2


def test_keyword_pause_operation(account):
    server = build_writes(Gate())
    dry = call(server, "set_keyword_status", **WRITES[0][1])
    op = mutates(account)[0][2]["request"].operations[0]
    assert op.update.resource_name == f"customers/{CUSTOMER}/adGroupCriteria/{AD_GROUP}~11"
    assert op.update.status.name == "PAUSED" and list(op.update_mask.paths) == ["status"]
    assert dry["changes"][0] == {"criterion_id": "11", "text": "example term 11",
                                 "match_type": "PHRASE", "status": "ENABLED",
                                 "new_status": "PAUSED"}


def test_schedule_uses_date_time_fields(account):
    server = build_writes(Gate())
    dry = call(server, "update_campaign_schedule", customer_id=CUSTOMER, campaign_id=CAMPAIGN,
               start_date="2026-12-01", end_date="2027-01-31")
    op = mutates(account)[0][2]["request"].operations[0]
    assert op.update.start_date_time == "2026-12-01 00:00:00"
    assert op.update.end_date_time == "2027-01-31 23:59:59"
    assert list(op.update_mask.paths) == ["start_date_time", "end_date_time"]
    assert dry["changes"]["end_date_time"] == {"current": "2026-12-31 23:59:59",
                                               "new": "2027-01-31 23:59:59"}


def test_placement_exclusions_are_campaign_negatives(account):
    call(build_writes(Gate()), "add_placement_exclusions", **WRITES[4][1])
    ops = mutates(account)[0][2]["request"].operations
    assert all(op.create.negative and op.create.campaign.endswith(f"campaigns/{CAMPAIGN}")
               for op in ops)
    assert ops[0].create.placement.url == "example.com"
    assert ops[1].create.youtube_channel.channel_id == "UCexample0000000000000001"
    assert ops[2].create.youtube_video.video_id == "abcdefghijk"
    assert ops[3].create.mobile_application.app_id == "2-com.example.app"


def test_asset_group_removes_first(account):
    call(build_writes(Gate()), "update_asset_group_assets", **WRITES[5][1])
    ops = mutates(account)[0][2]["request"].operations
    assert ops[0].remove == f"customers/{CUSTOMER}/assetGroupAssets/41~51~HEADLINE"
    assert ops[1].create.asset == f"customers/{CUSTOMER}/assets/52"
    assert ops[1].create.field_type.name == "HEADLINE"


def test_conversion_goal_operation(account):
    dry = call(build_writes(Gate()), "set_conversion_action_goal", **WRITES[3][1])
    op = mutates(account)[0][2]["request"].operations[0]
    assert op.update.primary_for_goal is False
    assert list(op.update_mask.paths) == ["primary_for_goal"]
    assert dry["changes"] == {"primary_for_goal": {"current": True, "new": False}}


def test_confirm_with_other_arguments_sends_nothing(account):
    server = build_writes(Gate())
    args = WRITES[0][1]
    dry = call(server, "set_keyword_status", **args)
    out = call(server, "set_keyword_status", **{**args, "status": "ENABLED"},
               confirm=dry["confirm"])
    assert out["error"] == "invalid_argument"
    assert len(mutates(account)) == 1


def test_unknown_token_sends_nothing(account):
    gate = Gate()
    server = build_writes(gate)
    for token in ("0" * 32, "not-a-token"):
        out = call(server, "set_keyword_status", **WRITES[0][1], confirm=token)
        assert out["error"] == "invalid_argument"
    assert mutates(account) == []


def test_gate_refusal_is_returned_and_keeps_the_token(account):
    refusal = {"error": "permission_denied", "hint": "Writes are off for this host."}
    gate = Gate(refusal)
    server = build_writes(gate)
    dry = call(server, "set_ad_status", **WRITES[1][1])
    assert call(server, "set_ad_status", **WRITES[1][1], confirm=dry["confirm"]) == refusal
    assert len(mutates(account)) == 1
    gate.refusal = None
    done = call(server, "set_ad_status", **WRITES[1][1], confirm=dry["confirm"])
    assert done["applied"] == 1


def test_changed_state_is_a_conflict(account):
    server = build_writes(Gate())
    dry = call(server, "set_keyword_status", **WRITES[0][1])
    account.keyword_status = "PAUSED"
    out = call(server, "set_keyword_status", **WRITES[0][1], confirm=dry["confirm"])
    assert out["error"] == "conflict"
    assert len(mutates(account)) == 1


@pytest.mark.parametrize("name,args,service,method,count", WRITES[:3] + WRITES[4:5],
                         ids=WRITE_NAMES[:3] + WRITE_NAMES[4:5])
def test_video_campaigns_are_not_supported(account, name, args, service, method, count):
    account.channel = "VIDEO"
    out = call(build_writes(Gate()), name, **args)
    assert out["error"] == "not_supported" and "Video" in out["hint"]
    assert mutates(account) == []


def test_validation_failure_returns_codes_and_paths_only(account):
    account.mutate_error = ads_error("campaign_error", "CANNOT_SET_DATE_TO_PAST",
                                     "private detail 2020-01-01")
    account.mutate_error.failure.errors[0].location.field_path_elements.extend(
        [{"field_name": "operations", "index": 0}, {"field_name": "update"},
         {"field_name": "end_date_time"}])
    out = call(build_writes(Gate()), "update_campaign_schedule", **WRITES[2][1])
    assert out["error"] == "invalid_argument"
    assert out["errors"] == [{"code": "campaign_error.CANNOT_SET_DATE_TO_PAST",
                              "field_path": "operations[0].update.end_date_time"}]
    assert "private detail" not in json.dumps(out) and "confirm" not in out


def test_api_video_refusal_maps_to_not_supported(account):
    account.mutate_error = ads_error("operation_access_denied_error",
                                     "OPERATION_NOT_PERMITTED_FOR_CAMPAIGN_TYPE")
    out = call(build_writes(Gate()), "update_campaign_schedule", **WRITES[2][1])
    assert out["error"] == "not_supported"


@pytest.mark.parametrize("exc", [api_errors.DeadlineExceeded("x"),
                                 api_errors.ServiceUnavailable("x"),
                                 ads_error("internal_error", "INTERNAL_ERROR")])
def test_failed_confirmed_write_is_not_retried(account, caplog, exc):
    caplog.set_level(logging.INFO)
    server = build_writes(Gate())
    dry = call(server, "set_keyword_status", **WRITES[0][1])
    account.mutate_error = exc
    out = call(server, "set_keyword_status", **WRITES[0][1], confirm=dry["confirm"])
    assert out["error"] == "upstream_error" and "may have been applied" in out["hint"]
    assert len(mutates(account)) == 2
    assert "outcome=upstream_error" in caplog.text


@pytest.mark.parametrize("name,args", [
    ("set_keyword_status", {"ad_group_id": AD_GROUP, "criterion_ids": [str(n) for n in range(201)],
                            "status": "PAUSED"}),
    ("set_keyword_status", {"ad_group_id": AD_GROUP, "criterion_ids": ["11", "11"],
                            "status": "PAUSED"}),
    ("set_keyword_status", {"ad_group_id": AD_GROUP, "criterion_ids": ["11"],
                            "status": "REMOVED"}),
    ("set_ad_status", {"ad_group_id": AD_GROUP, "ad_ids": [], "status": "PAUSED"}),
    ("update_campaign_schedule", {"campaign_id": CAMPAIGN}),
    ("update_campaign_schedule", {"campaign_id": CAMPAIGN, "end_date": "31.01.2027"}),
    ("update_campaign_schedule", {"campaign_id": CAMPAIGN, "start_date": "2027-02-01",
                                  "end_date": "2027-01-31"}),
    ("add_placement_exclusions", {"campaign_id": CAMPAIGN}),
    ("add_placement_exclusions", {"campaign_id": CAMPAIGN, "placements": [""]}),
    ("add_placement_exclusions", {"campaign_id": CAMPAIGN,
                                  "placements": [f"site{n}.example" for n in range(201)]}),
    ("update_asset_group_assets", {"asset_group_id": "41"}),
    ("update_asset_group_assets", {"asset_group_id": "41",
                                   "add": [{"asset_id": "52", "field_type": "TITLE"}]}),
    ("update_asset_group_assets", {"asset_group_id": "41",
                                   "add": [{"asset_id": "52"}]}),
])
def test_write_arguments_are_checked_before_any_request(account, name, args):
    out = call(build_writes(Gate()), name, customer_id=CUSTOMER, **args)
    assert out["error"] == "invalid_argument"
    assert account.recorder.requests == []


def test_direct_call_with_a_non_boolean_primary_is_refused(account):
    tool = gads_mcp._guarded(gads_mcp._bind_gate(gads_mcp.set_conversion_action_goal, Gate()),
                             lambda profile: FakeProvider())
    out = tool(customer_id=CUSTOMER, conversion_action_id="31", primary="no")
    assert out["error"] == "invalid_argument"
    assert account.recorder.requests == []


@pytest.mark.parametrize("name,args", [
    ("set_keyword_status", {"ad_group_id": AD_GROUP, "criterion_ids": ["11", "99"],
                            "status": "PAUSED"}),
    ("update_asset_group_assets", {"asset_group_id": "41",
                                   "remove": [{"asset_id": "59", "field_type": "HEADLINE"}]}),
])
def test_unknown_targets_are_not_found(account, name, args):
    out = call(build_writes(Gate()), name, customer_id=CUSTOMER, **args)
    assert out["error"] == "not_found"
    assert mutates(account) == []


def test_write_tools_use_the_profile_provider(account):
    seen = []

    def factory(profile):
        seen.append(profile)
        return FakeProvider(login="5556667777")

    server = build_writes(Gate(), provider_factory=factory)
    call(server, "set_ad_status", **WRITES[1][1], profile="second")
    assert seen == ["second"]
    assert {client["login_customer_id"] for client in account.recorder.clients} == {"5556667777"}


def test_no_secret_in_write_output_or_logs(account, caplog):
    caplog.set_level(logging.DEBUG)
    server = build_writes(Gate())
    outputs = []
    for name, args, *_ in WRITES:
        dry = call(server, name, **args)
        outputs += [dry, call(server, name, **args, confirm=dry["confirm"])]
    text = json.dumps(outputs) + caplog.text
    assert not any(secret in text for secret in SECRETS)
    assert all(out["confirm"] not in caplog.text for out in outputs if "confirm" in out)


def test_hung_write_hits_the_deadline_and_reports_unknown_outcome(account, caplog):
    caplog.set_level(logging.INFO)
    server = build_writes(Gate())
    dry = call(server, "set_ad_status", **WRITES[1][1])
    account.mutate_error = api_errors.DeadlineExceeded("deadline exceeded")
    out = call(server, "set_ad_status", **WRITES[1][1], confirm=dry["confirm"])
    assert out["error"] == "upstream_error" and "may have been applied" in out["hint"]
    assert mutates(account)[1][2]["timeout"] == gads_mcp._WRITE_TIMEOUT_SECONDS
    assert "gads write set_ad_status" in caplog.text and "outcome=upstream_error" in caplog.text


def test_rejected_write_gets_write_hints(account):
    account.mutate_error = ads_error("authorization_error", "USER_PERMISSION_DENIED")
    out = call(build_writes(Gate()), "set_ad_status", **WRITES[1][1])
    assert out["error"] == "permission_denied" and "cannot change" in out["hint"]
    account.mutate_error = ads_error("campaign_error", "CANNOT_SET_DATE_TO_PAST")
    out = call(build_writes(Gate()), "update_campaign_schedule", **WRITES[2][1])
    assert out["hint"] == gads_mcp._WRITE_HINTS["invalid_argument"]


def test_digest_covers_only_the_tool_arguments(account, monkeypatch):
    seen = []
    monkeypatch.setattr(gads_mcp, "_digest", lambda value: seen.append(value) or "d" * 64)
    call(build_writes(Gate()), "set_ad_status", **WRITES[1][1])
    assert seen[0] == {"tool": "set_ad_status", **WRITES[1][1], "profile": None}
