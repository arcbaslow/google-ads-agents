---
name: gads-geos
description: Resolve location names to Google Ads GeoTargetConstant IDs.
user-invokable: true
argument-hint: "<customer-id> --query NAME [NAME ...] [--country US] [--locale en]"
license: MIT
metadata:
  version: "0.1.0"
---

Runs:

```
python scripts/gads_geos.py --customer <id> --query "California" "New York City" --json
```

Useful when building the creation wizard context — users say "US" or
"California," the wizard needs IDs like `2840` or `21137`.
