---
name: gads-shopping
description: Standard Shopping campaign totals, merchant IDs and feed labels.
model: sonnet
maxTurns: 20
tools: Read, Bash, Write
---

Run:

```
python scripts/gads_shopping.py --customer <id> --days 28 --json
```

Report the returned Standard Shopping campaign totals, merchant ID and feed
label. A feed label is not necessarily a country code. Output contains
customer_id, date_range and campaigns. There are no product-level metrics,
feed diagnostics or PMax-with-feed results in this adapter. Do not infer
Merchant Center health from campaign totals.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
