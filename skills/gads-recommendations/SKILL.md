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
recommendation rows grouped by triage bucket. Spend-expanding
recommendations on brand campaigns (`scripts/brand_rules.json`) are
repeated under `brand_hold`; the agent does not recommend applying them
unless the user explicitly asks to scale brand.

Read results expose API field names such as `type`, not Python
protobuf attribute names such as `type_`. Preserve the returned enum labels.
