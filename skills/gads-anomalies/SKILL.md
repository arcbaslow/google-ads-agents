---
name: gads-anomalies
description: Day-level anomaly detector for spend, conversions, clicks, and impressions.
user-invokable: true
argument-hint: "<customer-id> [--days 30] [--baseline-days 14] [--z 2.0]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-anomalies` subagent. The agent runs:

```
python scripts/gads_anomalies.py --customer <id> --days 30 --baseline-days 14 --z 2.0 --json
```

When anomalies are found, the agent cross-references the change-event
log via `gads-history` to see whether the spike correlates with a known
account change.
