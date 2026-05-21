---
name: gads-display
description: Display campaign analysis. For placement safety, the agent hands off to gads-placements.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-display` subagent. The agent runs:

```
python scripts/gads_display.py --customer <id> --days <N> --json
```

Returns the standard `summary / findings / metrics` shape.
