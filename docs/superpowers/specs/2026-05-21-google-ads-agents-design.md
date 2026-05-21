# google-ads-agents — design

Multi-agent toolkit for Google Ads. Read, analyze, manage and create campaigns
across all campaign types. End-user Google sign-in via the gcloud CLI; no
service account, no per-user OAuth client to register. Hard 24-hour session
cap on top of whatever expiry Google issues.

## Scope

Read paths and write paths for:

- Search
- Performance Max
- Universal App Campaigns (App / UAC)
- Display
- Shopping
- Video (YouTube)
- Conversion tracking and the Google tag (gtag, GA4 link, Floodlight)
- Keyword research
- Auction Insights / competitor analysis
- Placement audits for Display and YouTube, with a built-in ban list
  (scams, bots, politics, religion, games, adult) plus low-quality / MFA
  sites

Plus a campaign-creation flow that gates on user-confirmed context:
business, website, primary goal, analytics installation status, conversion
correctness.

## Auth

The Google Ads API requires two things at request time:

1. An OAuth 2.0 access token with the `https://www.googleapis.com/auth/adwords` scope.
2. A developer token registered against a Google Ads manager account.

We will not register an app's OAuth client and we will not use service
accounts. Instead the user runs:

```
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/adwords,\
https://www.googleapis.com/auth/cloud-platform,\
openid,email
```

The gcloud CLI is a registered Google application; this is genuine end-user
SSO via the browser. The library calls `google.auth.default()` to pick up
the resulting application default credentials, refreshing transparently.

The developer token is a one-time setup at
`https://ads.google.com/aw/apicenter` and is stored locally at
`~/.claude/gads-credentials.json` (file mode 0600). It is account-level,
not user-level, so it is the same value regardless of who signs in.

`login-customer-id` is the manager (MCC) account ID used as the request
context; we read it from the credentials file, the `GOOGLE_ADS_LOGIN_CUSTOMER_ID`
env var, or via `--login-customer-id` on each command.

### 24-hour session cap

Every script reads the `session_started_at` timestamp from
`~/.claude/gads-session.json`. If more than 24 hours have passed, the
script refuses to run and prints the gcloud command to re-authenticate.
This is independent of token expiry — it is a hard rotation on the local
session marker. `gads_auth.py --check` is the canonical way to see the
remaining time.

## Layered architecture

Three layers, same pattern as `google-analytics-agent`:

```
google-ads-agents/
  scripts/    Python adapters that call the Google Ads API and return JSON
  agents/     markdown subagent definitions Claude Code dispatches
  skills/     /gads <command> routing for Claude Code
  hooks/      placeholder for pre/post-tool guards (e.g. session expiry block)
  docs/       setup guide
```

Python is the source of truth. Agents read JSON. Skills route commands.

## Sub-agents

| Agent             | Purpose                                                                     |
| ----------------- | --------------------------------------------------------------------------- |
| gads-search       | Search campaign performance, query mining, negative-keyword candidates      |
| gads-pmax         | Performance Max asset-group and listing-group audit, search-themes review  |
| gads-uac          | App campaign install / in-app event analysis, asset performance             |
| gads-display      | Display campaign performance and placement audit                            |
| gads-shopping     | Standard and Performance Max Shopping, feed-level diagnostics               |
| gads-youtube      | Video campaign performance and placement audit                              |
| gads-conversions  | Conversion action inventory, primary-vs-secondary, attribution, value rules |
| gads-gtag         | Google tag / GA4 link / Floodlight / Enhanced Conversions check             |
| gads-keywords     | Keyword research and ideas via Keyword Plan service                         |
| gads-competitors  | Auction Insights, overlap rate, top-of-page rate                            |
| gads-placements   | Cross-network placement scan with safety classification and exclusion lists |
| gads-creation     | Campaign creation and edit wizard with explicit context gates               |

### Placement safety (Display + YouTube)

`gads-placements` enumerates placements with non-trivial spend or impressions,
then classifies each into safety buckets:

- `scam` — known scammy / clickbait domains, made-for-ads (MFA) sites
- `bot` — placements flagged for invalid traffic patterns
- `politics`, `religion`, `gambling`, `adult` — sensitive verticals
- `games` — game and game-discovery apps (mobile)

Classification uses a bundled rules file
(`scripts/placements_rules.json`) of domain patterns and app bundle
prefixes, plus optional heuristics on the placement URL. The agent then
proposes additions to a campaign-level exclusion list and, with user
approval, writes them via the `CustomerNegativeCriterion` and
`AdGroupCriterion` services.

The bundled rules are conservative and editable. The agent says exactly
what it intends to exclude before writing.

### Creation gates (`gads-creation`)

Before any campaign create call, the agent collects:

1. Business / vertical
2. Website URL (and reachability check)
3. Primary goal (sales, leads, traffic, awareness, app installs)
4. Whether GA4 / gtag is installed and firing (calls `gads-gtag`)
5. Whether conversion actions exist and are marked primary (calls
   `gads-conversions`)
6. Budget and bidding strategy
7. Targeted geos and languages

Missing any of these aborts with a remediation note. The final mutate is
shown as a JSON diff and gated on `y/N`.

## Skills layout

Top-level router skill: `gads`.

```
skills/
  gads/                 /gads ... router + reference docs
  gads-audit/           parallel audit (gates on auth + 24h session)
  gads-search/
  gads-pmax/
  gads-uac/
  gads-display/
  gads-shopping/
  gads-youtube/
  gads-conversions/
  gads-gtag/
  gads-keywords/
  gads-competitors/
  gads-placements/
  gads-creation/
```

## Scripts layout

```
scripts/
  gads_auth.py          gcloud ADC + dev token + 24h session
  gads_client.py        GoogleAdsClient wrapper, credentials resolution
  gads_query.py         GAQL helpers (date ranges, segments)
  gads_search.py
  gads_pmax.py
  gads_uac.py
  gads_display.py
  gads_shopping.py
  gads_youtube.py
  gads_conversions.py
  gads_gtag.py
  gads_keywords.py
  gads_competitors.py
  gads_placements.py
  placements_rules.json
  gads_creation.py
  gads_report.py
  gads_utils.py
  requirements.txt
```

## Reporting

Default audit output is markdown (no emoji), matching the
`google-analytics-agent` convention. Optional HTML / PDF via WeasyPrint.

## Style

- Commits: short imperative sentence, no Conventional Commits prefix, no
  `Co-Authored-By`, no AI footer. Sentence-case acceptable.
- Comments only where the *why* is non-obvious.
- README is factual, opentoonz-style: short sections, links out for
  details.
