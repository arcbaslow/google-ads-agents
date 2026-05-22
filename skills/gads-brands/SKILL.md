---
name: gads-brands
description: Brand exclusions for Performance Max. Catalogue search plus gated exclusion writes.
user-invokable: true
argument-hint: "<customer-id> suggest --query NAME [...] | exclude --input file [--validate-only|--apply]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to `scripts/gads_brands.py`. The agent walks through search →
review → validate → apply with explicit confirmation gates.
