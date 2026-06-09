"""Pretty-print fallback in gads_utils.emit and the table helper."""

from __future__ import annotations

import io
import json

import gads_utils


def _capture_emit(data, as_json):
    buf = io.StringIO()
    gads_utils.emit(data, as_json=as_json, stream=buf)
    return buf.getvalue()


def test_json_mode_emits_valid_json():
    out = _capture_emit({"customer_id": "1", "summary": "hello"}, as_json=True)
    parsed = json.loads(out)
    assert parsed == {"customer_id": "1", "summary": "hello"}


def test_pretty_mode_includes_customer_and_summary():
    out = _capture_emit({"customer_id": "1234567890", "summary": "hello world"}, as_json=False)
    assert "customer_id=1234567890" in out
    assert "hello world" in out


def test_pretty_mode_renders_findings_grouped():
    out = _capture_emit({
        "customer_id": "x",
        "findings": [
            {"severity": "high",   "message": "issue A"},
            {"severity": "medium", "message": "issue B"},
        ],
    }, as_json=False)
    assert "findings:" in out
    assert "[high" in out
    assert "issue A" in out
    assert "issue B" in out


def test_pretty_mode_renders_list_as_table():
    out = _capture_emit({
        "customer_id": "x",
        "candidates": [
            {"search_term": "cheap thing", "cost": 12.5, "clicks": 10, "conversions": 0},
            {"search_term": "another",     "cost":  4.0, "clicks":  3, "conversions": 0},
        ],
    }, as_json=False)
    assert "candidates:" in out
    assert "search_term" in out
    assert "cheap thing" in out
    # column ordering preset for candidates
    assert out.index("search_term") < out.index("cost")


def test_pretty_mode_renders_audit_shape():
    out = _capture_emit({
        "customer_id": "x",
        "agents": {
            "gads-search":    {"status": "ok",     "summary": "looks fine"},
            "gads-placements": {"status": "failed", "error":   "perm denied"},
        },
    }, as_json=False)
    assert "agents:" in out
    assert "gads-search" in out
    assert "looks fine" in out
    assert "failed" in out


def test_pretty_mode_renders_by_type_groups():
    out = _capture_emit({
        "customer_id": "x",
        "by_type": {"KEYWORD": [{}, {}], "BUDGET": [{}]},
    }, as_json=False)
    assert "by_type:" in out
    assert "KEYWORD" in out
    assert "2" in out


def test_table_renders_no_rows():
    assert gads_utils.table([]) == "(no rows)"


def test_table_columns_and_widths():
    out = gads_utils.table([
        {"name": "Acme",     "spend": 12.5},
        {"name": "WidgetCo", "spend": 200.0},
    ], columns=["name", "spend"])
    lines = out.splitlines()
    assert lines[0].startswith("name")
    assert "spend" in lines[0]
    # alignment: each row should be exactly as wide as the header line
    assert all(len(line) == len(lines[0]) for line in lines)


def test_table_truncates_long_cells():
    out = gads_utils.table(
        [{"q": "x" * 100}], columns=["q"], max_width=10
    )
    assert "…" in out
