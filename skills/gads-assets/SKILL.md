---
name: gads-assets
description: RSA ad-strength audit and PMax linked asset inventory.
user-invokable: true
argument-hint: "<customer-id> rsa|pmax-assets [--days 28]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-assets` subagent. Runs:

```
python scripts/gads_assets.py --customer <id> --days <N> --json rsa
python scripts/gads_assets.py --customer <id> --json pmax-assets
```

PMax returns counts by field type and link status, plus explicit limitations.
It does not score assets, infer serving, or assess required creative coverage.
