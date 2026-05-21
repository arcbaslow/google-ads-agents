---
name: gads-recommendations
description: Triage Google's own account recommendations. Groups by apply-now / evaluate / ignore-by-default.
user-invokable: true
argument-hint: "<customer-id> [--include-dismissed]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-recommendations` subagent. The agent runs:

```
python scripts/gads_recommendations.py --customer <id> --json
```

Returns the standard `summary / findings / metrics` shape with
recommendation rows grouped by triage bucket.
