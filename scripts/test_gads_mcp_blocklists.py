"""Shared negative keyword and placement blocklist tools over the offline v25 transport."""

from __future__ import annotations

import logging
import re

import gads_mcp
import pytest
from mcp.server.fastmcp import FastMCP
from test_gads_mcp import (
    CUSTOMER,
    TYPES,
    FakeProvider,
    home,  # noqa: F401
    install,
    stream,
)
from test_gads_mcp_writes import Account, Gate, build_writes, call, mutates

KW_SET = "701"
PL_SET = "702"
BRAND_SET = "703"


class BlocklistAccount(Account):
    def __init__(self):
        super().__init__()
        self.sets = {
            KW_SET: {"id": int(KW_SET), "name": "Pre-launch KW trash", "type_": "NEGATIVE_KEYWORDS",
                     "status": "ENABLED", "member_count": 2, "reference_count": 1},
            PL_SET: {"id": int(PL_SET), "name": "Pre-launch Display trash",
                     "type_": "NEGATIVE_PLACEMENTS", "status": "ENABLED",
                     "member_count": 2, "reference_count": 0},
            BRAND_SET: {"id": int(BRAND_SET), "name": "Brand list", "type_": "BRANDS",
                        "status": "ENABLED", "member_count": 1, "reference_count": 0},
        }
        self.criteria = {
            KW_SET: [
                {"shared_criterion": {"criterion_id": 9001, "type_": "KEYWORD",
                                      "keyword": {"text": "free", "match_type": "PHRASE"}}},
                {"shared_criterion": {"criterion_id": 9002, "type_": "KEYWORD",
                                      "keyword": {"text": "crack", "match_type": "EXACT"}}},
            ],
            PL_SET: [
                {"shared_criterion": {"criterion_id": 9101, "type_": "PLACEMENT",
                                      "placement": {"url": "spam.example"}}},
                {"shared_criterion": {"criterion_id": 9102, "type_": "MOBILE_APPLICATION",
                                      "mobile_application": {"app_id": "2-com.example.game"}}},
            ],
        }
        self.campaigns = {
            "111": {"id": 111, "name": "Search Core", "status": "ENABLED",
                    "advertising_channel_type": "SEARCH"},
            "222": {"id": 222, "name": "Display Prospecting", "status": "ENABLED",
                    "advertising_channel_type": "DISPLAY"},
            "333": {"id": 333, "name": "YouTube Brand", "status": "ENABLED",
                    "advertising_channel_type": "VIDEO"},
        }
        self.links: set[tuple[str, str]] = {("111", KW_SET)}

    def rows(self, query: str):
        resource = re.search(r"FROM (\w+)", query).group(1)
        if resource == "shared_set":
            out = []
            for row in self.sets.values():
                if "shared_set.status != 'REMOVED'" in query and row["status"] == "REMOVED":
                    continue
                if "IN ('NEGATIVE_KEYWORDS', 'NEGATIVE_PLACEMENTS')" in query:
                    if row["type_"] not in ("NEGATIVE_KEYWORDS", "NEGATIVE_PLACEMENTS"):
                        continue
                m_type = re.search(r"shared_set\.type = '([A-Z_]+)'", query)
                if m_type and row["type_"] != m_type.group(1):
                    continue
                m_id = re.search(r"shared_set\.id = (\d+)", query)
                if m_id and str(row["id"]) != m_id.group(1):
                    continue
                m_name = re.search(r"shared_set\.name = '([^']*)'", query)
                if m_name and row["name"] != m_name.group(1):
                    continue
                out.append({"shared_set": dict(row)})
            return out
        if resource == "shared_criterion":
            m_set = re.search(r"shared_set\.id = (\d+)", query)
            rows = list(self.criteria.get(m_set.group(1), [])) if m_set else []
            m_in = re.search(r"criterion_id IN \(([^)]+)\)", query)
            if m_in:
                wanted = {x.strip() for x in m_in.group(1).split(",")}
                rows = [r for r in rows if str(r["shared_criterion"]["criterion_id"]) in wanted]
            return rows
        if resource == "campaign_shared_set":
            out = []
            for cid_str, sid_str in sorted(self.links):
                set_path = f"customers/{CUSTOMER}/sharedSets/{sid_str}"
                camp_path = f"customers/{CUSTOMER}/campaigns/{cid_str}"
                if f"shared_set.id = {sid_str}" in query or f"'{set_path}'" in query:
                    if "campaign_shared_set.campaign IN" in query and f"'{camp_path}'" not in query:
                        continue
                    out.append({
                        "campaign": dict(self.campaigns[cid_str]),
                        "campaign_shared_set": {
                            "resource_name": f"customers/{CUSTOMER}/campaignSharedSets/{cid_str}~{sid_str}",
                            "campaign": camp_path,
                            "shared_set": set_path,
                            "status": "ENABLED",
                        },
                    })
            return out
        if resource == "campaign":
            m_in = re.search(r"campaign\.id IN \(([^)]+)\)", query)
            if m_in:
                wanted = {x.strip() for x in m_in.group(1).split(",")}
                return [{"campaign": dict(v)} for k, v in self.campaigns.items() if k in wanted]
        return super().rows(query)

    def respond(self, service: str, method: str, kwargs: dict):
        if method == "mutate":
            if self.mutate_error:
                raise self.mutate_error
            req = kwargs["request"]
            resp = TYPES.get_type("MutateGoogleAdsResponse")
            if not req["validate_only"]:
                for i, op in enumerate(req["mutate_operations"]):
                    item = TYPES.get_type("MutateOperationResponse")
                    kind = op._pb.WhichOneof("operation")
                    if kind == "shared_set_operation":
                        item.shared_set_result.resource_name = f"customers/{CUSTOMER}/sharedSets/799"
                    else:
                        item.shared_criterion_result.resource_name = (
                            f"customers/{CUSTOMER}/sharedCriteria/799~{i}"
                        )
                    resp.mutate_operation_responses.append(item)
            return resp
        if method in ("mutate_shared_sets", "mutate_shared_criteria", "mutate_campaign_shared_sets"):
            if self.mutate_error:
                raise self.mutate_error
            rtype = {
                "mutate_shared_sets": "MutateSharedSetsResponse",
                "mutate_shared_criteria": "MutateSharedCriteriaResponse",
                "mutate_campaign_shared_sets": "MutateCampaignSharedSetsResponse",
            }[method]
            resp = TYPES.get_type(rtype)
            req = kwargs["request"]
            if not req.validate_only:
                resp.results.extend([
                    {"resource_name": f"customers/{CUSTOMER}/res/{i}"}
                    for i, _ in enumerate(req.operations)
                ])
            return resp
        return stream(self.rows(kwargs["query"]))


@pytest.fixture
def account(monkeypatch):
    acc = BlocklistAccount()
    acc.recorder = install(monkeypatch.setattr, acc.respond)
    acc.recorder.client_class.enums = TYPES.enums
    return acc


def build_reads():
    server = FastMCP("reads")
    gads_mcp.register(server, provider_factory=lambda _profile: FakeProvider())
    return server


def invoke(server, tool, /, **args):
    return call(server, tool, customer_id=CUSTOMER, **args)


def test_shared_blocklists_lists_and_expands_details(account):
    server = build_reads()
    listed = invoke(server, "shared_blocklists")
    assert [b["shared_set_id"] for b in listed["blocklists"]] == [KW_SET, PL_SET]
    assert listed["blocklists"][0]["member_count"] == 2
    assert listed["blocklists"][0]["reference_count"] == 1

    filtered = invoke(server, "shared_blocklists", list_type="NEGATIVE_PLACEMENTS")
    assert [b["shared_set_id"] for b in filtered["blocklists"]] == [PL_SET]

    detail = invoke(server, "shared_blocklists", shared_set_id=KW_SET)
    assert detail["criteria"] == [
        {"criterion_id": "9001", "type": "KEYWORD", "text": "free", "match_type": "PHRASE"},
        {"criterion_id": "9002", "type": "KEYWORD", "text": "crack", "match_type": "EXACT"},
    ]
    assert detail["campaigns"] == [
        {"campaign_id": "111", "name": "Search Core", "status": "ENABLED"},
    ]

    pl_detail = invoke(server, "shared_blocklists", shared_set_id=PL_SET)
    assert pl_detail["criteria"] == [
        {"criterion_id": "9101", "type": "PLACEMENT", "url": "spam.example"},
        {"criterion_id": "9102", "type": "MOBILE_APPLICATION", "app_id": "2-com.example.game"},
    ]
    assert invoke(server, "shared_blocklists", shared_set_id="9999")["error"] == "not_found"
    assert invoke(server, "shared_blocklists", list_type="BRANDS")["error"] == "invalid_argument"


def test_create_empty_and_atomic_seeded_blocklists(account, caplog):
    caplog.set_level(logging.INFO)
    gate = Gate()
    server = build_writes(gate)

    # Empty CREATE uses SharedSetService.
    dry = invoke(server, "manage_shared_blocklist", operation="CREATE",
                 list_type="NEGATIVE_KEYWORDS", name="  New empty list  ")
    assert dry["dry_run"] and dry["validated"] and dry["name"] == "New empty list"
    sent = mutates(account)
    assert [(s, m) for s, m, _ in sent] == [("SharedSetService", "mutate_shared_sets")]
    op = sent[0][2]["request"].operations[0]
    assert op.create.name == "New empty list"
    assert op.create.type_.name == "NEGATIVE_KEYWORDS"
    done = invoke(server, "manage_shared_blocklist", operation="CREATE",
                  list_type="NEGATIVE_KEYWORDS", name="  New empty list  ", confirm=dry["confirm"])
    assert done["dry_run"] is False and done["applied"] == 1

    # Seeded CREATE uses atomic GoogleAdsService.mutate with temp ID -1.
    dry2 = invoke(
        server, "manage_shared_blocklist", operation="CREATE",
        list_type="NEGATIVE_KEYWORDS", name="Launch Guard",
        keywords=[{"text": "torrent"}, {"text": "free pdf", "match_type": "EXACT"}],
    )
    assert dry2["dry_run"] and len(dry2["items"]) == 2
    atomic = [r for r in account.recorder.requests if r[1] == "mutate"]
    assert len(atomic) == 1 and atomic[0][2]["request"]["validate_only"] is True
    ops = atomic[0][2]["request"]["mutate_operations"]
    assert len(ops) == 3
    assert ops[0].shared_set_operation.create.resource_name == f"customers/{CUSTOMER}/sharedSets/-1"
    assert ops[1].shared_criterion_operation.create.shared_set == f"customers/{CUSTOMER}/sharedSets/-1"
    assert ops[1].shared_criterion_operation.create.keyword.text == "torrent"
    assert ops[1].shared_criterion_operation.create.keyword.match_type.name == "PHRASE"
    assert ops[2].shared_criterion_operation.create.keyword.match_type.name == "EXACT"

    gate.refusal = {"error": "writes_disabled"}
    assert invoke(
        server, "manage_shared_blocklist", operation="CREATE",
        list_type="NEGATIVE_KEYWORDS", name="Launch Guard",
        keywords=[{"text": "torrent"}, {"text": "free pdf", "match_type": "EXACT"}],
        confirm=dry2["confirm"],
    ) == {"error": "writes_disabled"}
    gate.refusal = None
    applied = invoke(
        server, "manage_shared_blocklist", operation="CREATE",
        list_type="NEGATIVE_KEYWORDS", name="Launch Guard",
        keywords=[{"text": "torrent"}, {"text": "free pdf", "match_type": "EXACT"}],
        confirm=dry2["confirm"],
    )
    assert applied["dry_run"] is False and applied["applied"] == 3
    assert applied["resource_names"][0] == f"customers/{CUSTOMER}/sharedSets/799"
    lines = [r.getMessage() for r in caplog.records if "ads write manage_shared_blocklist" in r.getMessage()]
    assert len(lines) == 2 and all(line.endswith("outcome=ok") for line in lines)


def test_add_remove_items_and_remove_blocklist(account):
    gate = Gate()
    server = build_writes(gate)

    # ADD_ITEMS on NEGATIVE_PLACEMENTS covers all 4 placement types.
    dry_add = invoke(
        server, "manage_shared_blocklist", operation="ADD_ITEMS", shared_set_id=PL_SET,
        placements=["mfa.example"], youtube_channel_ids=["UC0000000000000000000001"],
        youtube_video_ids=["dQw4w9WgXcQ"], mobile_app_ids=["1-123456789"],
    )
    assert dry_add["dry_run"] and len(dry_add["items"]) == 4
    req = mutates(account)[-1][2]["request"]
    assert len(req.operations) == 4
    assert req.operations[0].create.shared_set == f"customers/{CUSTOMER}/sharedSets/{PL_SET}"
    assert req.operations[0].create.placement.url == "mfa.example"
    assert req.operations[1].create.youtube_channel.channel_id == "UC0000000000000000000001"
    assert req.operations[2].create.youtube_video.video_id == "dQw4w9WgXcQ"
    assert req.operations[3].create.mobile_application.app_id == "1-123456789"
    done_add = invoke(
        server, "manage_shared_blocklist", operation="ADD_ITEMS", shared_set_id=PL_SET,
        placements=["mfa.example"], youtube_channel_ids=["UC0000000000000000000001"],
        youtube_video_ids=["dQw4w9WgXcQ"], mobile_app_ids=["1-123456789"],
        confirm=dry_add["confirm"],
    )
    assert done_add["applied"] == 4

    # REMOVE_ITEMS reads criteria, validates presence, and detects conflict on change.
    dry_rm = invoke(server, "manage_shared_blocklist", operation="REMOVE_ITEMS",
                    shared_set_id=KW_SET, criterion_ids=["9001"])
    assert dry_rm["removing"] == [
        {"criterion_id": "9001", "type": "KEYWORD", "text": "free", "match_type": "PHRASE"}
    ]
    assert mutates(account)[-1][2]["request"].operations[0].remove == (
        f"customers/{CUSTOMER}/sharedCriteria/{KW_SET}~9001"
    )
    account.sets[KW_SET]["member_count"] = 99
    assert invoke(server, "manage_shared_blocklist", operation="REMOVE_ITEMS",
                  shared_set_id=KW_SET, criterion_ids=["9001"],
                  confirm=dry_rm["confirm"])["error"] == "conflict"

    # REMOVE shared set reports member_count and reference_count.
    dry_del = invoke(server, "manage_shared_blocklist", operation="REMOVE", shared_set_id=PL_SET)
    assert dry_del["member_count"] == 2 and dry_del["reference_count"] == 0
    assert mutates(account)[-1][2]["request"].operations[0].remove == (
        f"customers/{CUSTOMER}/sharedSets/{PL_SET}"
    )
    done_del = invoke(server, "manage_shared_blocklist", operation="REMOVE",
                      shared_set_id=PL_SET, confirm=dry_del["confirm"])
    assert done_del["applied"] == 1


@pytest.mark.parametrize("args,expected", [
    ({"operation": "CREATE", "list_type": "NEGATIVE_KEYWORDS", "name": "Pre-launch KW trash"},
     "invalid_argument"),
    ({"operation": "CREATE", "list_type": "NEGATIVE_KEYWORDS", "name": "Bad",
      "placements": ["x.com"]}, "invalid_argument"),
    ({"operation": "CREATE", "list_type": "NEGATIVE_PLACEMENTS", "name": "Bad",
      "keywords": [{"text": "free"}]}, "invalid_argument"),
    ({"operation": "CREATE", "list_type": "NEGATIVE_KEYWORDS", "name": "Bad",
      "keywords": [{"text": "Free"}, {"text": "free", "match_type": "PHRASE"}]},
     "invalid_argument"),
    ({"operation": "CREATE", "list_type": "NEGATIVE_KEYWORDS", "name": "Line1\nLine2"},
     "invalid_argument"),
    ({"operation": "ADD_ITEMS", "shared_set_id": KW_SET, "placements": ["a.com"]},
     "invalid_argument"),
    ({"operation": "ADD_ITEMS", "shared_set_id": BRAND_SET, "keywords": [{"text": "x"}]},
     "invalid_argument"),
    ({"operation": "ADD_ITEMS", "shared_set_id": KW_SET}, "invalid_argument"),
    ({"operation": "REMOVE_ITEMS", "shared_set_id": KW_SET, "criterion_ids": ["9999"]},
     "not_found"),
    ({"operation": "REMOVE", "shared_set_id": PL_SET, "criterion_ids": ["9101"]},
     "invalid_argument"),
])
def test_manage_shared_blocklist_guards(account, args, expected):
    server = build_writes(Gate())
    out = invoke(server, "manage_shared_blocklist", **args)
    assert out["error"] == expected
    assert mutates(account) == []


def test_manage_campaign_blocklists_attach_detach_and_guards(account, caplog):
    caplog.set_level(logging.INFO)
    gate = Gate()
    server = build_writes(gate)

    # CREATE attaches PL_SET to campaigns 111 and 222.
    dry = invoke(server, "manage_campaign_blocklists", operation="CREATE",
                 shared_set_id=PL_SET, campaign_ids=["111", "222"])
    assert dry["dry_run"] and len(dry["changes"]) == 2
    ops = mutates(account)[0][2]["request"].operations
    assert ops[0].create.campaign == f"customers/{CUSTOMER}/campaigns/111"
    assert ops[0].create.shared_set == f"customers/{CUSTOMER}/sharedSets/{PL_SET}"
    done = invoke(server, "manage_campaign_blocklists", operation="CREATE",
                  shared_set_id=PL_SET, campaign_ids=["111", "222"], confirm=dry["confirm"])
    assert done["applied"] == 2
    assert any(
        f"ads write manage_campaign_blocklists customers/{CUSTOMER}/sharedSets/{PL_SET} outcome=ok"
        in r.getMessage()
        for r in caplog.records
    )

    # REMOVE detaches KW_SET from campaign 111 and detects conflict if link vanishes.
    dry_rm = invoke(server, "manage_campaign_blocklists", operation="REMOVE",
                    shared_set_id=KW_SET, campaign_ids=["111"])
    assert mutates(account)[-1][2]["request"].operations[0].remove == (
        f"customers/{CUSTOMER}/campaignSharedSets/111~{KW_SET}"
    )
    account.links.discard(("111", KW_SET))
    assert invoke(server, "manage_campaign_blocklists", operation="REMOVE",
                  shared_set_id=KW_SET, campaign_ids=["111"],
                  confirm=dry_rm["confirm"])["error"] == "conflict"

    # Guards: VIDEO rejected, already-attached rejected on CREATE, unattached on REMOVE, BRANDS rejected.
    account.links.add(("111", KW_SET))
    assert invoke(server, "manage_campaign_blocklists", operation="CREATE",
                  shared_set_id=PL_SET, campaign_ids=["333"])["error"] == "not_supported"
    assert invoke(server, "manage_campaign_blocklists", operation="CREATE",
                  shared_set_id=KW_SET, campaign_ids=["111"])["error"] == "invalid_argument"
    assert invoke(server, "manage_campaign_blocklists", operation="REMOVE",
                  shared_set_id=KW_SET, campaign_ids=["222"])["error"] == "not_found"
    assert invoke(server, "manage_campaign_blocklists", operation="CREATE",
                  shared_set_id=BRAND_SET, campaign_ids=["111"])["error"] == "invalid_argument"
