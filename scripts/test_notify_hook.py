"""PostToolUse Telegram hook behavior. No network calls."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "notify_telegram.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("notify_telegram", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _StringStdin:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload


def _run_hook(hook, event):
    sys.stdin = _StringStdin(json.dumps(event))
    return hook.main()


def test_non_bash_tool_no_op(monkeypatch):
    hook = _load_hook()
    calls = []
    monkeypatch.setattr(hook.gads_notify, "send_message",
                        lambda *a, **kw: calls.append((a, kw)))
    _run_hook(hook, {"tool_name": "Read", "tool_input": {}})
    assert calls == []


def test_non_audit_command_no_op(monkeypatch):
    hook = _load_hook()
    calls = []
    monkeypatch.setattr(hook.gads_notify, "send_message",
                        lambda *a, **kw: calls.append((a, kw)))
    _run_hook(hook, {
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
        "tool_response": {"output": "..."},
    })
    assert calls == []


def test_unconfigured_telegram_no_op(monkeypatch):
    hook = _load_hook()
    monkeypatch.setattr(hook.gads_notify, "is_configured", lambda: False)
    calls = []
    monkeypatch.setattr(hook.gads_notify, "send_message",
                        lambda *a, **kw: calls.append((a, kw)))
    _run_hook(hook, {
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_audit.py --customer 1"},
        "tool_response": {"output": json.dumps({
            "customer_id": "1",
            "agents": {"x": {"findings": [{"severity": "critical", "message": "boom"}]}},
        })},
    })
    assert calls == []


def test_audit_with_critical_sends(monkeypatch):
    hook = _load_hook()
    monkeypatch.setattr(hook.gads_notify, "is_configured", lambda: True)
    sent = []
    monkeypatch.setattr(hook.gads_notify, "send_message",
                        lambda text, **kw: sent.append(text) or {"ok": True})
    _run_hook(hook, {
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_audit.py --customer 1"},
        "tool_response": {"output": json.dumps({
            "customer_id": "1",
            "agents": {"x": {"findings": [{"severity": "critical", "message": "boom"}]}},
        })},
    })
    assert len(sent) == 1
    assert "boom" in sent[0]
    assert "critical" in sent[0]


def test_audit_with_no_critical_does_not_send(monkeypatch):
    hook = _load_hook()
    monkeypatch.setattr(hook.gads_notify, "is_configured", lambda: True)
    sent = []
    monkeypatch.setattr(hook.gads_notify, "send_message",
                        lambda *a, **kw: sent.append(a) or {"ok": True})
    _run_hook(hook, {
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_audit.py --customer 1"},
        "tool_response": {"output": json.dumps({
            "customer_id": "1",
            "agents": {"x": {"findings": [{"severity": "high", "message": "warn"}]}},
        })},
    })
    assert sent == []


def test_all_customers_walks_each_account(monkeypatch):
    hook = _load_hook()
    monkeypatch.setattr(hook.gads_notify, "is_configured", lambda: True)
    sent = []
    monkeypatch.setattr(hook.gads_notify, "send_message",
                        lambda text, **kw: sent.append(text) or {"ok": True})
    payload = {
        "accounts": {
            "1": {"customer_id": "1",
                  "agents": {"a": {"findings": [{"severity": "critical", "message": "one"}]}}},
            "2": {"customer_id": "2",
                  "agents": {"a": {"findings": [{"severity": "high", "message": "skip"}]}}},
            "3": {"customer_id": "3",
                  "agents": {"a": {"findings": [{"severity": "critical", "message": "three"}]}}},
        },
    }
    _run_hook(hook, {
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_audit.py --all-customers"},
        "tool_response": {"output": json.dumps(payload)},
    })
    assert len(sent) == 2
    joined = "\n".join(sent)
    assert "one" in joined
    assert "three" in joined
    assert "skip" not in joined


def test_pretty_print_output_is_ignored(monkeypatch):
    """If the audit ran without --json the output isn't valid JSON; bail."""
    hook = _load_hook()
    monkeypatch.setattr(hook.gads_notify, "is_configured", lambda: True)
    sent = []
    monkeypatch.setattr(hook.gads_notify, "send_message",
                        lambda *a, **kw: sent.append(a) or {"ok": True})
    _run_hook(hook, {
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_audit.py --customer 1"},
        "tool_response": {"output": "agents:\n  gads-x  ok  fine\n"},
    })
    assert sent == []
