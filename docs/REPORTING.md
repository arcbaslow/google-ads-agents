# Reporting surfaces

## Performance Max

`python scripts/gads_pmax.py --customer <id> --report channels --days 28 --json`
returns channel segments. Other report choices are `placements`, `assets`,
`branding`, `tracking`, and the existing default `groups`. Reports keep raw API rows.
Placement impressions do not establish placement spend or conversions.
Asset metrics overlap because assets can serve together. Branding is current
campaign-level link inventory, not historical metrics or proof of serving.

Sources: [campaign reporting](https://developers.google.com/google-ads/api/performance-max/campaign-reporting),
[asset-group asset fields](https://developers.google.com/google-ads/api/fields/v25/asset_group_asset),
[campaign assets](https://developers.google.com/google-ads/api/fields/v25/campaign_asset).

## Demand Gen and AI Max settings

Demand Gen `--channel-controls` reads current ad-group channel controls;
Search `--ai-max-settings` reads current enablement, bundling requirements and
API-reported ACA/broad-match migration dates. Absent dates remain unknown.
Missing optional fields remain absent. Neither command changes settings.
These are configuration reads, not historical delivery or migration forecasts.

Sources: [channel controls](https://developers.google.com/google-ads/api/docs/demand-gen/channel-controls),
[AI Max settings](https://developers.google.com/google-ads/api/reference/rpc/v25/Campaign.AiMaxSetting).

## Conversion and consent evidence

`gads_conversions.py --customer <id> --diagnostics --json` reads recent offline
import diagnostics by client. Empty results do not establish health. For
enhanced conversions for leads, use the appropriate diagnostics in the Ads UI.
The tag scanner lists mentions of consent signal names in HTML; it never
executes scripts or verifies runtime consent, event delivery or compliance.

Sources: [upload summaries](https://developers.google.com/google-ads/api/docs/conversions/upload-summaries),
[consent concepts](https://developers.google.com/tag-platform/security/concepts/consent-mode).

Use `gads_audit.py --all-customers --include-managed` to explicitly traverse
manager trees and audit enabled client accounts once. Direct-access behavior
remains the default. Discovery carries a root login ID into each audit and
reports inaccessible branches as partial. Traversal is capped at 1000 manager
visits. This is a CLI feature; the hosted service still exposes no audit endpoint.

Reference: [account hierarchy](https://developers.google.com/google-ads/api/docs/account-management/get-account-hierarchy).

## Read failures

Read CLI commands return exit code 3 and a JSON object with `status: failed`,
`error_code`, a fixed message and `retryable`. Provider exception text and
tracebacks are omitted. Permission failure, removed resources and unavailable
services are distinct from a successful empty report. Python adapter functions
still raise; the audit driver records a failed block per adapter. No automatic
retry is added. Site-scan and notification errors use the same redacted form.

`test_gads_read_boundaries.py` covers the previously untested thin channel
wrappers and geo suggestions using real v25 messages with mocked services,
including empty rows, permissions, missing resources and malformed transport.
Other adapter tests cover transformations and write boundaries; this is not a
claim of complete branch coverage or server-side field compatibility.

## Local exports

Export a saved single-account or multi-account audit without API access:

```sh
python scripts/gads_export.py --audit-file audit.json --format csv --output findings.csv
python scripts/gads_export.py --audit-file audit.json --format json --output findings.json
python scripts/gads_export.py --audit-file audit.json --format prometheus --output findings.prom
```

Rows distinguish account, adapter status, finding and incomplete discovery.
Nested finding paths and entity IDs survive export; raw legacy exception
messages are excluded. JSON preserves nested values. CSV flattens object keys,
encodes arrays as JSON, keeps numeric types and prefixes formula-like strings
with an apostrophe for spreadsheet safety. Empty query CSV has no header.

Prometheus text includes finding counts by account/severity, failed-adapter
counts and a discovery-incomplete gauge. It represents the saved snapshot,
not a live account. Check the audit date range and file age separately in your
monitoring system; zero findings is not evidence that every check ran or that
tracking works. No credentials, scheduler, HTTP server, push gateway or
notification delivery are involved. Publish the file to an existing collector
only through your own approved process. This covers the local integration
portion of the [Ads Monitor comparison](https://github.com/google-marketing-solutions/ads-monitor)
without installing its infrastructure.

## Bounded GAQL export

Save a reviewed query, for example:

```sql
SELECT campaign.id, campaign.name, metrics.cost_micros
FROM campaign
WHERE segments.date DURING LAST_30_DAYS
ORDER BY campaign.id
```

```sh
python scripts/gads_export.py --customer 1234567890 --query-file report.gaql --limit 1000 --format json --output report.json
```

JSON and CSV are supported. A numeric customer is required and only the
SearchStream read service is called, through the normal provider/session gate.
The command accepts one SELECT/FROM query with optional WHERE and ORDER BY,
rejects comments, multiple statements, LIMIT and PARAMETERS, and appends its
own limit. `--limit` accepts 1–10000 rows. One extra row detects truncation;
JSON records `truncated` and CSV emits a warning on stderr. No automatic
pagination beyond that limit or multi-account query fan-out is provided.

The syntax check is conservative; Google validates actual field compatibility
and account permission. A failed request returns exit code 3 without replacing
an existing `--output` file. Always check exit status before consuming stdout
as CSV, since failure output is JSON.

See the [official GAQL structure](https://developers.google.com/google-ads/api/docs/query/structure).
The export scope addresses the local reporting gap compared with
[Ads API Report Fetcher](https://github.com/google/ads-api-report-fetcher);
warehouse connectors and hosted reporting remain outside this toolkit.

PMax `--report tracking` reads asset-group tracking templates, custom parameters
and final URL suffixes. These are current settings, not resolved click URLs or
proof that tags fire. Field references: [AssetGroup](https://developers.google.com/google-ads/api/reference/rpc/v25/AssetGroup)
and [Campaign migration dates](https://developers.google.com/google-ads/api/reference/rpc/v25/Campaign).
These additions cover the v25.1/v25.2 configuration gaps listed in the roadmap.
