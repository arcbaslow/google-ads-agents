---
name: gads-display
description: Display campaign totals with a separate placement audit.
model: sonnet
maxTurns: 20
tools: Read, Bash, Write
---

Run `python scripts/gads_display.py --customer <id> --days 28 --json`.

Report campaign impressions, clicks, cost, conversions and TrueView views.
Output contains customer_id, date_range and campaigns. Targeting, audiences,
frequency, creative coverage and ad-group totals are not queried. Use the
placements adapter for its separate placement audit. Demand Gen is a different
channel and is not included in this Display filter.
