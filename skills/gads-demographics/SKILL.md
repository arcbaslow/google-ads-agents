---
name: gads-demographics
description: Age / gender / device / location breakdowns with CPA outlier detection.
user-invokable: true
argument-hint: "<customer-id> age|gender|device|location|all [--days 28]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-demographics` subagent. Runs:

```
python scripts/gads_demographics.py --customer <id> --days <N> --json age|gender|device|location|all
```

The age breakdown reads `age_range_view` and preserves the returned age-range
buckets. It reports observed performance, not a complete audience inventory.
