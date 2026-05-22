# Hooks

Two hooks ship with the project. Both are optional; the toolkit works
without either.

- `hooks/session_gate.py` — PreToolUse. Blocks `gads_*` invocations
  once the 24h local session is expired.
- `hooks/notify_telegram.py` — PostToolUse. Sends critical audit
  findings to Telegram.

Wire either or both in `~/.claude/settings.json` (or the project's
`.claude/settings.json`):

```json
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
    ],
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
```

## Session-gate hook

Runs before every Bash tool call. Reads the local session marker at
`~/.claude/gads-session.json`. If the marker is older than 24h and the
Bash command contains a `gads_*` reference, the hook returns a
`block` decision with the exact `gcloud auth application-default
login` command to run.

Tool calls that don't touch `gads_*` are approved unconditionally so
unrelated Bash usage isn't blocked.

## Telegram hook

Runs after every Bash tool call. Sends one Telegram message per audit
that contains at least one critical finding.

### Flow

```
Claude runs Bash tool
        |
        v
Tool finishes, output captured
        |
        v
Claude Code fires PostToolUse hooks
        |
        v
notify_telegram.py reads the event from stdin
        |
        +-- Was it a Bash call?            --- no --> exit
        +-- Did the command run gads_audit? -- no --> exit
        +-- Is Telegram configured?        --- no --> exit
        +-- Is the output valid JSON?      --- no --> exit
        |
        v
Parse audit, collect findings where severity == "critical"
        |
        +-- none --> exit
        v
Build HTML-formatted message:
   <b>gads audit (1234567890): 3 critical</b>
   - [gads-conversions] No primary conversion
   - [gads-gtag] gtag not found on site
   - ...
        |
        v
POST https://api.telegram.org/bot<TOKEN>/sendMessage
        |
        v
Telegram delivers to the chat
```

### Hook event shape

Claude Code pipes a JSON event to the hook's stdin:

```json
{
  "tool_name": "Bash",
  "tool_input": {
    "command": "python scripts/gads_audit.py --customer 123 --json"
  },
  "tool_response": {
    "output": "{\"customer_id\": \"123\", \"agents\": {...}}"
  }
}
```

### The four gates

Every PostToolUse fires on every tool call, so the hook stays cheap
and selective:

1. **Tool gate** — `tool_name` must be `Bash`.
2. **Command gate** — the Bash command string must contain
   `gads_audit`. Other `gads_*` scripts don't trigger a notification.
3. **Config gate** — `gads_notify.is_configured()` reads
   `~/.claude/gads-credentials.json` for the `telegram` block (token
   + chat_id). No config → silent exit. This is why wiring the hook
   in before setting up Telegram is safe.
4. **Format gate** — only valid JSON output is processed. If the
   audit ran in pretty-print mode, the hook bails. Parsing findings
   from human-readable text would be unreliable.

### Multi-account audits

For `gads_audit.py --all-customers`, the JSON shape is

```json
{"accounts": {"1234567890": {...audit...}, "9876543210": {...audit...}}}
```

The hook walks `accounts` and sends one Telegram message per account
that has critical findings. A fan-out across 10 customers can produce
0–10 messages depending on what's broken.

### Telegram POST

Bare stdlib, no SDK:

```python
url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": text[:4096],
    "parse_mode": "HTML",
    "disable_web_page_preview": "true",
}).encode()
urllib.request.urlopen(url, data=payload, timeout=5.0)
```

5-second timeout, no retries. If Telegram is unreachable or the token
is wrong, the hook fails quietly rather than slowing Claude Code.

### One-time setup

```
# 1. Create a bot in @BotFather, save the token
# 2. From the target chat, send the bot any message
python scripts/gads_notify.py --discover-chat-id --token <BOT_TOKEN>
# -> prints chat IDs that have messaged the bot

python scripts/gads_notify.py --setup --token <BOT_TOKEN> --chat-id <CHAT_ID>
python scripts/gads_notify.py --test    # sends a hello message
```

### What it does not do

- Doesn't fire on non-audit `gads_*` scripts. Broaden
  `_is_audit_command()` in the hook if you want to cover more.
- Doesn't fire on pretty-print output. Use `--json` when running an
  audit you want notifications for.
- Doesn't send anything below `severity: "critical"`. High / medium /
  low findings stay in the audit report.
- Doesn't retry or queue. If Telegram returns an error, the hook
  exits non-zero but Claude Code keeps going.
- Doesn't block tool calls. PostToolUse hooks observe; they don't
  veto. The session-gate is a PreToolUse hook, and it's the only one
  that can block.
