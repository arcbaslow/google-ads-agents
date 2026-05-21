---
name: gads-placements
description: Display + YouTube placement safety audit with built-in exclusions for scams, bots, politics, religion, games, gambling, adult, and MFA sites. Never excludes without explicit confirmation.
user-invokable: true
argument-hint: "<customer-id> [--days N] [--rules path]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-placements` subagent. The agent runs:

```
python scripts/gads_placements.py --customer <id> --days <N> --json
```

Then walks the user through the proposed exclusions per category and
asks `y/N` before writing.

Rules file: `scripts/placements_rules.json`. Override with `--rules`.
