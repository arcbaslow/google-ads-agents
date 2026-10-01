---
name: gads-competitors
description: Campaign search impression-share metrics; no competitor domains.
model: sonnet
maxTurns: 20
tools: Read, Bash, Write
---

Run `python scripts/gads_competitors.py --customer <id> --days 28 --json`.

Compare search impression share, top/absolute-top impression share and share
lost to rank or budget. Output contains customer_id, date_range and rows.
This query does not return competitor domains, overlap, position-above or
outranking rates. Do not invent a per-domain Auction Insights table.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
