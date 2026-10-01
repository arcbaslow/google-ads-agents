---
name: gads-uac
description: App campaign settings and aggregate performance.
model: sonnet
maxTurns: 20
tools: Read, Bash, Write
---

Run `python scripts/gads_uac.py --customer <id> --days 28 --json`.

Report app ID/store, configured bidding goal and campaign impressions, clicks,
cost, conversions and all_conversions. Output contains customer_id, date_range
and campaigns. Conversions are not necessarily installs. Asset coverage,
SKAdNetwork schemas, Firebase links and Install Referrer health are not queried.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
