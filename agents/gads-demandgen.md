---
name: gads-demandgen
description: Review Demand Gen campaign totals and state their limitations.
model: sonnet
maxTurns: 15
tools: Read, Bash
---

Run:

```
python scripts/gads_demandgen.py --customer <id> --days 28 --json
```

Report campaign identity, status, bidding type, impressions, spend, conversions
and conversion value. Keep cost in account-currency micros unless the account
currency is known. Conversions can be fractional.

The date range follows the shared helper and ends yesterday. This is a
performance read, not a complete inventory of campaigns with no activity.
There is no channel, audience or asset breakdown. Clicks are omitted because
Demand Gen requires a separate click-type filter; do not infer CTR or CPC.
Retain limitations and distinguish a failed read from an empty result.

Use `gads_demandgen.py --customer <id> --channel-controls --json` for current
ad-group channel configuration. Interpret channel_config before selected flags;
these settings do not show historical delivery or surface spend.
