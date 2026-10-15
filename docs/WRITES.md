# Bounded writes

Every write prints operation JSON, requires an explicit `y` at a `y/N` prompt,
and validates before application. Piped stdin and EOF cancel. The local
24-hour session gate still applies. YouTube uploads are the one step the API
cannot validate; see the upload section.

Since 2026-04-01 the API rejects campaign mutates in an account that has any
campaign without an EU political advertising declaration. Writers report this
as `eu_political_declaration_required`; declare every campaign, then retry.
[EU declaration](https://developers.google.com/google-ads/api/docs/api-policy/eu-par)

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

## PAUSED Demand Gen campaigns

`gads_creation.py --demand-gen-spec demand-gen.json` accepts exactly the
top-level fields in this example. Every key is required, including nullable
targets and optional asset lists. Extra or missing keys at any object level
fail before credentials are loaded.

```json
{
  "name": "Reviewed Demand Gen campaign",
  "budget_micros": 50000000,
  "budget_period": "DAILY",
  "start_date": null,
  "end_date": null,
  "bidding": "MAXIMIZE_CONVERSIONS",
  "target_cpa_micros": null,
  "target_roas": null,
  "geo_target_ids": ["2840"],
  "language_ids": ["1000"],
  "channel_controls": "ALL_CHANNELS",
  "asset_automation": {
    "GENERATE_DESIGN_VERSIONS_FOR_IMAGES": "OPTED_OUT",
    "GENERATE_VIDEOS_FROM_OTHER_ASSETS": "OPTED_OUT",
    "GENERATE_ANIMATED_IMAGES_FROM_OTHER_ASSETS": "OPTED_OUT"
  },
  "ad": {
    "type": "MULTI_ASSET",
    "final_url": "https://example.com/offer",
    "business_name": "Example",
    "headlines": ["Explore our collection"],
    "descriptions": ["Find your next favorite."],
    "marketing_images": ["customers/1234567890/assets/101"],
    "square_marketing_images": null,
    "logo_images": ["customers/1234567890/assets/102"]
  },
  "eu_political_advertising": false,
  "conversions_confirmed": true
}
```

Names must be non-empty strings without null, newline or carriage return
characters. `budget_micros` is a positive integer below 2**63 in account
currency micros. With `budget_period` `DAILY` it is the daily amount and both
dates are null. With `CAMPAIGN_TOTAL` it is the amount for the whole flight:
`start_date` and `end_date` are required `YYYY-MM-DD` dates (end not before
start), the budget uses `period` `CUSTOM_PERIOD` with `total_amount_micros`,
and the campaign gets `start_date_time` at 00:00:00 and `end_date_time` at
23:59:59 in the account time zone. Geo IDs are 1–100 numeric strings; language IDs are 0–50
numeric strings, with `[]` meaning all languages. Duplicate criterion IDs
are deduplicated. The political declaration must be an owner-supplied boolean;
`conversions_confirmed` must be explicitly `true`. Neither declaration is
inferred or proof of measurement, consent or eligibility.

| `bidding` | Campaign field | Required target |
| --- | --- | --- |
| `MAXIMIZE_CLICKS` | `target_spend` | Both null |
| `MAXIMIZE_CONVERSIONS` | `maximize_conversions` | Both null |
| `TARGET_CPA` | `maximize_conversions.target_cpa_micros` | Positive integer micros below 2**63; ROAS null |
| `TARGET_ROAS` | `maximize_conversion_value.target_roas` | Finite number greater than zero; CPA null |

`channel_controls` is either `"ALL_CHANNELS"` or exactly this boolean object,
with at least one flag true:

```json
{
  "youtube_in_stream": true,
  "youtube_in_feed": false,
  "youtube_shorts": false,
  "discover": true,
  "gmail": false,
  "display": false,
  "maps": false
}
```

The installed v25 `AdGroup.DemandGenAdGroupSettings.DemandGenChannelControls`
docstring marks `channel_config` output-only. The writer sets
`channel_strategy = ALL_CHANNELS` or `selected_channels`, passing every
selected-channel boolean explicitly. False proto3 booleans may be omitted
from the serialized preview.

`asset_automation` has exactly three keys for the selected `ad.type`, each
explicitly `OPTED_IN` or `OPTED_OUT`. `MULTI_ASSET` requires the three keys
shown above. `VIDEO_RESPONSIVE` requires `GENERATE_VERTICAL_YOUTUBE_VIDEOS`,
`GENERATE_SHORTER_YOUTUBE_VIDEOS` and `GENERATE_LANDING_PAGE_TEXT` instead.
The installed v25 `AssetAutomationTypeEnum.AssetAutomationType` docstrings
tie these sets to `DemandGenMultiAssetAd` and
`DemandGenVideoResponsiveAdInfo`, respectively. The ad is validated before
its automation keys. Only its three owner choices are written to
`ad_group_ad.ad_group_ad_asset_automation_settings`; none is a campaign
setting in this contract. Keys for the other ad type and additional keys
are rejected. `GENERATE_LANDING_PAGE_PREVIEW` is not included because its
enum docstring does not name Demand Gen. Server validation determines
eligibility.

The exact `MULTI_ASSET` ad keys are `type`, `final_url`, `business_name`,
`headlines`, `descriptions`, `marketing_images`, `square_marketing_images`,
`logo_images`. At least one of the two marketing-image lists must be
non-empty; the other can be null or empty. `logo_images`, `headlines` and
`descriptions` must be non-empty lists. Text is inline; asset lists contain
existing `customers/{customer_id}/assets/{numeric_id}` resources belonging
to the selected customer. `final_url` must be an absolute HTTP(S) URL.

For `VIDEO_RESPONSIVE`, use its three automation keys listed above and
replace the entire `ad` object with this exact key set:

```json
{
  "type": "VIDEO_RESPONSIVE",
  "final_url": "https://example.com/offer",
  "business_name": "Example",
  "headlines": ["Explore our collection"],
  "long_headlines": ["Find your next favorite in our collection"],
  "descriptions": ["Discover the collection today."],
  "videos": ["customers/1234567890/assets/103"],
  "logo_images": ["customers/1234567890/assets/102"]
}
```

All five lists in this video example must be non-empty. The v25
`DemandGenVideoResponsiveAdInfo.business_name` is an `AdTextAsset`, so the
inline string is wrapped as text; the multi-asset field is a plain string.
Other asset counts, text lengths, image dimensions and eligibility are left
to API validation. Optional descriptor fields such as portrait images,
companion banners and call-to-action assets are outside this bounded contract.

```sh
python scripts/gads_creation.py --customer 1234567890 --demand-gen-spec demand-gen.json --validate-only --json
python scripts/gads_creation.py --customer 1234567890 --demand-gen-spec demand-gen.json --apply --json
```

The request creates, in order, an unshared daily or campaign-total budget
(-1), a PAUSED `DEMAND_GEN` campaign (-2) without a channel subtype, an ENABLED ad group
(-3) without a type, ad-group location and language criteria, and one
ENABLED ad. Criteria and the ad omit `resource_name`; only the budget,
campaign and ad group need temporary names because later operations reference them.
`demand_gen_campaign_settings.upgraded_targeting` is explicitly true at
creation, enabling ad-group targeting. The paused campaign is the activation
gate. One atomic request uses `partial_failure=False` and `retry=None`;
apply validates the same request before sending it for application.

Product/carousel ads, asset uploads, audiences, lookalikes, activation and
edits after creation are unsupported. Neither mode bypasses interactive
review or the session gate; no mode flag returns `no_op`. The strict sources
are mutually exclusive, and `--context-file` remains non-executable.

A successful validation does not reserve names or guarantee a later apply
will succeed. A timeout during apply can leave an unknown outcome. There is
no idempotency key: inspect the account before retrying. Field and bidding
mappings were checked against installed v25 `Campaign`, `TargetSpend`,
`MaximizeConversions`, `MaximizeConversionValue`, `DemandGenMultiAssetAdInfo`
and `DemandGenVideoResponsiveAdInfo` docstrings. Tests use real v25 protobufs
with mocked services; no live account eligibility has been verified.

## PAUSED App campaigns and target edits

`gads_creation.py --app-spec app.json` accepts exactly these fields:

```json
{
  "name": "Reviewed App campaign",
  "sub_type": "APP_CAMPAIGN",
  "app_id": "com.example.app",
  "app_store": "GOOGLE_APP_STORE",
  "goal_type": "OPTIMIZE_INSTALLS_TARGET_INSTALL_COST",
  "target_cpa_micros": 2000000,
  "target_roas": null,
  "budget_micros": 50000000,
  "geo_target_ids": ["2840"],
  "language_ids": [],
  "selective_optimization_conversion_actions": [],
  "user_list": null,
  "ad": {
    "headlines": ["Try our app"],
    "descriptions": ["Discover what you can do today."],
    "images": ["customers/1234567890/assets/201"],
    "youtube_videos": null
  },
  "eu_political_advertising": false,
  "conversions_confirmed": true
}
```

All keys are required; omitted or additional fields fail before credentials
are loaded. The name, budget, customer, geo and language validation and
owner declarations follow the Demand Gen rules above. `app_id` is a
non-empty string. `sub_type` is `APP_CAMPAIGN` (installs) or
`APP_CAMPAIGN_FOR_ENGAGEMENT`; `app_store` is `GOOGLE_APP_STORE` or
`APPLE_APP_STORE`. The campaign channel is `MULTI_CHANNEL`. Pre-registration
campaigns are unsupported.

Engagement campaigns cannot use install goals or a target cost per install
(`OPTIMIZE_INSTALLS_*`, `OPTIMIZE_IN_APP_CONVERSIONS_TARGET_INSTALL_COST`), and
`user_list` is one
existing `customers/{customer_id}/userLists/{numeric_id}` resource in the same
customer. Google requires engagement ad groups to target an audience, so the
writer adds it as an ad-group `user_list` criterion; the Firebase all-users
list qualifies. The ad is an `AppEngagementAdInfo` with no deep link, so a
click opens the app's main screen. For `APP_CAMPAIGN`, `user_list` must be
null. [App ad groups](https://developers.google.com/google-ads/api/docs/app-campaigns/create-ad-group)

| `goal_type` | Strategy at creation | Target |
| --- | --- | --- |
| `OPTIMIZE_INSTALLS_TARGET_INSTALL_COST` | `target_cpa` | CPA required |
| `OPTIMIZE_INSTALLS_WITHOUT_TARGET_INSTALL_COST` | `maximize_conversions` | Both null |
| `OPTIMIZE_IN_APP_CONVERSIONS_TARGET_INSTALL_COST` | `target_cpa` | CPA required |
| `OPTIMIZE_IN_APP_CONVERSIONS_TARGET_CONVERSION_COST` | `target_cpa` | CPA required |
| `OPTIMIZE_IN_APP_CONVERSIONS_WITHOUT_TARGET_CPA` | `maximize_conversions` | Both null |
| `OPTIMIZE_RETURN_ON_ADVERTISING_SPEND` | `target_roas` | ROAS required |
| `OPTIMIZE_TOTAL_VALUE_WITHOUT_TARGET_ROAS` | `maximize_conversion_value` | Both null |

CPA is positive integer micros below 2**63; ROAS is a finite number greater
than zero. The unrelated target must be null. Other goals and portfolio
strategies are unsupported. `selective_optimization_conversion_actions`
is a list of existing `customers/{customer_id}/conversionActions/{numeric_id}`
resources in the same customer. It must be non-empty for engagement, all
`OPTIMIZE_IN_APP_*` goals, ROAS and total-value goals; otherwise it may be
empty. It is written to `campaign.selective_optimization.conversion_actions`.

The ad uses exactly `headlines`, `descriptions`, `images` and
`youtube_videos`, written to `AppAdInfo` for installs and to
`AppEngagementAdInfo` for engagement, whose v25 video field is `videos`.
Headlines and descriptions are
non-empty lists of inline text. Images and videos are existing asset resources
in the same customer; unused lists are present as null (empty lists are also
accepted). Other asset counts and eligibility are left to API validation.
Media bundles, mandatory ad text and deep-link fields are outside this
contract. Server validation can still reject an ineligible account or campaign.

```sh
python scripts/gads_creation.py --customer 1234567890 --app-spec app.json --validate-only --json
python scripts/gads_creation.py --customer 1234567890 --app-spec app.json --apply --json
```

Creation sends one atomic request, ordered as an unshared daily budget (-1),
a PAUSED campaign (-2) with its strategy set, an ENABLED ad group (-3)
without a type, campaign location and language criteria, the engagement
user-list criterion when present, and an ENABLED ad.
Criteria and the ad omit `resource_name`; only the budget, campaign and
ad group need temporary names because later operations reference them.
The campaign is the activation gate. Partial failure and automatic retries are disabled;
application validates the same request first. Asset uploads, audience
creation, lookalikes, pre-registration campaigns, deep links, activation,
product/carousel ads and edits after creation are unsupported, except the
separate App target path below.

`--app-target target.json` accepts exactly `campaign_id`, `target_cpa_micros`
and `target_roas`. The campaign ID is a numeric string and exactly one
target is non-null, with the same positive target validation as creation:

```json
{
  "campaign_id": "456",
  "target_cpa_micros": 2500000,
  "target_roas": null
}
```

```sh
python scripts/gads_creation.py --customer 1234567890 --app-target target.json --validate-only --json
python scripts/gads_creation.py --customer 1234567890 --app-target target.json --apply --json
```

After input validation and client construction, the writer reads the campaign
by ID. It must be non-REMOVED and `MULTI_CHANNEL`; its existing App goal must
map to `target_cpa` for a CPA change or `target_roas` for a ROAS change in the
table above, and its current `bidding_strategy_type` must already be that
strategy with no portfolio strategy attached, so the edit cannot switch the
bidding scheme. Targetless goals cannot be edited here. One reviewed
`CampaignOperation` changes only `target_cpa.target_cpa_micros` or
`target_roas.target_roas` with that exact field mask. Output includes
`previous_value`, `new_value`, `field`, status, response and limitations.
The read and update are not locked against concurrent operators.

Both sources require interactive review and respect the session gate. With
neither mode flag they return `no_op`. A successful validation does not
reserve names or guarantee a later apply will succeed. A timeout during
apply can leave an unknown outcome. There is no idempotency key: inspect
the account before retrying. The legacy planning source stays non-executable.
Mappings were checked against installed v25 `Campaign.AppCampaignSetting`,
`AppCampaignBiddingStrategyGoalTypeEnum`, `AppAdInfo` and `AppEngagementAdInfo`
docstrings and the [App campaign guide](https://developers.google.com/google-ads/api/docs/app-campaigns/create-campaign).
Real protobuf tests use mocked services. The App target read was run read-only
against a live account (see REPORTING.md); no live writes or `validate_only`
calls were made.

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

## YouTube uploads and video assets

```sh
python scripts/gads_creative.py upload-video --customer 1234567890 --file video.mp4 --title "Video title" --description "Optional description" --asset-name "Video asset" --apply --json
python scripts/gads_creative.py create-video-asset --customer 1234567890 --video-id Abc_def-123 --name "Video asset" --validate-only --json
```

`upload-video` uploads binary video through `YouTubeVideoUploadService`, then
creates an Asset with `youtube_video_asset.youtube_video_id`. It accepts only
`--apply`; there is no upload `--validate-only` and no API validation for the
upload. Without `--apply`, local file, title and privacy checks run and return
`no_op`. The first review shows customer, file path, size, title, description,
channel and privacy, never file bytes. Uploads do not retry automatically.

Privacy defaults to `UNLISTED`. Unlisted videos are viewable by anyone with the
link. Without `--channel-id`, the destination is a Google-managed channel and
only `UNLISTED` is supported. Advertiser-owned brand channels require
`--channel-id` and user OAuth; service accounts are not supported. Brand channels
accept `--privacy PUBLIC` or `--privacy UNLISTED`.

Processing is asynchronous. The adapter polls `you_tube_video_upload` every
10 seconds for up to 10 minutes. `FAILED`, `REJECTED` and `UNAVAILABLE` stop
polling; failures and timeout retain the upload resource name in output.
Only `PROCESSED` yields the video ID for the asset step. A second interactive
review validates and then creates the asset through AssetService.

If that second review is cancelled or asset creation fails, the result is
`uploaded_without_asset`, including the upload resource and video ID. The
upload is left behind. Use `create-video-asset` to finish, or the API's
`RemoveYouTubeVideoUpload` to remove the upload; removal is not implemented by
this CLI. Inspect account state before retrying an uncertain asset write.
Neither command attaches the video asset to an ad or campaign.

`create-video-asset` accepts existing 11-character YouTube IDs (letters, digits,
underscore and hyphen), a required `--name`, and mutually exclusive
`--validate-only` / `--apply`. Neither mode flag returns `no_op`. Both active
modes require review, and apply validates first. This asset-only command does
not upload a video or change its privacy. Create operations have no field mask.

## Video responsive and responsive Display ad edits

```sh
python scripts/gads_creative.py edit-ad --customer 1234567890 --ad-id 123 --input ad-edit.json --validate-only --json
```

`edit-ad` reads the ad type, ad group, campaign channel and statuses first.
Only `VIDEO_RESPONSIVE_AD` in `VIDEO` and `RESPONSIVE_DISPLAY_AD` in `DISPLAY`
are accepted. Missing ads return `not_found`. Video campaigns cannot be created
or mutated through the API; editing `VideoResponsiveAdInfo` through AdService
is the supported exception. This command does not change campaign settings,
ad status, URLs, ad groups or targeting. It uses one AdService update, reviewed
and validated before application. Choose `--validate-only` or `--apply`; neither
flag returns `no_op`.

The JSON object contains only the fields to edit. Text asset fields accept
inline strings, or arrays of strings for repeated fields. Image and video
fields accept arrays of `customers/{customer_id}/assets/{asset_id}` names;
cross-customer names and malformed inputs are rejected before credentials load.
The server validates creative lengths, dimensions, eligibility and limits.

Video editable keys are `headlines`, `long_headlines`, `descriptions`,
`call_to_actions` (string arrays), `videos`, `logo_images`, `companion_banners`
(asset arrays), and `business_name`, `breadcrumb1`, `breadcrumb2` (strings).
Every Video edit must supply non-empty `videos`, `business_name`, `logo_images`.
For example:

```json
{
  "videos": ["customers/1234567890/assets/7"],
  "business_name": "Brand",
  "logo_images": ["customers/1234567890/assets/8"],
  "headlines": ["Updated headline"]
}
```

Display editable keys are `marketing_images`, `square_marketing_images`,
`logo_images`, `square_logo_images`, `youtube_videos` (asset arrays),
`headlines`, `descriptions` (string arrays), `long_headline`, `business_name`,
`main_color`, `accent_color`, `call_to_action_text`, `price_prefix`, `promo_text`
(strings), `allow_flexible_color` (boolean), `format_setting` (`ALL_FORMATS`,
`NON_NATIVE`, `NATIVE`), and `control_spec` (an object containing either or both
`enable_asset_enhancements` and `enable_autogen_video`, both booleans).
Empty optional asset arrays clear those fields, subject to API validation.

Field masks contain only supplied fields, prefixed by `video_responsive_ad.`
or `responsive_display_ad.`. Repeated fields are masked by name and replaced
whole. Singular message fields are masked at their leaves, because the API
rejects a mask on a field that has subfields: Video `business_name` and
Display `long_headline` use `.text`, and `control_spec` masks only the
supplied boolean leaves, preserving the other control. The installed v25 descriptors
define Video `business_name` as `AdTextAsset`, Display `business_name` as a
string, and Display `long_headline` as singular. The adapter converts inline
text accordingly; it does not accept asset resource names for text fields.

## Display optimized targeting and campaign exclusions

```sh
python scripts/gads_apply.py --customer 1234567890 optimized-targeting --input targeting.json --validate-only --json
python scripts/gads_apply.py --customer 1234567890 placements --campaign-id 123 --input exclusions.json --apply --json
```

`optimized-targeting` accepts exactly
`{"ad_group_id": "123", "enabled": false}` (or `true`). It reads the ad group
and requires a `DISPLAY` campaign. The review shows the previous and new value.
One AdGroup update sets `optimized_targeting_enabled`, with that exact field
mask. It changes only that setting; it does not edit targeting criteria.

`placements --campaign-id` reads the campaign and requires `DISPLAY`, then
creates negative CampaignCriterion rows. The existing category-to-array input
is unchanged. Each entry uses `target_url`, falling back to `placement`:
`mobileapp://` routes to `mobile_application.app_id`, YouTube channel URLs or
`UC` prefixes route to `youtube_channel.channel_id`, and other strings route
to `placement.url`. This is best-effort routing; API validation decides whether
the placement is supported. No update field masks are used for these creates.

Without `--campaign-id`, `placements` retains account-level
CustomerNegativeCriterion behavior and applies across the account. Neither
path removes exclusions or deduplicates existing criteria. These commands
require `--validate-only` or `--apply`, with review and validation before apply;
neither flag returns `no_op`. Missing campaigns or ad groups return `not_found`
without mutation.

## Guards on existing creative and keyword writers

`gads_creative.py attach --campaign-id ... --field-type AD_IMAGE` reads the
campaign and accepts only `SEARCH`. It still creates a CampaignAsset link,
without an update field mask. The asset-group attachment path is unchanged.

`gads_apply.py negatives` reads the target campaign and rejects `VIDEO` because
the API does not support Video campaign mutations. Other channels retain the
existing reviewed CampaignCriterion negative-keyword creates, without update
field masks. Missing campaigns return `not_found`; guards never send a mutate.
