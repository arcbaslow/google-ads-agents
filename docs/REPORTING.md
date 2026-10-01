# Reporting surfaces

## Performance Max

`python scripts/gads_pmax.py --customer <id> --report channels --days 28 --json`
returns channel segments. Other report choices are `placements`, `assets`,
`branding`, and the existing default `groups`. Reports keep raw API rows.
Placement impressions do not establish placement spend or conversions.
Asset metrics overlap because assets can serve together. Branding is current
campaign-level link inventory, not historical metrics or proof of serving.

Sources: [campaign reporting](https://developers.google.com/google-ads/api/performance-max/campaign-reporting),
[asset-group asset fields](https://developers.google.com/google-ads/api/fields/v25/asset_group_asset),
[campaign assets](https://developers.google.com/google-ads/api/fields/v25/campaign_asset).

## Demand Gen and AI Max settings

Demand Gen `--channel-controls` reads current ad-group channel controls;
Search `--ai-max-settings` reads current enablement and bundling requirements.
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
