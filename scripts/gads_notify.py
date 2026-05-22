"""Telegram notifications.

Two responsibilities:

  - Setup. Store a bot token and chat ID in the local credentials
    file (under a `telegram` key, separate from the Ads profile so it
    survives `--use-profile` switches).

  - Send. A small, dependency-free POST to api.telegram.org. The
    PostToolUse hook (hooks/notify_telegram.py) and human-facing
    scripts both use `send_message`.

To set up:

  1. Create a bot in BotFather, get a token.
  2. Open the bot in Telegram and send it any message.
  3. Run:
       python scripts/gads_notify.py --discover-chat-id --token <TOKEN>
     This calls getUpdates and prints the chat IDs that have spoken
     to the bot.
  4. Save:
       python scripts/gads_notify.py --setup --token <TOKEN> --chat-id <ID>
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import gads_auth
import gads_utils

API_BASE = "https://api.telegram.org"


# ---------- creds ----------

def load_telegram() -> dict[str, Any]:
    data = gads_auth.load_credentials()
    return data.get("telegram") or {}


def save_telegram(token: str, chat_id: str) -> None:
    data = gads_auth.load_credentials()
    data["telegram"] = {"token": token.strip(), "chat_id": str(chat_id).strip()}
    gads_auth.save_credentials(data)


def is_configured() -> bool:
    cfg = load_telegram()
    return bool(cfg.get("token") and cfg.get("chat_id"))


# ---------- send ----------

def send_message(text: str, *, parse_mode: str = "HTML",
                 token: str | None = None, chat_id: str | None = None,
                 timeout: float = 5.0) -> dict[str, Any]:
    """POST to Bot API. Returns the decoded response or {"ok": False, ...}."""
    cfg = load_telegram()
    token = token or cfg.get("token")
    chat_id = chat_id or cfg.get("chat_id")
    if not (token and chat_id):
        return {"ok": False, "error": "telegram not configured"}

    url = f"{API_BASE}/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text[:4096],          # Telegram caps message length
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=payload, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        return {"ok": False, "error": f"HTTP {e.code}: {body}"}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"ok": False, "error": str(e)}


def discover_chat_id(token: str, timeout: float = 5.0) -> dict[str, Any]:
    """Call getUpdates and return the distinct chat IDs found."""
    url = f"{API_BASE}/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        return {"ok": False, "error": str(e)}
    if not data.get("ok"):
        return data
    chats: dict[str, dict] = {}
    for update in data.get("result", []):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = str(chat.get("id"))
        if cid:
            chats[cid] = {
                "id": cid,
                "title": chat.get("title"),
                "username": chat.get("username"),
                "first_name": chat.get("first_name"),
                "type": chat.get("type"),
            }
    return {"ok": True, "chats": list(chats.values())}


# ---------- audit message formatting ----------

def format_critical_audit(audit: dict, limit: int = 10) -> str | None:
    """Build a Telegram message for an audit if it has any critical findings.

    Returns None when there's nothing worth pinging about.
    """
    cid = audit.get("customer_id", "?")
    findings: list[dict] = []
    for agent, out in (audit.get("agents") or {}).items():
        if not isinstance(out, dict):
            continue
        for f in out.get("findings") or []:
            if f.get("severity") == "critical":
                findings.append({"agent": agent, **f})

    if not findings:
        return None

    lines = [f"<b>gads audit ({cid}): {len(findings)} critical</b>"]
    for f in findings[:limit]:
        msg = _escape_html(str(f.get("message", "")))
        lines.append(f"• [{f['agent']}] {msg}")
    if len(findings) > limit:
        lines.append(f"…and {len(findings) - limit} more")
    return "\n".join(lines)


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--setup", action="store_true",
                   help="Save token and chat ID")
    p.add_argument("--token", help="Bot token from BotFather")
    p.add_argument("--chat-id", help="Target chat ID")
    p.add_argument("--discover-chat-id", action="store_true",
                   help="Call getUpdates and print chat IDs that messaged the bot")
    p.add_argument("--send", metavar="TEXT", help="Send a one-off message")
    p.add_argument("--test", action="store_true",
                   help="Send a hello message to confirm the config works")
    p.add_argument("--status", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.setup:
        if not (args.token and args.chat_id):
            p.error("--setup requires --token and --chat-id")
        save_telegram(args.token, args.chat_id)
        gads_utils.emit({"status": "saved", "configured": True}, args.json)
        return 0

    if args.discover_chat_id:
        if not args.token:
            p.error("--discover-chat-id requires --token")
        gads_utils.emit(discover_chat_id(args.token), args.json)
        return 0

    if args.status:
        cfg = load_telegram()
        gads_utils.emit({
            "configured": is_configured(),
            "chat_id": cfg.get("chat_id"),
            "token": "set" if cfg.get("token") else "missing",
        }, args.json)
        return 0

    if args.test:
        out = send_message("gads-notify is wired up.")
        gads_utils.emit(out, args.json)
        return 0 if out.get("ok") else 1

    if args.send:
        out = send_message(args.send)
        gads_utils.emit(out, args.json)
        return 0 if out.get("ok") else 1

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
