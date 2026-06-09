"""Telegram formatter + credential storage. No network calls."""

from __future__ import annotations


import gads_notify


def test_is_configured_false_by_default():
    assert gads_notify.is_configured() is False


def test_save_and_load_telegram(monkeypatch):
    gads_notify.save_telegram("TEST_TOKEN", "12345")
    cfg = gads_notify.load_telegram()
    assert cfg == {"token": "TEST_TOKEN", "chat_id": "12345"}
    assert gads_notify.is_configured() is True


def test_format_critical_audit_with_findings():
    audit = {
        "customer_id": "1234567890",
        "agents": {
            "gads-conversions": {
                "findings": [
                    {"severity": "critical", "message": "No primary conversion"},
                    {"severity": "high",     "message": "Won't show"},
                ],
            },
            "gads-gtag": {
                "findings": [
                    {"severity": "critical", "message": "<gtag> not found on site"},
                ],
            },
        },
    }
    msg = gads_notify.format_critical_audit(audit)
    assert msg is not None
    assert "1234567890" in msg
    assert "No primary conversion" in msg
    assert "&lt;gtag&gt;" in msg     # HTML-escaped
    assert "Won't show" not in msg   # non-critical not included


def test_format_critical_audit_returns_none_without_critical():
    audit = {
        "customer_id": "1",
        "agents": {
            "gads-search": {"findings": [{"severity": "high", "message": "x"}]},
        },
    }
    assert gads_notify.format_critical_audit(audit) is None


def test_format_critical_audit_truncates():
    findings = [
        {"severity": "critical", "message": f"finding {i}"} for i in range(20)
    ]
    audit = {"customer_id": "1", "agents": {"gads-x": {"findings": findings}}}
    msg = gads_notify.format_critical_audit(audit, limit=5)
    assert "…and 15 more" in msg


def test_send_message_when_not_configured():
    """No token saved => the send call short-circuits gracefully."""
    out = gads_notify.send_message("hello")
    assert out == {"ok": False, "error": "telegram not configured"}
