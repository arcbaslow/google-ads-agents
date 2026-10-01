---
name: gads-audit
description: Collect supported adapter results and render a Markdown or HTML audit.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

Run the session check first. Stop on expiry and follow the sign-in instructions.
Do not work around the 24-hour cap.

```
python scripts/gads_auth.py --check
python scripts/gads_audit.py --customer <id> --days 28 --site <url> --output audit.json
python scripts/gads_report.py --input audit.json --format md --output audit.md
```

`--site` is optional. The driver runs its DEFAULT_AGENTS and optional site scan
in parallel; it does not block analysis on conversion or tag results. Review
conversion findings and static tag-scan limitations before interpreting the
other results. A snippet match does not establish healthy measurement.

The driver always emits JSON (no `--json` flag). Adapter shapes differ. Inspect
failed blocks and nested demographic findings explicitly; a completed audit
is not proof all reads succeeded. The report renderer supports `md` and `html`,
not PDF. Use `--save-history` to retain the driver's raw result.

`--all-customers` lists directly accessible customers, not every child of an
MCC. Keyword ideas, anomalies and creative inventory are separate commands;
there is no audit `--seeds` option.

Worker threads retain the caller's bound credential provider at both account
and adapter levels. This does not add a hosted audit endpoint or manager-tree
discovery. Providers used in parallel must support concurrent reads.

Reports, history and notification formatting include nested findings. New demographic
findings carry campaign, dimension and bucket identity. History uses entity metadata
when present; legacy findings without it use their full message, so changed text
can appear as a resolved and new finding.
