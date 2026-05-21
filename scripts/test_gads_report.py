"""Audit report renderer."""

from __future__ import annotations

import gads_report


def _audit():
    return {
        "customer_id": "1234567890",
        "date_range": {"start": "2025-01-01", "end": "2025-01-28"},
        "agents": {
            "gads-search": {
                "status": "ok",
                "summary": "spend stable, 2 underperformers",
                "findings": [
                    {"severity": "high", "message": "Brand cannibalization between Search and PMax"},
                    {"severity": "low",  "message": "Two ad groups have <3 RSAs"},
                ],
            },
            "gads-conversions": {
                "status": "ok",
                "summary": "no primary conversion",
                "findings": [
                    {"severity": "critical", "message": "No conversion is primary-for-goal"},
                ],
            },
            "gads-placements": {
                "status": "failed",
                "error": "permission denied",
            },
        },
    }


def test_markdown_contains_summary_and_findings():
    md = gads_report.render_markdown(_audit())
    assert "# Google Ads audit — customer 1234567890" in md
    assert "## Summary" in md
    assert "## Findings" in md
    assert "### critical" in md
    assert "### high" in md
    assert "### low" in md
    # failed agent surfaces with its error
    assert "failed: permission denied" in md


def test_markdown_orders_severity_critical_first():
    md = gads_report.render_markdown(_audit())
    crit = md.find("### critical")
    high = md.find("### high")
    low = md.find("### low")
    assert -1 < crit < high < low


def test_html_wraps_markdown():
    out = gads_report.render_html(_audit())
    assert out.startswith("<!doctype html>")
    assert "Google Ads audit" in out
    assert "customer 1234567890" in out


def test_empty_audit_renders_summary_only():
    md = gads_report.render_markdown({"customer_id": "x", "date_range": {}, "agents": {}})
    assert "## Summary" in md
    assert "## Findings" not in md  # no findings, no findings section
