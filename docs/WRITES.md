# Bounded writes

Every write prints operation JSON, requires an explicit `y` at a `y/N` prompt,
and validates before application. EOF cancels. The local 24-hour session gate
still applies. Never pipe approval into a writer.

## Search campaign shells

`gads_creation.py --search-spec search-spec.json` accepts exactly these fields:

```json
{
  "name": "Reviewed Search campaign",
  "budget_micros": 50000000,
  "bidding": "MAXIMIZE_CONVERSIONS",
  "geo_target_ids": ["2840"],
  "language_mode": "AUTOMATIC",
  "eu_political_advertising": false,
  "analytics_confirmed": true,
  "conversions_confirmed": true
}
```

The budget is daily micros in the account currency. Supply verified geo target
IDs, not country abbreviations. Measurement flags are owner assertions, not
proof of delivery or consent. The political declaration must come from the
owner. Unsupported or extra fields fail before credentials are loaded.

```sh
python scripts/gads_creation.py --customer 1234567890 --search-spec search-spec.json --validate-only --json
python scripts/gads_creation.py --customer 1234567890 --search-spec search-spec.json --apply --json
```

The request creates a dedicated, unshared budget, a PAUSED Search campaign
using Maximize Conversions on Google Search, and location criteria with
presence targeting. It uses temporary resource names in one atomic request,
with partial failure and automatic retries disabled. No ads, keywords,
activation, CPA target, other campaign channels or manual language criteria
are supported. Inspect the operation preview before approving.

A successful validation does not reserve names or guarantee a later apply
will succeed. A timeout during apply can leave an unknown outcome. There is
no idempotency key: inspect the account before retrying. The original
`--context-file` planning contract remains non-executable.

Request fields were checked against the official [Campaign reference](https://developers.google.com/google-ads/api/reference/rpc/v25/Campaign),
[atomic mutation guide](https://developers.google.com/google-ads/api/docs/mutating/overview),
[location targeting guide](https://developers.google.com/google-ads/api/docs/targeting/location-targeting),
[political declaration guide](https://developers.google.com/google-ads/api/docs/api-policy/eu-par)
and [Search language deprecation](https://developers.google.com/google-ads/api/docs/deprecations).
Tests use actual v25 protobufs and mocked services. Server validation and
account eligibility have not been exercised against live accounts.
