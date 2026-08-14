# Contributing

Patches welcome. Keep changes small and focused.

## Setup

```
git clone https://github.com/arcbaslow/google-ads-agents
cd google-ads-agents
uv venv && uv pip install -e ".[dev]"
# or: python -m venv .venv && pip install -e ".[dev]"

# only if you're touching webapp/
pip install -r webapp/requirements.txt
```

## Before you push

```
ruff check scripts/ hooks/ webapp/
pytest scripts/ -q
pytest webapp/tests/ -q
```

All three must pass. CI runs them on every PR across Python 3.10 /
3.11 / 3.12 / 3.13.

## Commit style

Plain imperative sentence, sentence-case acceptable. No Conventional
Commits prefixes (`feat:`, `fix:`, `chore:`). No `Co-Authored-By:`
trailers, no `Generated with...` footers, no emoji.

Examples of the desired tone:

- `migrate the flat credentials file to a default profile`
- `fix z-score baseline window in anomaly detection`
- `pin upper bound on google-ads`
- `rewrite the Option B auth section in SETUP.md`

PR refs `(#NNN)` only when one exists.

## The two rails, and why they are not negotiable

**Every mutate confirms first.** Build the operation JSON, show it, ask
`y/N`, then send. Use `validate_only=True` first wherever the API
supports it. New campaigns are created `PAUSED`. A write path that
skips this will not be merged — this toolkit spends real money, and an
agent that can mutate without a human in the loop is a different and
much worse product.

**The 24-hour session cap stays.** `gads_auth.enforce_session()` is
enforced locally, independent of token TTL, because an ADC refresh
token outlives a working session. Don't add a flag to disable it.

## Google Ads API versioning

Google ships a new API version roughly every four months and sunsets
old ones on a published schedule. Verify resource, field, and enum
names against the current official reference before touching request
code — not from memory. Version bumps are their own PR, with the
suite run and a `CHANGELOG.md` note.

## What I'll accept

- Bug fixes with a regression test
- New read surfaces backed by the official Google Ads API
- Better heuristics in `placements_rules.json`, the anomaly z-score
  rules, pacing thresholds, or bid-strategy fit — with a reason the
  current one is wrong
- Google Ads API version bumps
- Documentation fixes
- CI improvements

## What I'll push back on

- Write paths without confirm-before-mutate
- Anything that weakens or bypasses the session cap or the session gate
  hook
- Adding paid SaaS dependencies
- Big rewrites without a discussion first — open an issue describing
  the shape before the work

## Local-only files

- `gads-credentials.json` / `gads-session.json` — developer tokens,
  per-MCC profiles, and local session state. Already gitignored.
- `~/.config/gcloud/application_default_credentials.json` — gcloud ADC.
- `client_secret.json` — own-OAuth-client mode.
- `.env` — webapp settings, including the Fernet keys.

If you accidentally stage any of these, `git restore --staged <file>`
before committing.

## Tests

Every adapter is mocked. CI never hits the Google Ads API and needs no
credentials. Keep it that way: any test that touches the network must
be guarded behind an env var and skipped by default.

`scripts/conftest.py` redirects the credentials and session paths to a
temp directory and strips `GOOGLE_ADS_*` env vars for every test.
Don't write a test that depends on real user state.

## License

By contributing you agree your changes are released under the MIT
license, same as the rest of the repo.
