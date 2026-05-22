#!/usr/bin/env python3
"""Claude Code PostToolUse hook for Telegram audit notifications.

Reads the hook event from stdin. If the tool was a Bash invocation of
gads_audit.py and the captured output is a parsable audit JSON with
critical findings, format the findings and POST to Telegram. Silent on
anything else.

If Telegram isn't configured, the hook exits cleanly without trying.
This makes the hook safe to leave wired in settings.json even before
the user runs `python scripts/gads_notify.py --setup`.

Wire it in settings.json:

  {
    "hooks": {
      "PostToolUse": [
        {
          "matcher": "Bash",
          "hooks": [{
            "type": "command",
            "command": "python ${CLAUDE_PROJECT_DIR}/hooks/notify_telegram.py"
          }]
        }
      ]
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# The hook lives in hooks/. Make scripts/ importable so we can reuse
# the formatter and the send_message helper.
_THIS = Path(__file__).resolve()
_SCRIPTS = _THIS.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import gads_notify  # noqa: E402


def _is_audit_command(command: str) -> bool:
    return "gads_audit" in command


def _parse_audit_json(output: str) -> dict | None:
    """The audit script prints either JSON or pretty text. Only the JSON
    path carries enough structure for the formatter; for pretty mode we
    just bail."""
    if not output:
        return None
    s = output.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    if (event.get("tool_name") or event.get("tool")) != "Bash":
        return 0

    command = (event.get("tool_input") or {}).get("command", "")
    if not _is_audit_command(command):
        return 0

    if not gads_notify.is_configured():
        return 0

    response = event.get("tool_response") or {}
    output = response.get("output") or response.get("stdout") or ""
    audit = _parse_audit_json(output)
    if not audit:
        return 0

    # --all-customers wraps audits under `accounts`. Walk the children.
    if "accounts" in audit:
        for cid, child in audit["accounts"].items():
            msg = gads_notify.format_critical_audit(child)
            if msg:
                gads_notify.send_message(msg)
        return 0

    msg = gads_notify.format_critical_audit(audit)
    if msg:
        gads_notify.send_message(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
