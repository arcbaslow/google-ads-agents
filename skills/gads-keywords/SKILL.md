---
name: gads-keywords
description: Keyword research via the Keyword Plan service.
user-invokable: true
argument-hint: "<customer-id> --seeds w1 w2 ... [--language en] [--geo US]"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-keywords` subagent. The agent runs:

```
python scripts/gads_keywords.py --customer <id> --seeds <s1> <s2> --language <lang> --geo <geo> --json
```

The agent groups ideas by intent and surfaces volume + competition.

Supported languages: `en`, `es`, `de`, `fr`. Supported countries: `US`, `GB`,
`CA`, `AU`. Codes are case-insensitive; defaults remain `en` and `US` when
omitted. Unsupported codes and numeric IDs are rejected before API access.
Ask for an explicitly supported market; do not silently replace the user's
requested locale.
