---
name: gads-gtag
description: Google tag / GA4 link / Enhanced Conversions audit. Scans the site for gtag/GTM, checks GA4 link, surfaces Enhanced Conversions enrollment.
user-invokable: true
argument-hint: "<customer-id> --site <url>"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-gtag` subagent. The agent runs:

```
python scripts/gads_gtag.py --customer <id> --site <url> --json
```

Returns the standard `summary / findings / metrics` shape.
