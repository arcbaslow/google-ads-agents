---
name: gads-pacing
description: Budget pacing — MTD vs target with month-end projection.
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
