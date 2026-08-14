# Security policy

## Reporting a vulnerability

Open a private security advisory on the repo:
https://github.com/arcbaslow/google-ads-agents/security/advisories/new

Please do not file public issues for security problems.

## What's in scope

- Credential handling in `scripts/gads_auth.py`, `scripts/gads_authflow.py`,
  and `scripts/gads_tokenstore.py` — anything touching the developer
  token, refresh tokens, or the per-MCC profile store
- Bypasses of the 24-hour session cap in `gads_auth.enforce_session()`
- Bypasses of the `PreToolUse` session gate in `hooks/session_gate.py`
- Any mutate path that reaches the Google Ads API without the
  confirm-before-write prompt (`gads_apply.py`, `gads_creation.py`,
  placement exclusion writes)
- The hosted sign-in service under `webapp/`: OAuth state and CSRF
  handling, session fixation, token encryption at rest
  (`app/crypto.py`), and the token store (`app/tokenstore_db.py`)
- Telegram credential storage and the notification hook in
  `hooks/notify_telegram.py` — a chat ID and bot token are a
  send-anywhere capability
- Dependency-chain vulnerabilities in the Google client libraries
  pinned in `scripts/requirements.txt` and `webapp/requirements.txt`

## What's out of scope

- Misuse of the toolkit against an account you do not have legitimate
  access to
- Bugs in the upstream Google Ads API itself — report those to Google
- Issues that require an attacker with shell access to the user's
  machine (they already own `~/.claude/` and the gcloud config dir)
- Spend caused by an approved mutate. The toolkit shows the operation
  JSON and waits for `y/N`; approving it is the operator's decision.

## Where credentials live on disk

- gcloud ADC (default path):
  `~/.config/gcloud/application_default_credentials.json`
- Developer tokens and per-MCC profiles:
  the credentials file managed by `gads_auth.py` (file mode `0600` on
  POSIX)
- Local session state: the session file managed by `gads_auth.py`,
  which is what the 24-hour cap reads
- Own-OAuth-client mode: the token store managed by
  `gads_tokenstore.py`
- Telegram bot token and chat ID: configured via
  `gads_notify.py --setup`

The toolkit never logs credentials to stdout, never sends them to a
third party, and never bakes them into report files. The developer
token in particular is redacted in `--check` output.

## Two safety rails worth knowing about

**24-hour session cap.** Enforced locally in
`gads_auth.enforce_session()`, independent of token TTL. After expiry
every script refuses to run and prints the gcloud command. This is
deliberate: an ADC refresh token outlives a working session, and a
long-lived agent shell holding write scope on an ad account is a
standing risk.

**Confirm before mutate.** Every write builds the operation JSON, shows
it, and waits for `y/N`. `validate_only=True` is used first where the
API supports it. New campaigns are created `PAUSED`. A PR that adds a
write path without this pattern will not be merged.

## Disclosure timeline

I aim to acknowledge security reports within 7 days and ship a fix or
mitigation within 30 days. For high-severity issues affecting active
users, both windows shrink.
