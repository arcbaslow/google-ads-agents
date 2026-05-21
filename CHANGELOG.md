# Changelog

## 0.1.0

Initial release.

- gcloud Application Default Credentials as the auth path. No service
  account, no per-user OAuth client. Hard 24-hour local session cap on
  top of token expiry.
- Per-MCC profiles. Each profile owns its own developer token and
  optional `login-customer-id`. Switch with `--use-profile`. The old
  single-token credentials file auto-migrates to a `default` profile.
- Twelve specialist subagents: gads-search, gads-pmax, gads-uac,
  gads-display, gads-shopping, gads-youtube, gads-conversions,
  gads-gtag, gads-keywords, gads-competitors, gads-placements,
  gads-creation.
- Audit orchestrator (`scripts/gads_audit.py`) fans out every read-path
  domain and merges results. Markdown and HTML renderers in
  `scripts/gads_report.py`.
- Placement safety scanner with bundled rules for scams, bots,
  politics, religion, games, gambling, adult, and made-for-ads sites.
  Exclusions are always shown before writing.
- Campaign-creation wizard with required context gates (business,
  website, goal, analytics-installed, conversions-correct, budget,
  bidding, geos, languages, channel). Supports `--validate-only` dry
  run and `--apply`. New campaigns are created `PAUSED`.
- PreToolUse hook (`hooks/session_gate.py`) that blocks `gads_*`
  invocations when the 24h session is expired.
- pytest suite covering auth profile logic, utilities, GAQL builders,
  placement classification, creation validation, report rendering, and
  the session hook.
