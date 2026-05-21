---
name: gads-creation
description: Campaign creation and management wizard with required context gates (business, website, goal, analytics installed, conversions correct). New campaigns are created PAUSED.
user-invokable: true
argument-hint: "<customer-id>"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-creation` subagent. The agent collects context one
field at a time, saves it to `/tmp/gads-ctx-<customer>.json`, runs:

```
python scripts/gads_creation.py --customer <id> --context-file /tmp/gads-ctx-<customer>.json --json
```

If `blocked`, the agent surfaces the missing/invalid fields and works
through them with the user. If `ready`, it shows the proposed mutate
JSON and waits for `y/N` before sending.

All new campaigns are created `PAUSED`. The user must unpause manually.
