# google-ads-agents

[![tests](https://github.com/arcbaslow/google-ads-agents/actions/workflows/tests.yml/badge.svg)](https://github.com/arcbaslow/google-ads-agents/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![version](https://img.shields.io/badge/version-0.6.0-blue.svg)](CHANGELOG.md)

Multi-agent toolkit for Google Ads. Read, analyze, and gate-managed
mutate paths across Search, Performance Max, App, Display, Shopping,
and Video. Conversion-tracking and Google tag audits. Keyword research
via Keyword Plan. Auction Insights. Placement safety with built-in
exclusions for scams, bots, politics, religion, games, gambling, and
adult content. Campaign creation behind explicit context gates.

End-user Google sign-in. The default path uses the gcloud CLI — no
service account, no per-user OAuth client to register. Restricted
Workspaces can sign in with their own OAuth client instead (see Option B
in [docs/SETUP.md](docs/SETUP.md)). Hard 24-hour session cap on top of
token expiry.

## What is it?

Three layers:

1. Python adapters under `scripts/` that call the Google Ads API and
   return JSON.
2. Subagent definitions under `agents/`, one per analysis domain.
3. Skills under `skills/` that route `/gads <command>` to the right
   agent.

The audit orchestrator (`skills/gads-audit/`) gates on auth, runs
conversions + Google tag checks first, then fans out the rest in
parallel and renders a markdown report.

## Requirements

- Python 3.10 or newer
- Google Cloud SDK (`gcloud`)
- A Google Ads developer token registered against a manager account
  (one-time setup at https://ads.google.com/aw/apicenter)

## Install

### Recommended: `uv`

```
uv venv
uv pip install -r scripts/requirements.txt
uv run python scripts/gads_auth.py --check
```

[`uv`](https://github.com/astral-sh/uv) is a single-binary Python installer
and runner. One install of `uv` replaces the venv + pip dance and is
faster on cold-start.

### Plain venv (works everywhere)

```
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

pip install -r scripts/requirements.txt
```

### Optional extras

- `pip install -e ".[dev]"` — adds pytest + ruff for contributors.
- `pip install -r webapp/requirements.txt` — only needed to run the
  hosted sign-in service under `webapp/`.

## Authenticate

End-user sign-in through `gcloud`:

```
python scripts/gads_auth.py --adc
```

That prints the exact `gcloud auth application-default login` command
to run. Run it. A browser opens, sign in, grant scope. Then register a
profile for each manager account you work with:

```
python scripts/gads_auth.py --add-profile acme --developer-token <TOKEN> --login-customer-id <MCC-id>
python scripts/gads_auth.py --add-profile widgets --developer-token <TOKEN2> --login-customer-id <MCC2>
```

Switch the active profile any time:

```
python scripts/gads_auth.py --use-profile widgets
python scripts/gads_auth.py --list-profiles
```

A single-MCC setup just adds one profile and stays on it. The old flat
credentials file (one token, no profiles) is migrated to a "default"
profile automatically the first time the script runs.

If your Google Workspace blocks the gcloud sign-in, authenticate with your
own OAuth client instead — no admin needed. See "Option B" in
[docs/SETUP.md](docs/SETUP.md).

Verify:

```
python scripts/gads_auth.py --check
python scripts/gads_auth.py --customers
```

The session is good for 24 hours. After that the scripts refuse to run
until you sign in again. This is enforced locally regardless of token
TTL.

## Run the tests

The non-API logic is covered by pytest. Every adapter is mocked, so no
credentials and no network access are needed.

There are two independent suites:

```
pytest scripts/ -q      # the CLI adapters, agents, and hooks
pytest webapp/ -q       # the hosted sign-in service (needs webapp/requirements.txt)
```

Coverage spans the auth profile lifecycle and session expiry, GAQL
builder shapes, placement classification, campaign-context validation,
markdown and HTML report rendering, both hooks, search-term mining,
anomaly detection, audit history persistence and diff, recommendation
triage, bid-strategy fit rules, budget pacing thresholds, RSA strength
and PMax asset coverage, Quality Score component ranking,
demographic and location outlier rules, creative brief parsing,
Telegram formatting and credential storage, and the pluggable auth
backends (gcloud ADC vs. your own OAuth client, the token store, and
backend selection).

CI runs both suites on Python 3.10 / 3.11 / 3.12 / 3.13.

## Use it

In Claude Code, slash commands map to skills:

```
/gads audit <customer-id>
/gads search <customer-id>
/gads pmax <customer-id>
/gads uac <customer-id>
/gads display <customer-id>
/gads shopping <customer-id>
/gads youtube <customer-id>
/gads conversions <customer-id>
/gads gtag <customer-id> --site <url>
/gads keywords <customer-id> --seeds w1 w2 ...
/gads competitors <customer-id>
/gads placements <customer-id>
/gads recommendations <customer-id>     # Google's own actionable list
/gads anomalies <customer-id>           # day-level metric anomalies
/gads bidstrategy <customer-id>         # per-campaign bid strategy fit
/gads pacing <customer-id>              # MTD vs budget projection
/gads assets <customer-id> rsa          # responsive search ad strength
/gads assets <customer-id> pmax-assets  # PMax asset coverage
/gads brands <customer-id> suggest --query "Acme"
/gads geos <customer-id> --query "California"
/gads creative <customer-id> <site-url>  # site -> brief -> prompts (BYO images) -> upload + attach
/gads quality <customer-id>             # per-keyword QS + weakest component
/gads demographics <customer-id> all    # age + gender + device + location
/gads notify --setup --token T --chat-id C   # Telegram notifications
/gads history <customer-id> --changes   # change_event log
/gads history <customer-id> --diff a b  # compare two saved audits
/gads create <customer-id>
/gads audit --all-customers             # multi-account fan-out
```

Scripts pretty-print a compact summary by default. Pass `--json` for
machine output.

Outside Claude Code, the same things run as plain Python:

```
python scripts/gads_search.py --customer <id> --days 28 --negative-candidates --json
python scripts/gads_placements.py --customer <id> --days 28 --json
python scripts/gads_recommendations.py --customer <id> --json
python scripts/gads_anomalies.py --customer <id> --days 30 --baseline-days 14 --z 2.0 --json
python scripts/gads_history.py --customer <id> --changes --days 7 --json
python scripts/gads_audit.py --customer <id> --days 28 --site https://example.com --save-history --output audit.json
python scripts/gads_history.py --customer <id> --list --json
python scripts/gads_history.py --customer <id> --diff <ts-a> <ts-b> --json
python scripts/gads_report.py --input audit.json --format md --output audit.md
python scripts/gads_report.py --input audit.json --format html --output audit.html
python scripts/gads_creation.py --customer <id> --context-file ctx.json --validate-only --json
python scripts/gads_creation.py --customer <id> --context-file ctx.json --apply --json
python scripts/gads_apply.py --customer <id> negatives  --input negs.json --validate-only --json
python scripts/gads_apply.py --customer <id> placements --input excl.json --apply --json
```

## Hooks

Two optional hooks ship with the project:

- `hooks/session_gate.py` — PreToolUse. Blocks `gads_*` Bash calls
  once the 24h local session is expired and prints the gcloud command
  to re-authenticate.
- `hooks/notify_telegram.py` — PostToolUse. Sends critical audit
  findings to Telegram. Silent until configured.

See [docs/HOOKS.md](docs/HOOKS.md) for the settings.json wiring, the
event flow, the four gates the Telegram hook applies, multi-account
behaviour, and one-time setup.

## Placement safety

`gads_placements.py` enumerates every placement that served impressions
in the window and classifies each against
`scripts/placements_rules.json`. Default categories: `scam`, `bot`,
`politics`, `religion`, `games`, `gambling`, `adult`, `mfa`. The agent
shows the proposed exclusion list per category and waits for `y/N`
before writing the negative criteria.

The rules file is plain JSON. Edit it, point at a custom file via
`--rules`, or override per-run.

## Campaign creation

`gads-creation` refuses to propose a mutate until you've supplied:

1. business / vertical
2. website (reachability is checked)
3. primary goal (sales, leads, traffic, awareness, app installs)
4. analytics installed (verified via `gads-gtag`)
5. conversion actions correct (verified via `gads-conversions`)
6. daily budget
7. bidding strategy
8. geo and language
9. channel type

The script returns either `blocked` (with a list of missing or
contradictory fields) or `ready` (with a proposed mutate JSON). Nothing
is sent until the user approves the JSON. New campaigns are created
`PAUSED`.

## Project structure

```
google-ads-agents/
  .claude-plugin/  plugin manifest and marketplace config
  agents/          21 subagent definitions, one per domain
  scripts/         Python adapters and tests (the universal CLI)
  skills/          /gads command routing
  hooks/           session gate (PreToolUse) + Telegram notify (PostToolUse)
  webapp/          optional hosted sign-in service (FastAPI)
  docs/            setup and hooks guides, plus design specs
```

## Licensing

MIT. See [LICENSE](LICENSE).

## Related

Part of a set of marketing-measurement agent toolkits:

- [google-analytics-agent](https://github.com/arcbaslow/google-analytics-agent)
- [google-search-console-agent](https://github.com/arcbaslow/google-search-console-agent)
- [meta-ads-agents](https://github.com/arcbaslow/meta-ads-agents)
- [gtm-diff](https://github.com/arcbaslow/gtm-diff)
- [figma-taxonomy-gen](https://github.com/arcbaslow/figma-taxonomy-gen)

Built and maintained by [Good Labs](https://goodlabs.kz).
