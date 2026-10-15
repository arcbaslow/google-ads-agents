---
name: gads-uac
description: Read App campaigns, ad policy and asset links.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-uac` subagent.

Run `python scripts/gads_uac.py --customer <id> --days 28 --json`.

`--report campaigns` (default) returns `customer_id`, `date_range`,
`app_campaigns`, `by_sub_type` and `limitations`. Rows include app ID/store,
bidding goal, campaign status/subtype, bidding type, budget (daily amount or period total), impressions,
clicks, cost, conversions, conversion value and all_conversions. `by_sub_type`
groups the same rows by App, engagement and pre-registration subtype without
summing conversions. Conversions are not necessarily installs.

Use `--report ads` for ad identity, type, status, policy approval/review status,
all ads regardless of activity; `--report assets` for ad asset links, roles, enabled state,
relative performance labels, policy approval and impressions. These reports
return `rows`, `report`, `customer_id`, `date_range` and `limitations`.

The audit driver calls `audit(customer_id, days)` and includes campaign, ad and
asset rows plus `summary` and `findings`. Enabled ads in enabled or paused
campaigns produce one finding per ad: DISAPPROVED is high, APPROVED_LIMITED is
medium. Enabled asset links labeled LOW produce one low finding per link.
Findings retain entity IDs; asset identity includes the ad link, asset and role.

Metric reads can omit entities with no activity. Asset labels are relative
within the ad, and asset impressions must not be summed. Frequency/unique-user
metrics, SKAdNetwork schemas, Firebase links and Install Referrer health are
not queried. Policy fields describe current state, not historical serving.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
