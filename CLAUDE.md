# CLAUDE.md

Notes for Claude Code working in `google-ads-agents`.

## Style

- Plain factual writing. No marketing copy. No emoji.
- Commit messages: short imperative sentence, sentence case acceptable.
  No `feat:` / `fix:` / `chore:` / Conventional Commits prefixes.
  No `Co-Authored-By` trailer. No "Generated with ..." footer.
- Comments only where the *why* is non-obvious. No restating what
  the code does in prose.

## Skills and subagents

Top-level router: `skills/gads/SKILL.md` — exposes `/gads <command>`.

Read paths:

- `gads-audit` — parallel orchestrator
- `gads-search`, `gads-pmax`, `gads-uac`, `gads-display`, `gads-shopping`, `gads-youtube`
- `gads-conversions`, `gads-gtag`
- `gads-keywords`, `gads-competitors`, `gads-placements`

Write / management paths:

- `gads-creation` — gated campaign creation
- `gads-placements` — exclusion writes after y/N confirmation

The audit orchestrator runs `gads-conversions` and `gads-gtag` first as
gates, then fans the rest out in parallel. Each agent returns JSON with
`summary`, `findings`, `metrics`.

## When to use the Bash tool instead of a skill

Skills are sugar for the same Python adapters. For one-off queries that
map to a single script flag, call the script directly via Bash:

```
python scripts/gads_search.py --customer <id> --days 28 --json
```

Don't spawn a subagent for a one-shot lookup.

## Auth

```
python scripts/gads_auth.py --check
python scripts/gads_auth.py --adc                    # print gcloud command
python scripts/gads_auth.py --add-profile NAME --developer-token TOKEN [--login-customer-id MCC]
python scripts/gads_auth.py --use-profile NAME
python scripts/gads_auth.py --list-profiles
python scripts/gads_auth.py --customers
python scripts/gads_auth.py --logout
```

One profile per MCC. Each carries its own developer token plus
login-customer-id. When the user works across multiple MCCs in a
session, suggest switching with `--use-profile` rather than re-entering
the token. The active profile name is shown by `--check`.

The 24h session cap is enforced in `gads_auth.enforce_session()`. After
expiry, every script raises and prints the gcloud command. Don't try to
work around it.

## Confirmation before writes

For every mutate:

1. Build the operation JSON.
2. Show it to the user.
3. Ask `y/N`.
4. On `y`, send. Use `validate_only=True` first when feasible.
5. Show the response.

Skill bodies wire this in; don't bypass.

## Placement rules

`scripts/placements_rules.json` is conservative and editable. When a
user disagrees with a category match, edit the rules file rather than
hard-coding an override in the agent.

## Asset role (2026-08)

Shipped and public. Maintenance mode: bugfixes, Google API version bumps,
and docs only - the active OSS build slot belongs to capi-kit. Role:
portfolio proof for the measurement practice; the README should keep a link
to Good Labs services. New features need an explicit owner decision.
