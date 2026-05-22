# Changelog

## 0.3.0

- Pretty-print fallback: `gads_utils.emit()` now renders a compact
  human-readable summary when `--json` isn't passed. Includes a small
  ASCII table renderer for list-valued payloads (search terms,
  anomalies, change events, keyword ideas, etc.).
- Brand exclusions for Performance Max: `scripts/gads_brands.py` plus
  the `gads-brands` agent and skill. `suggest` searches Google's brand
  catalogue; `exclude` attaches negative brand criteria to specified
  PMax campaigns behind `--validate-only` / `--apply`.
- Geo lookup helper: `scripts/gads_geos.py`. Resolves location names
  to GeoTargetConstant IDs via GeoTargetConstantService.
- Bid strategy fit recommender: `scripts/gads_bidstrategy.py` plus
  the `gads-bidstrategy` agent and skill. Applies the standard
  volume-vs-strategy rules and flags Smart Bidding running below the
  learning floor.
- Budget pacing analyzer: `scripts/gads_pacing.py` plus the
  `gads-pacing` agent and skill. MTD spend vs daily budget,
  month-end projection, over/under-pacing flags with severity tied
  to deviation magnitude.
- Multi-account audit: `gads_audit.py --all-customers` fans out
  across every accessible customer in parallel (capped by
  `--account-workers`, default 3).
- Ad-strength + PMax asset audit: `scripts/gads_assets.py` plus the
  `gads-assets` agent and skill. RSA strength flags and PMax
  asset-coverage gap / LOW-label findings.
- Tests grew from 68 to 95.

## 0.2.0

- Audit driver runs every agent in parallel (`concurrent.futures`,
  six workers by default). Adds `--save-history` to persist the merged
  audit under `~/.claude/gads-audit-history/<customer>/`.
- Recommendations API integration: `scripts/gads_recommendations.py`,
  the `gads-recommendations` agent and skill. Pulls Google's own
  account recommendations, groups by type, and surfaces base→potential
  impact.
- Change-event log + audit history: `scripts/gads_history.py` with
  `--changes`, `--list`, and `--diff`. The diff classifies findings as
  resolved, new, or unchanged across runs.
- Day-level anomaly detector: `scripts/gads_anomalies.py`. Trailing
  14-day baseline, z-score threshold (default 2.0), flags spend /
  conv / clicks / impressions swings per campaign per day.
- Write paths in `scripts/gads_apply.py`: negative keywords on a
  campaign and account-wide placement exclusions. Both behind
  `--validate-only` and `--apply`.
- Search-term mining: `gads_search.py --negative-candidates` filters
  raw search-term rows into a costed candidate list with severity-
  scaled findings.
- Tests grew from 53 to 68.

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
