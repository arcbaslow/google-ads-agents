# Security policy

## Reporting a vulnerability

Open a private security advisory on the repo:
https://github.com/arcbaslow/google-ads-agents/security/advisories/new

Please do not file public issues for security problems.

## What's in scope

- Credential handling in `scripts/gads_auth.py`, `scripts/gads_authflow.py`,
  and `scripts/gads_tokenstore.py` - anything touching the developer
  token, refresh tokens, or the per-MCC profile store
- Bypasses of the 24-hour session cap in `gads_auth.enforce_session()`
- Bypasses of the `PreToolUse` session gate in `hooks/session_gate.py`
- Any CLI mutate path that reaches the Google Ads API without the
  confirm-before-write prompt (`gads_apply.py`, `gads_creation.py`,
  placement exclusion writes)
- Any MCP write tool in `scripts/gads_mcp.py` that sends a change
  without a matching single-use confirm token and the host's gate, or
  that sends one confirmed change more than once
- The hosted sign-in service under `webapp/`: OAuth state and CSRF
  handling, session fixation, token encryption at rest
  (`app/crypto.py`), and the token store (`app/tokenstore_db.py`)
- Telegram credential storage and the notification hook in
  `hooks/notify_telegram.py` - a chat ID and bot token are a
  send-anywhere capability
- Dependency-chain vulnerabilities in the Google client libraries
  pinned in `scripts/requirements.txt` and `webapp/requirements.txt`

## What's out of scope

- Misuse of the toolkit against an account you do not have legitimate
  access to
- Bugs in the upstream Google Ads API itself - report those to Google
- Issues that require an attacker with shell access to the user's
  machine (they already own `~/.claude/` and the gcloud config dir)
- Spend caused by an approved mutate. The CLI shows the operation JSON
  and waits for `y/N`; the MCP tools return a validated dry run and need
  a confirm token. Approving it is the operator's decision.

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

**Confirm before mutate.** Every CLI write builds the operation JSON,
shows it, and waits for `y/N`. `validate_only=True` is used first where
the API supports it. New campaigns are created `PAUSED`.

The MCP write tools (`register_writes` in `scripts/gads_mcp.py`) have no
terminal, so they confirm differently. A call without `confirm` reads
the targets, sends the operations with `validate_only=True` and returns
what would change plus a single-use token, valid 10 minutes and bound to
the tool, every argument and the state that was read. The identical call
with that token runs the host's `gate()`, then sends the same operations
once with no automatic retry. Changed arguments, a reused token or
changed state send nothing. A PR that adds a write path without one of
these two patterns will not be merged.

## Disclosure timeline

I aim to acknowledge security reports within 7 days and ship a fix or
mitigation within 30 days. For high-severity issues affecting active
users, both windows shrink.

Hosted sign-in callbacks require the initiating browser's short-lived HttpOnly
SameSite state cookie as well as a valid server-stored state. Production uses
Secure cookies. This check does not replace the existing session expiry or
per-user connection ownership checks.
