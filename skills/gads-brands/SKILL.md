---
name: gads-brands
description: Look up brand catalogue entries. Brand exclusion writes are unavailable.
user-invokable: true
argument-hint: "<customer-id> suggest --query NAME [...]"
license: MIT
metadata:
  version: "0.1.0"
---

Run `python scripts/gads_brands.py --customer <id> suggest --query NAME --json`.
Review each suggestion's ID, name, primary URL and catalogue state with the user.
The catalogue can be incomplete. `exclude` returns `unsupported` without API
access; brand exclusions need shared-list management that is not implemented.
Do not substitute direct API calls or claim negatives are equivalent.
