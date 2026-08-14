# Changelog

## 0.6.0 - 2026-08-14

- Version metadata corrected. `pyproject.toml` and
  `.claude-plugin/plugin.json` both still read `0.1.0` — they were never
  bumped across the 0.2.0 through 0.6.0 releases, so anything reading
  the package or plugin version got the wrong answer. Both now track
  the changelog.
- CI on Python 3.10 / 3.11 / 3.12 / 3.13 running ruff plus both test
  suites (`scripts/` and `webapp/tests/`).
- Added `CONTRIBUTING.md`, `SECURITY.md`, issue and pull-request
  templates, and Dependabot config covering the root and `webapp/`
  requirement sets.
- `pyproject.toml` gained project URLs, trove classifiers, keywords,
  and a `testpaths` covering both suites. The ruff lint selection is
  pinned explicitly rather than inherited from ruff's implicit default,
  which changes between releases and would otherwise turn a ruff
  upgrade into a red CI run.
- README: badges, a `uv` install path, and a corrected project
  structure. The test section no longer carries a hardcoded test count
  and now names both suites.


- Pluggable auth backends: `scripts/gads_authflow.py` defines an
  `AuthBackend` protocol with two implementations. `GcloudAdcBackend`
  (default) wraps `google.auth.default()`; `OAuthClientBackend` builds
  credentials from a stored refresh token and refreshes them without any
  gcloud dependency. `gads_auth.get_credentials()` dispatches on the
  profile's `auth_method` and still enforces the 24h session cap for
  both paths.
- Bring-your-own OAuth client for restricted Google Workspaces. A new
  `--oauth-login` runs an `InstalledAppFlow` loopback browser flow
  (`--no-browser` for headless) using a Desktop OAuth client you create
  in your own org; it stores the refresh token on the target profile.
  `--set-oauth` is a manual fallback for pasting a pre-obtained refresh
  token. Internal Workspace OAuth apps skip Google verification for the
  restricted `adwords` scope, sidestepping org third-party-app blocks.
- Token-store seam: `scripts/gads_tokenstore.py` isolates OAuth material
  behind a `TokenStore` interface (`LocalFileTokenStore` keeps it in the
  existing 0600 credentials file). A future web app can drop in a
  `DbTokenStore` keyed by user id without touching the backends or
  `gads_client`.
- Profiles gain `auth_method` (`gcloud_adc` default or `oauth_client`).
  Migrated and existing profiles default to `gcloud_adc`, so current
  setups are unaffected.
- New dependency: `google-auth-oauthlib`.
- Tests grew from 132 to 154. Design and plan under
  `docs/superpowers/`.

## 0.5.0

- Image-asset wizard: `scripts/gads_creative.py` plus the
  `gads-creative` agent and skill. Four subcommands:
  1. `brief` — fetch the advertiser's site, parse title / meta /
     headings / og:image / hex colors into a structured creative
     brief.
  2. `prompts` — emit prompt-template scaffolding for every PMax
     image format (MARKETING_IMAGE 1.91:1, SQUARE 1:1, PORTRAIT 4:5,
     LOGO 1:1, LANDSCAPE_LOGO 4:1) with brief snippets and a default
     negative prompt. The agent fills in copy.
  3. `upload` — push a PNG to Google Ads as an `ImageAsset`. Behind
     `--validate-only` / `--apply`.
  4. `attach` — link an uploaded asset to a PMax asset group (any of
     5 image field types) or a Search campaign (image extension).
- No bundled image generator. Google Ads' free PMax generator is
  UI-only (not on the API); we don't ship a paid provider as the
  default. The agent hands the user the prompts; the user generates
  with whatever they choose (Ads UI, Midjourney, Imagen on Vertex, a
  stock library, a designer) and comes back with PNGs.
- Tests grew from 123 to 132.

## 0.4.0

- Quality Score audit: `scripts/gads_quality.py` plus the
  `gads-quality` agent and skill. Per-keyword QS with its three
  components (expected CTR, ad relevance, landing page), weakest-
  component ranking (canonical-order tiebreak, not alphabetical),
  severity by QS, and a `weakest_component_counts` aggregate that
  tells you which lever to pull first.
- Demographic and location breakdowns: `scripts/gads_demographics.py`
  plus the `gads-demographics` agent and skill. Sub-commands `age`,
  `gender`, `device`, `location`, `all`. Outlier rule: bucket CPA
  ≥ 2x campaign mean AND ≥ 5% of spend → flagged; ≥ 3x → high
  severity. Zero-conversion buckets and tiny-share buckets are
  ignored.
- Telegram notifications: `scripts/gads_notify.py` and a new
  PostToolUse hook at `hooks/notify_telegram.py`. The hook fires only
  on audit JSON with critical findings, walks `--all-customers`
  results, and is a no-op until the user runs `--setup`. Dependency-
  free (stdlib urllib only).
- Audit fan-out now includes `gads-quality` and `gads-demographics`.
- Tests grew from 95 to 123.

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
