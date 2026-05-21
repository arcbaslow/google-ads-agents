---
name: gads
description: "Google Ads multi-agent toolkit. Audits, campaign-type analysis (Search, Performance Max, App, Display, Shopping, YouTube), conversion + Google tag health, keyword research, auction insights, placement safety with built-in scam/bot/politics/religion/games/adult exclusions, and gated campaign creation. End-user Google SSO via gcloud, 24h session cap. Triggers on: google ads, adwords, search campaign, performance max, pmax, uac, app campaign, display campaign, shopping campaign, youtube ads, video campaign, auction insights, keyword research, conversion tracking, gtag, ga4 link."
user-invokable: true
argument-hint: "[command] [customer-id] [options]"
license: MIT
metadata:
  version: "0.1.0"
  category: google-ads
---

# Google Ads router skill

Top-level entry point. `/gads <command> <args>`.

## Commands

| Command | What it does |
|---------|-------------|
| `/gads auth` | Print the `gcloud auth application-default login` command, set developer token / login-customer-id |
| `/gads customers` | List accessible Google Ads customers |
| `/gads audit <customer-id>` | Full audit, all agents in parallel |
| `/gads search <customer-id>` | Search campaigns |
| `/gads pmax <customer-id>` | Performance Max |
| `/gads uac <customer-id>` | App campaigns |
| `/gads display <customer-id>` | Display |
| `/gads shopping <customer-id>` | Shopping |
| `/gads youtube <customer-id>` | YouTube / Video |
| `/gads conversions <customer-id>` | Conversion tracking |
| `/gads gtag <customer-id> --site <url>` | Google tag / GA4 link / Enhanced Conversions |
| `/gads keywords <customer-id> --seeds w1 w2` | Keyword ideas |
| `/gads competitors <customer-id>` | Auction Insights |
| `/gads placements <customer-id>` | Display + YouTube placement audit with safety exclusions |
| `/gads recommendations <customer-id>` | Google's account recommendations, triaged |
| `/gads anomalies <customer-id>` | Day-level metric anomaly detector |
| `/gads history <customer-id>` | Change-event log; list and diff saved audits |
| `/gads apply <customer-id>` | Write paths: negative keywords and placement exclusions |
| `/gads create <customer-id>` | Campaign creation wizard, with gates |

## Routing

| Input | Route to |
|-------|----------|
| `audit <id>` | gads-audit |
| `search <id>` | gads-search |
| `pmax <id>` | gads-pmax |
| `uac <id>` or `app <id>` | gads-uac |
| `display <id>` | gads-display |
| `shopping <id>` | gads-shopping |
| `youtube <id>` or `video <id>` | gads-youtube |
| `conversions <id>` | gads-conversions |
| `gtag <id>` | gads-gtag |
| `keywords <id>` | gads-keywords |
| `competitors <id>` | gads-competitors |
| `placements <id>` | gads-placements |
| `recommendations <id>` | gads-recommendations |
| `anomalies <id>` | gads-anomalies |
| `history <id>` | scripts/gads_history.py |
| `apply <id>` | scripts/gads_apply.py |
| `create <id>` | gads-creation |
| `auth` | Run `python scripts/gads_auth.py --adc` and friends |
| `customers` | Run `python scripts/gads_auth.py --customers` |

## Auth gate

Before any read/write, verify the session:

```
python scripts/gads_auth.py --check
```

If the session is older than 24h or the developer token is missing,
guide the user through:

1. `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/adwords,https://www.googleapis.com/auth/cloud-platform,openid,email`
2. `python scripts/gads_auth.py --set-developer-token <TOKEN>`
3. Optionally `--set-login-customer-id <MCC>` for manager-account flows.

## Natural-language routing

- "How are my search campaigns doing?" → gads-search
- "Audit my Google Ads account" → gads-audit
- "Find scam placements" → gads-placements
- "I want to launch a new campaign" → gads-creation (it will collect
  context before proposing anything)
- "Why am I losing impression share?" → gads-search and gads-competitors
- "Is my conversion tracking right?" → gads-conversions + gads-gtag

## Defaults

- Lookback: 28 days
- Output: markdown (no emoji)
- Mutate: always `PAUSED` first, never auto-unpause
