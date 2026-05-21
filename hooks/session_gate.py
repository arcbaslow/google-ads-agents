#!/usr/bin/env python3
"""Claude Code PreToolUse hook for the 24h session cap.

Reads the hook event from stdin. Approves anything that isn't a call into
the gads_* scripts. For gads_* Bash invocations, checks the local session
marker — if expired, returns a deny decision with the gcloud command the
user needs to run.

Wire it in settings.json:

  {
    "hooks": {
      "PreToolUse": [
        {
          "matcher": "Bash",
          "hooks": [{
            "type": "command",
            "command": "python ${CLAUDE_PROJECT_DIR}/hooks/session_gate.py"
          }]
        }
      ]
    }
  }

The script returns JSON like
  {"decision": "approve"}
  {"decision": "block", "reason": "..."}
so it can be a drop-in for any harness that follows the documented hook
protocol.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SESSION_PATH = Path.home() / ".claude" / "gads-session.json"
SESSION_MAX_HOURS = 24
GADS_MARKERS = ("scripts/gads_", "scripts\\gads_", "gads_auth", "gads_audit")


def _session_expired() -> bool:
    if not SESSION_PATH.exists():
        return True
    try:
        data = json.loads(SESSION_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return True
    started = data.get("started_at")
    if not started:
        return True
    try:
        ts = datetime.fromisoformat(started)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - ts > timedelta(hours=SESSION_MAX_HOURS)


def _is_gads_call(command: str) -> bool:
    return any(m in command for m in GADS_MARKERS)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        # If we can't parse the event, fall through and approve — the
        # session check shouldn't break unrelated tool calls.
        print(json.dumps({"decision": "approve"}))
        return 0

    tool = event.get("tool_name") or event.get("tool", "")
    command = (event.get("tool_input") or {}).get("command", "") if tool == "Bash" else ""

    if tool == "Bash" and _is_gads_call(command) and _session_expired():
        print(json.dumps({
            "decision": "block",
            "reason": (
                "Google Ads session expired (24h cap reached). Re-authenticate:\n"
                "  gcloud auth application-default login --scopes="
                "https://www.googleapis.com/auth/adwords,"
                "https://www.googleapis.com/auth/cloud-platform,openid,email\n"
                "Then run:\n"
                "  python scripts/gads_auth.py --use-profile <NAME>"
            ),
        }))
        return 0

    print(json.dumps({"decision": "approve"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
