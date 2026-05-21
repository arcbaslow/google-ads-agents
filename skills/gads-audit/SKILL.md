---
name: gads-audit
description: Full Google Ads account audit. Fans out to every analysis agent in parallel, gates on auth and 24h session, then renders a markdown report.
user-invokable: true
argument-hint: "<customer-id> [--days N]"
license: MIT
metadata:
  version: "0.1.0"
---

# Audit orchestrator

`/gads audit <customer-id> [--days N]`

## Sequence

1. **Auth + session gate.** Run `python scripts/gads_auth.py --check`.
   If the session is expired or the developer token is missing, stop
   and instruct the user to re-authenticate. Do not proceed.

2. **Pre-flight gates, in series.** These determine whether the rest
   of the audit can be trusted:
   - `gads-conversions` — if there are no primary conversion actions,
     the rest of the audit's bid-strategy critique is meaningless.
     Note that in the report and continue with reduced confidence.
   - `gads-gtag` — if gtag/GA4 isn't installed, conversion data is
     unreliable. Note and continue.

3. **Fan out in parallel** (one subagent per domain):
   - gads-search
   - gads-pmax
   - gads-uac
   - gads-display
   - gads-shopping
   - gads-youtube
   - gads-keywords (skip unless `--seeds` provided)
   - gads-competitors
   - gads-placements

4. **Merge results.** Each agent returns JSON with `summary`, `findings`,
   and `metrics`. Concatenate findings, group by severity, build the
   action plan.

5. **Render** via `python scripts/gads_report.py --input <merged.json>`
   to markdown by default. HTML and PDF via `--format html|pdf`.

## Output

A single markdown file under `~/.claude/gads-audit-<customer>-<date>.md`
plus the `~/.claude/gads-audit-<customer>-<date>.json` raw merge for
reference.
