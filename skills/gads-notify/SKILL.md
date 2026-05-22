---
name: gads-notify
description: Telegram notifications. Setup, discover-chat-id, test, send. Pairs with the PostToolUse hook for automatic critical-finding alerts.
user-invokable: true
argument-hint: "--setup --token T --chat-id C | --discover-chat-id --token T | --test | --send TEXT | --status"
license: MIT
metadata:
  version: "0.1.0"
---

Runs `scripts/gads_notify.py`. The PostToolUse hook at
`hooks/notify_telegram.py` reuses this module to send a single
Telegram message whenever a `gads_audit.py` invocation surfaces
critical findings.

Setup flow:

1. Create a bot in @BotFather, save the token.
2. Send the bot any message from the target chat (1:1 or group).
3. `python scripts/gads_notify.py --discover-chat-id --token <TOKEN>`
   lists every chat that has spoken to the bot.
4. `python scripts/gads_notify.py --setup --token <TOKEN> --chat-id <ID>`
5. `python scripts/gads_notify.py --test` to confirm.
