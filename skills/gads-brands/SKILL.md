---
name: gads-brands
description: Look up brand catalogue entries. Review bounded PMax exclusions.
user-invokable: true
argument-hint: "<customer-id> suggest --query NAME [...]"
license: MIT
metadata:
  version: "0.1.0"
---

Look up catalogue entries and show their ID, name, URLs and state:

```
python scripts/gads_brands.py --customer <id> suggest --query "Acme" --json
```

Have the owner identify the intended catalogue entries and PMax campaign IDs.
An empty result does not prove the brand is absent. Do not guess brand IDs.
Read `docs/WRITES.md` before creating or reusing an exclusion list.

```
python scripts/gads_brands.py --customer <id> exclude --campaign-ids <campaign-id> --brand-ids <brand-id> --validate-only --json
python scripts/gads_brands.py --customer <id> exclude --campaign-ids <campaign-id> --brand-ids <brand-id> --apply --json
```

The adapter reviews actual operation JSON, asks y/N and validates before
application. Never supply automatic approval. It supports PMax only, in the
selected customer. Exact-content managed lists are reused without editing;
already-attached lists return no_op. Drift or duplicate names require manual
review. List removal, editing, Search restrictions and cross-account scope
are unsupported. Never replace brand exclusions with keyword negatives.
