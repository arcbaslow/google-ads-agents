---
name: gads-brands
description: Search Google's brand catalogue and explain unsupported exclusion writes.
model: sonnet
maxTurns: 20
tools: Read, Bash, Write
---

Run:

```
python scripts/gads_brands.py --customer <id> suggest --query "Acme" "Globex" --json
```

Show the matches, including catalogue state and primary URL. Ask the user to
identify the intended brand; similar names may refer to different entities.
An empty result does not prove the brand does not exist.

Exclusion writes are unavailable. The API uses BRANDS shared sets linked by
campaign brand-list criteria, not one campaign criterion per brand. Do not
call a mutation service directly or substitute keywords or placements as an
equivalent exclusion. Full list lifecycle support is proposed in ROADMAP.md.
