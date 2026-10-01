---
name: gads-demandgen
description: Read Demand Gen campaign status, bidding type and performance totals.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to `gads-demandgen`. Run:

```
python scripts/gads_demandgen.py --customer <id> --days 28 --json
```

Returns customer_id, date_range, campaigns and limitations. Also included in
the audit driver. Cost is in account-currency micros. Clicks and channel,
audience and asset breakdowns are not queried. No writes are supported.

Use `gads_demandgen.py --customer <id> --channel-controls --json` for current
ad-group channel configuration. Interpret channel_config before selected flags;
these settings do not show historical delivery or surface spend.
