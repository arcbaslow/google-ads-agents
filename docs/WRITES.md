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

## PMax brand exclusions

Use `gads_brands.py suggest` to obtain catalogue IDs, then have the owner select
the intended brands and campaigns. `exclude` takes `--campaign-ids` and
`--brand-ids`, or `--input` containing exactly those two JSON arrays. Each
array accepts 1–100 strings. An explicit `--validate-only` or `--apply` is
required; both modes still require the interactive review.

The adapter reads campaign eligibility, existing BRANDS lists, list contents
and campaign links in the selected account. A deterministic name derived from
the sorted brand IDs identifies a managed list. It reuses that list only when
its current contents match exactly; duplicate names, foreign resource names
and changed contents fail closed. New list, members and negative campaign
brand-list criteria use one atomic request. Existing lists are never edited.
Already attached campaigns need no operation.

Only active or paused PMax campaigns are supported. No Search restrictions,
cross-account list sharing, list edits, removal or deletion are included.
Names identify managed content, not ownership permissions. Concurrent operators
are not locked: sequential repeat requests avoid duplicates, but an uncertain
apply must be investigated in the account before retrying.

Request fields follow [shared sets](https://developers.google.com/google-ads/api/docs/targeting/shared-sets),
[BrandInfo.entity_id](https://developers.google.com/google-ads/api/reference/rpc/v25/BrandInfo)
and [CampaignCriterion.brand_list](https://developers.google.com/google-ads/api/reference/rpc/v25/CampaignCriterion).
Server validation decides catalogue eligibility and account limits. Mocked
checks do not establish that a particular brand can be excluded in a real account.
