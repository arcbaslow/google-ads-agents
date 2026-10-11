---
name: gads-demandgen
description: Read Demand Gen campaigns, ads, assets and channel controls.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-demandgen` subagent.

Run `python scripts/gads_demandgen.py --customer <id> --days 28 --json`.

`--report campaigns` (default) returns `customer_id`, `date_range`, `campaigns`
and `limitations`: campaign status/subtype, bidding type, budget micros,
impressions, cost, conversions and conversion value. Cost remains in account
currency micros; conversions can be fractional. Clicks are omitted because
Demand Gen needs a separate click-type filter; do not infer CTR or CPC.

Use `--report ads` for campaign/ad-group/ad identity, ad type/status, policy
approval/review status for all ads regardless of activity. `--report assets` reads ad asset
links, roles, relative performance labels, enabled state, policy approval and
impressions. These reports return `rows`, `report`, `customer_id`, `date_range`
and `limitations`.

`--channel-controls` retains precedence over `--report` and reads current
ad-group channel configuration. Interpret channel_config before selected flags;
these settings do not establish historical delivery or surface spend.

The audit driver calls `audit(customer_id, days)` and includes campaign rows,
ads, channel_controls, `summary` and `findings`. Enabled ads in enabled or
paused campaigns produce one finding per ad: DISAPPROVED is high,
APPROVED_LIMITED is medium. Findings retain campaign, ad group and ad IDs.
No asset-performance or channel-control finding is inferred.

Metric reads can omit entities with no activity. Asset labels are relative
within the ad; asset impressions overlap and must not be summed. Frequency and
unique-user metrics are not read. Policy fields describe current state, not
historical serving. All commands are reads.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
