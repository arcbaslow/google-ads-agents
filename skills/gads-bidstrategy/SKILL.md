---
name: gads-bidstrategy
description: Bid strategy fit per campaign based on conversion volume.
user-invokable: true
argument-hint: "<customer-id> [--days 30]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-bidstrategy` subagent. Runs:

```
python scripts/gads_bidstrategy.py --customer <id> --days 30 --json
```
