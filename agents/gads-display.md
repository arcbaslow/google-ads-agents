---
name: gads-display
description: Read Display campaigns and ad policy.
model: sonnet
maxTurns: 20
tools: Read, Bash, Write
---

Run `python scripts/gads_display.py --customer <id> --days 28 --json`.

`--report campaigns` (default) returns `customer_id`, `date_range`, `campaigns`
and `limitations`: campaign status/subtype, bidding type, budget micros,
impressions, clicks, cost, conversions and TrueView views. `--report ads`
returns `rows` with campaign/ad-group/ad identity, ad type and status, policy
approval/review status for all ads regardless of activity, plus report metadata.

The audit driver calls `audit(customer_id, days)` and includes campaign and ad
rows, `summary` and `findings`. Enabled ads in enabled or paused campaigns
produce one finding per ad: DISAPPROVED is high, APPROVED_LIMITED is medium.
Each finding retains campaign, ad group and ad IDs.

Metric reads can omit entities with no activity. Policy fields describe current
state, not historical serving. Frequency/unique-user metrics, targeting and
audiences are not read. v25 ad_group_ad_asset_view does not support responsive
Display ads, so there is no asset report. Use gads-placements for its separate
placement audit. Demand Gen is a separate channel.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
