---
name: gads-competitors
description: Auction Insights and competitor pressure analysis.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-competitors` subagent. The agent runs:

```
python scripts/gads_competitors.py --customer <id> --days <N> --json
```

Returns the standard `summary / findings / metrics` shape.
