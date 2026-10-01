---
name: gads-display
description: Display campaign totals with a separate placement audit.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-display` subagent.

Run `python scripts/gads_display.py --customer <id> --days 28 --json`.

Report campaign impressions, clicks, cost, conversions and TrueView views.
Output contains customer_id, date_range and campaigns. Targeting, audiences,
frequency, creative coverage and ad-group totals are not queried. Use the
placements adapter for its separate placement audit. Demand Gen is a different
channel and is not included in this Display filter.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
