---
name: gads-pacing
description: Budget pacing - MTD vs target with month-end projection.
user-invokable: true
argument-hint: "<customer-id>"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-pacing` subagent. Runs:

```
python scripts/gads_pacing.py --customer <id> --json
```

Campaign rows carry `brand` (name match against `scripts/brand_rules.json`).
Brand underpacing is reported as `brand_underpacing` and is not a scale
candidate unless the user asks for it explicitly.
