"""Audit history persistence + diff — no API calls."""

from __future__ import annotations

import json
from pathlib import Path

import gads_history


def _audit(cid, findings_by_agent):
    return {
        "customer_id": cid,
        "agents": {
            agent: {"status": "ok", "findings": findings}
            for agent, findings in findings_by_agent.items()
        },
    }


def test_save_and_list(tmp_path, monkeypatch):
    monkeypatch.setattr(gads_history, "HISTORY_ROOT", tmp_path)
    gads_history.save_audit(_audit("123", {}))
    gads_history.save_audit(_audit("123", {}))
    audits = gads_history.list_audits("123")
    assert len(audits) == 2
    assert all(p.suffix == ".json" for p in audits)


def test_diff_classifies_findings(tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps(_audit("123", {
        "gads-search": [
            {"severity": "high", "code": "wasted_spend", "message": "..."},
            {"severity": "low",  "code": "few_rsa",     "message": "..."},
        ],
    })))
    b.write_text(json.dumps(_audit("123", {
        "gads-search": [
            {"severity": "high", "code": "wasted_spend", "message": "..."},
        ],
        "gads-placements": [
            {"severity": "medium", "code": "scam_placements", "message": "..."},
        ],
    })))
    out = gads_history.diff_audits(a, b)
    assert [f["code"] for f in out["resolved"]] == ["few_rsa"]
    assert [f["code"] for f in out["new"]] == ["scam_placements"]
    assert [f["code"] for f in out["unchanged"]] == ["wasted_spend"]


def test_resolve_audit_by_path(tmp_path, monkeypatch):
    monkeypatch.setattr(gads_history, "HISTORY_ROOT", tmp_path)
    saved = gads_history.save_audit(_audit("123", {}))
    # full path resolves
    assert gads_history._resolve_audit(str(saved), "123") == saved
    # bare timestamp resolves when customer is supplied
    ts = saved.stem
    assert gads_history._resolve_audit(ts, "123") == saved
