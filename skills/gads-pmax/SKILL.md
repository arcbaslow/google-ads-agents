---
name: gads-pmax
description: Performance Max analysis (asset groups, listing groups, search themes).
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-pmax` subagent. The agent runs:

```
python scripts/gads_pmax.py --customer <id> --days <N> --json
```

Returns the standard `summary / findings / metrics` shape.
