---
name: gads-history
description: Change-event log and audit history. See what changed in the account recently; diff one saved audit against another.
user-invokable: true
argument-hint: "<customer-id> [--changes [--days N]] | [--list] | [--diff A B]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to `scripts/gads_history.py`.

```
python scripts/gads_history.py --customer <id> --changes --days 7 --json
python scripts/gads_history.py --customer <id> --list --json
python scripts/gads_history.py --customer <id> --diff <ts-a> <ts-b> --json
```

Audit history is auto-populated when `gads_audit.py` is invoked with
`--save-history`. The diff output groups findings into `resolved`,
`new`, and `unchanged`.
