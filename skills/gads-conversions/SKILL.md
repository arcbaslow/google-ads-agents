---
name: gads-conversions
description: Conversion action audit — primary-for-goal, attribution, lookback, double-count.
user-invokable: true
argument-hint: "<customer-id>"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-conversions` subagent. The agent runs:

```
python scripts/gads_conversions.py --customer <id> --health --json
```

Returns the standard `summary / findings / metrics` shape.
