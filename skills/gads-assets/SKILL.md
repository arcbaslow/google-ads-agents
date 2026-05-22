---
name: gads-assets
description: RSA ad-strength audit and PMax asset coverage / performance labels.
user-invokable: true
argument-hint: "<customer-id> rsa|pmax-assets [--days 28]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-assets` subagent. Runs:

```
python scripts/gads_assets.py --customer <id> rsa --days <N> --json
python scripts/gads_assets.py --customer <id> pmax-assets --json
```
