---
name: gads-shopping
description: Shopping and PMax-with-feed analysis.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-shopping` subagent. The agent runs:

```
python scripts/gads_shopping.py --customer <id> --days <N> --json
```

Returns the standard `summary / findings / metrics` shape.
