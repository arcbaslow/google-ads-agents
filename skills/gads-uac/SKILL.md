---
name: gads-uac
description: App campaign (UAC) analysis.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-uac` subagent. The agent runs:

```
python scripts/gads_uac.py --customer <id> --days <N> --json
```

Returns the standard `summary / findings / metrics` shape.
