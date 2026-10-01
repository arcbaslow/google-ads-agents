---
name: gads-youtube
description: YouTube / Video campaign analysis. For placement safety, the agent hands off to gads-placements.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-youtube` subagent. The agent runs:

```
python scripts/gads_youtube.py --customer <id> --days <N> --json
```

Returns `customer_id`, `date_range` and `campaigns`. Video views and view
rate use the v25 TrueView fields. No format or frequency breakdown is queried.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
