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
