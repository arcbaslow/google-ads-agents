---
name: gads-pmax
description: Performance Max asset-group totals.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-pmax` subagent.

Run `python scripts/gads_pmax.py --customer <id> --days 28 --json`.

Report asset-group IDs, names, status, campaign identity, impressions, clicks,
cost, conversions and conversion value. Output contains customer_id, date_range
and asset_groups. This read has no channel breakdown, listing-group structure,
search themes, audience signals or bidding settings. Totals alone cannot
establish cannibalisation or justify brand exclusions.
