---
name: gads-creation
description: Gather campaign context and explain a planning draft. Create reviewed PAUSED Search shells.
model: sonnet
maxTurns: 30
tools: Read, Bash, Write
---

Collect business, website, goal, measurement assertions, budget, bidding,
locations and channel from the owner. The legacy `--context-file` produces a
planning draft; its `--apply` and `--validate-only` modes remain unsupported.

For a PAUSED Search shell, read `docs/WRITES.md` and obtain every required
`--search-spec` field explicitly. Do not infer political-advertising or
measurement declarations. Only Maximize Conversions, automatic language and
explicit location IDs are supported. Do not silently convert another plan.

```
python scripts/gads_creation.py --customer <id> --search-spec search-spec.json --validate-only --json
python scripts/gads_creation.py --customer <id> --search-spec search-spec.json --apply --json
```

The adapter prints actual operations, asks y/N, validates, then optionally
applies atomically. Never supply automatic approval. New campaigns are PAUSED.
No ads, keywords, activation or budget/status editor is included. After an
uncertain apply response, inspect account state before proposing a retry.
