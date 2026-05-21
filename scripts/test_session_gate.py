"""Session-gate hook behavior. No live API."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parent.parent / "hooks" / "session_gate.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location("session_gate", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hook(tmp_path, monkeypatch):
    sg = _load_hook()
    monkeypatch.setattr(sg, "SESSION_PATH", tmp_path / "gads-session.json")
    return sg


def _run_hook(hook, event, capsys):
    monkeypatch_stdin = json.dumps(event)
    sys.stdin = _StringStdin(monkeypatch_stdin)
    hook.main()
    return json.loads(capsys.readouterr().out)


class _StringStdin:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self):
        return self._payload

    def readlines(self):
        return [self._payload]


def test_non_bash_tool_always_approves(hook, capsys, monkeypatch):
    sys.stdin = _StringStdin(json.dumps({"tool_name": "Read", "tool_input": {}}))
    hook.main()
    assert json.loads(capsys.readouterr().out) == {"decision": "approve"}


def test_unrelated_bash_command_approves(hook, capsys):
    sys.stdin = _StringStdin(json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
    }))
    hook.main()
    assert json.loads(capsys.readouterr().out) == {"decision": "approve"}


def test_gads_call_with_no_session_blocks(hook, capsys):
    sys.stdin = _StringStdin(json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_search.py --customer 1"},
    }))
    hook.main()
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"
    assert "session expired" in out["reason"].lower()


def test_gads_call_with_fresh_session_approves(hook, capsys):
    hook.SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    hook.SESSION_PATH.write_text(json.dumps({
        "started_at": datetime.now(timezone.utc).isoformat()
    }))
    sys.stdin = _StringStdin(json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_search.py --customer 1"},
    }))
    hook.main()
    out = json.loads(capsys.readouterr().out)
    assert out == {"decision": "approve"}


def test_gads_call_with_expired_session_blocks(hook, capsys):
    hook.SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    hook.SESSION_PATH.write_text(json.dumps({
        "started_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    }))
    sys.stdin = _StringStdin(json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "python scripts/gads_audit.py --customer 1"},
    }))
    hook.main()
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"


def test_malformed_input_falls_through_to_approve(hook, capsys):
    sys.stdin = _StringStdin("not-json")
    hook.main()
    assert json.loads(capsys.readouterr().out) == {"decision": "approve"}
