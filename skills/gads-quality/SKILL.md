---
name: gads-quality
description: Quality Score audit. Per-keyword QS, deficient-component grouping, severity by QS.
user-invokable: true
argument-hint: "<customer-id> [--days 28] [--min-impressions 100]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-quality` subagent. Runs:

```
python scripts/gads_quality.py --customer <id> --days <N> --min-impressions <M> --json
```
