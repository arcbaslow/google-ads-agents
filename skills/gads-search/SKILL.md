---
name: gads-search
description: Search campaign analysis (impression share, search terms, negatives, bid strategy fit).
user-invokable: true
argument-hint: "<customer-id> [--days N] [--search-terms]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-search` subagent. The agent runs:

```
python scripts/gads_search.py --customer <id> --days <N> --json
python scripts/gads_search.py --customer <id> --days <N> --search-terms --json
```

Then returns the standard `summary / findings / metrics` shape.
