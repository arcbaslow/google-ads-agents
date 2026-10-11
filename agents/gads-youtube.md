---
name: gads-youtube
description: Read Video campaigns, ad policy, sub-formats and account suitability.
model: sonnet
maxTurns: 20
tools: Read, Bash, Write
---

Run `python scripts/gads_youtube.py --customer <id> --days 28 --json`.

`--report campaigns` (default) returns `customer_id`, `date_range`, `campaigns`
and `limitations`: campaign status/subtype, bidding type, budget (daily amount or period total),
impressions, clicks, cost, TrueView views/view rate and quartile rates.
TrueView views are not all video plays.

`--report ads` returns ad identity/type/status, policy approval/review status,
all ads regardless of activity. `--report formats` returns campaign rows segmented by
`segments.ad_sub_format_type` with impressions, cost and TrueView views. The v25
enum exposes non-skippable variants, UNSEGMENTED and unknown values; it is not a
complete video format taxonomy. `--report brand-safety` reads one current
`customer.video_brand_safety_suitability` row with `date_range: null`; this is an
account setting. These reports return `rows`, `report` and `limitations` plus
customer/date metadata.

The audit driver calls `audit(customer_id, days)` and includes campaign and ad
rows, `summary` and `findings`. Enabled ads in enabled or paused campaigns
produce one finding per ad: DISAPPROVED is high, APPROVED_LIMITED is medium.
Each finding retains campaign, ad group and ad IDs.

Metric reads can omit entities with no activity. Frequency/unique-user metrics
are not read. Policy fields describe current state, not historical serving.
Account suitability does not prove placement safety. Use gads-placements for
its separate placement audit.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
