import json

import gads_findings
import gads_history
import gads_notify
import gads_report


def test_nested_findings_reach_reports_history_and_notifications():
    audit = {"agents": {"demographics": {"age": {"findings": [
        {"code": "outlier", "severity": "critical", "message": "Nested issue"},
    ]}}}}
    findings = gads_findings.collect(audit)
    assert findings[0]["source_path"] == "age"
    assert gads_history._findings(audit) == findings
    assert "Nested issue" in gads_report.render_markdown(audit)
    assert "Nested issue" in gads_notify.format_critical_audit(audit)
    assert "agent" not in audit["agents"]["demographics"]["age"]["findings"][0]


def test_history_distinguishes_entities_and_ignores_metric_text_changes(tmp_path):
    def finding(cid, message):
        return {"code": "outlier", "entity": {"campaign_id": cid, "bucket": "MOBILE"},
                "message": message}

    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(json.dumps({"agents": {"x": {"findings": [
        finding("1", "CPA 10"), finding("2", "CPA 20"),
    ]}}}))
    after.write_text(json.dumps({"agents": {"x": {"findings": [finding("2", "CPA 30")]}}}))
    result = gads_history.diff_audits(before, after)
    assert [f["entity"]["campaign_id"] for f in result["resolved"]] == ["1"]
    assert [f["entity"]["campaign_id"] for f in result["unchanged"]] == ["2"]
    assert result["new"] == []


def test_legacy_same_code_different_messages_do_not_collapse():
    assert gads_findings.identity({"code": "x", "message": "campaign A"}) != (
        gads_findings.identity({"code": "x", "message": "campaign B"})
    )
