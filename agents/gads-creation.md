---
name: gads-creation
description: Plan campaigns, create reviewed PAUSED Search, Demand Gen and App campaigns, and edit App targets.
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
applies atomically. The operator runs these commands in their own
terminal; never supply automatic approval. New campaigns are PAUSED.
Search creates only a shell. Demand Gen and App create one ad group and one ad
using owner-supplied existing assets. No activation or budget/status editor is
included. After an uncertain apply response, inspect account state before
proposing a retry.

For Demand Gen or App, read the exact contracts in `docs/WRITES.md` and collect
every required key, including null optional values. Use `--demand-gen-spec`
or `--app-spec` with `--validate-only` or `--apply`; without a mode the adapter
returns `no_op`. Do not convert a legacy planning context into an executable
spec without the owner's explicit choices. Obtain the political declaration,
conversion confirmation and the three Demand Gen automation choices for the
selected ad type from the owner. Automation keys must match that ad type's
set in `docs/WRITES.md` exactly.

Demand Gen supports multi-asset and video-responsive ads, daily or
campaign-total budgets (total needs start and end dates), explicit channel
controls, and ad-group locations/languages. App supports install and engagement
campaigns with a fixed goal-to-strategy mapping and campaign locations/languages.
Collect conversion action resources when the App goal or engagement subtype
requires them, and one existing user list for engagement (the Firebase all-users
list qualifies; ads open the app's main screen, no deep link). Asset,
conversion action and user list resources must belong to the selected customer. API validation determines eligibility and asset
limits. There are no
asset uploads, audience creation, lookalikes, product/carousel ads or pre-registration.

Use `--app-target` only for an existing App CPA or ROAS target. The adapter reads
the campaign, checks the goal, previews one masked update and reports previous
and new values. It cannot switch goals or add targets to targetless strategies.
Other edits after creation are unsupported. Never pipe approval or bypass the
session gate.
