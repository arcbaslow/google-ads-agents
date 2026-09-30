---
name: gads-shopping
description: Standard Shopping campaign totals and feed labels.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-shopping` subagent. The agent runs:

```
python scripts/gads_shopping.py --customer <id> --days <N> --json
```

Returns `customer_id`, `date_range` and `campaigns`, including merchant ID
and feed label. Does not include PMax or Merchant Center feed diagnostics.
