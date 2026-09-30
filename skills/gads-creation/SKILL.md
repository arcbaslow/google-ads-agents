---
name: gads-creation
description: Collect campaign context and produce a planning draft. API creation is unavailable.
user-invokable: true
argument-hint: "<customer-id>"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-creation` subagent. Collect context and run:

```
python scripts/gads_creation.py --customer <id> --context-file context.json --json
```

`blocked` lists missing or invalid context. `planning_only` contains a
`campaign_plan`, not executable API operations. It does not prove the site or
measurement works. `--apply` and `--validate-only` return `unsupported` before
API access. Do not substitute a direct API call. A future writer must preserve
the reviewed settings and create the campaign PAUSED.
