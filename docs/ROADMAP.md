# Roadmap

Reviewed on 2026-09-30 against v0.6.1, baseline commit `1aa6db6`.
The owner explicitly authorised this maintenance and feature pass. The session
cap, session hook and requirement to review every write remain in force.
Effort estimates are engineering days, including mocked tests and documentation.
Code references below describe the baseline unless stated otherwise.

## Baseline and evidence limits

- Ruff: `ruff check scripts/ hooks/ webapp/` passed.
- Adapters: `pytest scripts/ -q` passed, 174 tests.
- Hosted service: `pytest webapp/tests/ -q` passed, 55 tests, with a Starlette
  warning about its deprecated httpx integration.
- Tests ran in a Python 3.12 virtual environment installed according to
  CONTRIBUTING.md. A test-only wrapper disabled dotenv loading, redirected
  temporary credential/session fixture paths to neutral filenames and blocked
  external socket connections. Windows loopback connections remained available
  for the ASGI test runner. No live Google Ads requests were made.
- A coverage run found no executed production lines in `gads_apply`, `gads_audit`,
  `gads_brands`, `gads_competitors`, `gads_conversions`, `gads_display`, `gads_geos`,
  `gads_gtag`, `gads_keywords`, `gads_pmax`, `gads_shopping`, `gads_uac` or
  `gads_youtube`. Passing the existing tests did not establish these adapters work.
- Queries were inspected against official v25 references and installed client
  protobuf descriptors. This verifies field names, not server-side GAQL field
  combinations, account eligibility, permissions or actual responses.

## API and product review

The latest published API release is v25.2 (2026-09-23), using the v25 service
namespace. v26 is scheduled for October, not yet published. v22 is scheduled to
sunset in October 2026; v23 in February 2027; v24/v24.1 in May 2027; v24.2 in
June 2027; and v25/v25.1/v25.2 in August 2027. Future dates are tentative.
Sources: [release notes](https://developers.google.com/google-ads/api/docs/release-notes)
and [sunset schedule](https://developers.google.com/google-ads/api/docs/sunset-dates).

The repository did not pin a client or API version: `pyproject.toml:27` and
`scripts/requirements.txt:1` allowed `google-ads>=25.0.0`, and
`scripts/gads_client.py:27` used the library default. Client 25.0.0 added API
v17.1; current client 33.0.0 includes v25.2 and removes v21/v22. Fresh and older
installations could therefore use different schemas. The reviewed environment
resolved client 33.0.0.
Source: [Python client changelog](https://raw.githubusercontent.com/googleads/google-ads-python/main/ChangeLog).

The reference review covered these adapter families. Local schema tests now
check resources and selected field paths in all static query strings. No claim
of complete server-side GAQL compatibility is made.

| Adapter family | Current reference and finding |
| --- | --- |
| Campaign reads, pacing, bidding and anomalies | [Campaign](https://developers.google.com/google-ads/api/fields/v25/campaign): existing channel filters and performance fields; TrueView and feed-label repairs in N6. |
| PMax groups and creative inventory | [AssetGroup](https://developers.google.com/google-ads/api/fields/v25/asset_group) and [AssetGroupAsset](https://developers.google.com/google-ads/api/fields/v25/asset_group_asset): inventory fields exist; no asset-group performance_label. |
| RSA and keyword quality | [AdGroupAd](https://developers.google.com/google-ads/api/fields/v25/ad_group_ad?authuser=19) and [KeywordView](https://developers.google.com/google-ads/api/fields/v25/keyword_view?authuser=19): ad_strength, RSA text assets and quality-score fields are present. |
| Placements | [DetailPlacementView](https://developers.google.com/google-ads/api/fields/v25/detail_placement_view): placement URLs and type enums are present; this is not exhaustive cross-network visibility. |
| Conversion actions and tracking IDs | [ConversionAction](https://developers.google.com/google-ads/api/fields/v25/conversion_action?authuser=0) and [Customer](https://developers.google.com/google-ads/api/fields/v25/customer): these reads do not establish consent or conversion delivery. |
| Demographics | [AgeRangeView](https://developers.google.com/google-ads/api/fields/v25/age_range_view?authuser=19) and [UserLocationView](https://developers.google.com/google-ads/api/fields/v25/user_location_view): wrong age resource fixed in N9; enum serialization fixed in N10. |
| Recommendations and history | [Recommendation](https://developers.google.com/google-ads/api/fields/v25/recommendation) and [ChangeEvent](https://developers.google.com/google-ads/api/fields/v25/change_event): field names checked; recommendation classification fixed in N10. |
| Brand and image writes | BrandSuggestion, CampaignCriterion and CampaignAsset references in N3/N6 distinguish catalogue response types, brand-list criteria and AD_IMAGE. |

Relevant changes in the past year:

- Video reporting renamed views and view rate to TrueView metrics in v22. The
  YouTube adapter still requested the old fields.
  [v22 release notes](https://developers.google.com/google-ads/api/docs/release-notes#v22)
- PMax channel reporting became available in v23. Existing `gads_pmax.py`
  reports asset-group totals only; it cannot explain a shift between channels.
  [Google announcement](https://ads-developers.googleblog.com/2026/01/introducing-channel-level-reporting-for.html)
- v25.1 added AI Max migration dates; v25.2 added asset-group URL tracking
  settings. Neither has a read surface here.
  [release notes](https://developers.google.com/google-ads/api/docs/release-notes)
- Demand Gen has its own campaign reporting and channel controls. The existing
  Display and YouTube filters do not cover Demand Gen. Click reporting has a
  `CROSS_NETWORK` caveat that a new adapter must respect.
  [reporting](https://developers.google.com/google-ads/api/docs/demand-gen/reporting),
  [channel controls](https://developers.google.com/google-ads/api/docs/demand-gen/channel-controls)
- Customer Match and offline conversion uploads acquired historical-usage
  restrictions in April and June 2026; newer integrations should evaluate Data
  Manager. This repository reads conversion actions and does not upload events.
  New Smart campaign creation ended in September; manual Search language
  targeting is also being retired. These changes matter to any future writer.
  [deprecations](https://developers.google.com/google-ads/api/docs/deprecations)
- Developer tokens were retired in favour of Cloud project access on September
  9. Existing approved projects and requests carrying tokens can continue, but
  a new project's access cannot be obtained by borrowing an old token. Current
  setup still requires a token; it needs an access-model review.
  [access migration](https://developers.google.com/google-ads/api/docs/api-policy/developer-token)
- Consent checks must distinguish `ad_user_data` and `ad_personalization` from
  basic tag presence. Static HTML detection in `gads_gtag.py` cannot establish
  runtime consent or conversion delivery. This is a current limitation, not a
  claim that consent mode itself was introduced this year.
  [consent concepts](https://developers.google.com/tag-platform/security/concepts/consent-mode)

## Now

All Now items below are implemented on `roadmap-work`. The descriptions explain
the baseline problem and the chosen repair. Initial bugs and API compatibility
were committed before Demand Gen; N9 and N10 were discovered in final review
and fixed afterward. Estimates are rough planning effort, not elapsed time.
See VERIFICATION.md for checks and commit records.

### N1. Enforce write review in the Python boundary

- What: centralise operation JSON preview, explicit `y/N`, API validation and
  then application for negative keywords, placements and creative writes. Reject
  conflicting CLI mode flags. EOF or unavailable input cancels.
- Why: a command flag sufficed at baseline to change a spending account; relying
  on an agent's prose is not a safety boundary.
- Evidence: `scripts/gads_apply.py:62`, `scripts/gads_creative.py:197` and the
  other creative attachment functions call mutation services directly.
- Effort: 1–2 days. Risk: medium; scripted writes now require interactive input.
  Preview and prompt use stderr so stdout remains machine-readable JSON.

### N2. Block incomplete campaign creation

- What: keep campaign context planning, but reject both API validation and
  application before constructing a client. Mark the result as a planning
  draft, not executable operation JSON.
- Why: the writer ignores the proposed bidding strategy, geos and languages;
  it creates a budget separately and can leave it behind on campaign failure.
  Its dry run cannot obtain the budget resource needed by the campaign.
- Evidence: `scripts/gads_creation.py:78` through `send_mutate`; the proposed
  fields in `propose_mutate` never reach the campaign operation. The political
  advertising declaration is hard-coded rather than supplied by the owner.
- Effort: half a day. Risk: low; a broken write path becomes explicitly
  unsupported. A replacement remains Next and must always create PAUSED.

### N3. Repair brand suggestions and block invalid exclusions

- What: read `BrandSuggestion.state` instead of the nonexistent
  `entity_status`. Retain `id`, `name` and `urls`. Reject the
  existing direct-brand exclusion path before client construction.
- Why: catalogue lookup dropped the returned state, and the
  proposed campaign criterion does not exist. Operators need usable lookup and
  an honest explanation of unsupported writes.
- Evidence: `scripts/gads_brands.py:45` and `scripts/gads_brands.py:65`;
  [BrandSuggestion](https://developers.google.com/google-ads/api/reference/rpc/v25/BrandSuggestion),
  [CampaignCriterion](https://developers.google.com/google-ads/api/reference/rpc/v25/CampaignCriterion),
  [brand shared sets](https://developers.google.com/google-ads/api/docs/targeting/shared-sets).
- Effort: half a day. Risk: low. Full shared-list lifecycle is deferred.

### N4. Repair hosted credential construction and reconnect errors

- What: construct GoogleAdsClient with in-memory credentials for account
  discovery; translate revoked-refresh-token failures to the existing
  reconnect-required response without exposing provider exception text.
- Why: a successful OAuth connection could fail at baseline to list accounts;
  revocation can produce an unhandled server error instead of actionable status.
- Evidence: `webapp/app/routes/auth_routes.py:35` uses
  `load_from_dict` with a credentials object; CLI `gads_client.build_client`
  already documents why this is invalid. `webapp/app/providers.py:34` does not wrap refresh failures, while account routes catch
  `ConnectionAuthError` only.
- Effort: one day, separate changes for discovery and refresh handling.
  Risk: medium; authentication code requires mocked constructor and route tests.

### N5. Bind hosted sign-in state to its initiating browser

- What: require a short-lived HttpOnly SameSite cookie matching OAuth state
  before consuming state or exchanging a code. Clear it after successful login.
- Why: a valid server-stored state alone does not prove the callback arrived in
  the browser that started sign-in; a different browser can accept another
  person's initiated flow.
- Evidence: `webapp/app/routes/signin_routes.py:55` and `:73`;
  callback had no browser binding. Regression tests must use separate
  cookie jars. This is confirmed by handler inspection, not a production attack.
- Effort: one day. Risk: medium; concurrent sign-in tabs may invalidate the
  earlier flow. Database-level concurrent replay protection remains Next.

### N6. Select API v25 and repair removed query fields

- What: constrain the client to the reviewed 33.x series and select v25
  explicitly. Replace Shopping `sales_country` with `feed_label`, replace invalid Search
  attachment `IMAGE` with `AD_IMAGE`, rename video
  metrics, and make PMax asset reads an inventory by type/status. Remove
  unsupported performance-label and mandatory-coverage conclusions.
- Why: existing queries contain fields absent from the current schema. A logo
  absent from an asset group does not establish a campaign lacks branding.
- Evidence: `scripts/gads_assets.py:49`, `scripts/gads_query.py:110`,
  `scripts/gads_query.py:130`, `scripts/gads_creative.py:234`;
  [asset-group asset fields](https://developers.google.com/google-ads/api/fields/v25/asset_group_asset),
  [ShoppingSetting](https://developers.google.com/google-ads/api/reference/rpc/v25/Campaign.ShoppingSetting),
  [Metrics](https://developers.google.com/google-ads/api/reference/rpc/v25/Metrics),
  [campaign asset enum](https://developers.google.com/google-ads/api/fields/v25/campaign_asset).
- Effort: one day. Risk: medium; asset inventory and Shopping output fields
  change. Local descriptor checks cannot replace a later owner-run API check.
  This is a separate compatibility commit with the complete test suite.

### N7. Align operator instructions with implemented reads

- What: correct unsupported flags and claims about asset labels, competitor
  domains, consent verification and campaign creation. State read limitations.
- Why: an agent following an overstated skill can give an account owner a false
  assurance or issue a command the parser rejects.
- Evidence: `skills/gads-assets/SKILL.md:14` puts global `--json` after subcommands;
  `skills/gads-audit/SKILL.md:44` advertises PDF although `gads_report.py` supports
  Markdown/HTML; compare the gtag, competitors, Shopping and PMax agents with
  their adapters' SELECT clauses.
- Effort: one day. Risk: low; documentation only.

### N8. Add a small Demand Gen read adapter

- What: campaign performance rows with impressions, spend and conversions over a
  requested date range, with a skill, agent and audit-driver entry. No writes or optimisation claims.
  Omit clicks until their surface-specific semantics are modelled.
- Why: accounts running Demand Gen are missing from the current channel reads.
- Evidence: existing filters in `scripts/gads_query.py:98` and `:139`;
  [official Demand Gen reporting](https://developers.google.com/google-ads/api/docs/demand-gen/reporting).
- Effort: half to one day. Risk: low; mocked read tests and schema checks only.

### N9. Correct the age-demographics resource

- What: query `age_range_view` instead of the nonexistent `age_view`; extend
  the offline schema tests to SQL literals in every adapter.
- Why: an age report (and the combined demographics audit) otherwise fails
  before returning any age buckets.
- Evidence: `scripts/gads_demographics.py:33` and the final descriptor sweep;
  [official age-range view](https://developers.google.com/google-ads/api/fields/v25/age_range_view?authuser=19).
- Effort: less than half a day. Risk: low; no output-shape or heuristic change.
  Discovered during the final broader resource check and added to this pass.

### N10. Preserve API names when serializing response enums

- What: translate Python-reserved protobuf names such as `type_` to their API
  names while retaining snake_case elsewhere.
- Why: real age/gender and recommendation responses were silently classified
  as UNKNOWN; hand-written dictionary fixtures hid the mismatch.
- Evidence: baseline `scripts/gads_client.py:55` preserves protobuf names;
  `scripts/gads_demographics.py:158` and `scripts/gads_recommendations.py:47`
  expect `type`. Reproduced locally with real v25 GoogleAdsRow messages and
  anonymous credentials, without a service call.
- Effort: half a day. Risk: medium; consumers that used the unintended `type_`
  output must use `type`. Regression tests retain micros and fractional values.
  Discovered while testing real demographic messages during final review.

## Next

| Item | Account benefit and evidence | Effort | Risk / reason not built now |
| --- | --- | --- | --- |
| Expand adapter tests and structured read errors | Prevent silent audit omissions; the baseline coverage gaps above include the audit dispatcher itself. Test empty results, permissions, removed resources and malformed responses. | 3–5 days | Medium; needs adapter-specific expected behavior, beyond a single small repair. |
| Review Cloud project access and onboarding | Let newly approved projects connect without an obsolete token requirement. `gads_auth.py`, `gads_provider.py`, web settings and SETUP assume a token. [Migration guide](https://developers.google.com/google-ads/api/docs/api-policy/developer-token). | 2–4 days | High; changes both credential models and onboarding; preserve the 24-hour gate. |
| Build an atomic, channel-specific campaign writer | Apply exactly the reviewed budget, bidding, targeting and declaration with temporary resource names in one validated batch. [Mutating resources](https://developers.google.com/google-ads/api/docs/mutating/overview), N2. | 5–10 days | High; broad channel creation is not a small feature. Search language retirement and political declarations need explicit design. |
| Implement brand shared-list lifecycle | Exclude the intended brands without duplicate lists or unintended campaign scope. [Shared sets](https://developers.google.com/google-ads/api/docs/targeting/shared-sets), N3. | 2–4 days | High; needs list ownership, reuse, idempotency and campaign compatibility rules. |
| Add PMax channel, placement and asset metrics | Explain where spend moved and distinguish campaign branding from group assets. [Channel reporting announcement](https://ads-developers.googleblog.com/2026/01/introducing-channel-level-reporting-for.html), [asset fields](https://developers.google.com/google-ads/api/fields/v25/asset_group_asset). | 3–5 days | Medium; aggregating incompatible segments would mislead account decisions. |
| Add conversion diagnostics and consent evidence | Show primary goals and delivery diagnostics separately from detected HTML tags. `gads_conversions.py`, `gads_gtag.py`; [consent concepts](https://developers.google.com/tag-platform/security/concepts/consent-mode), [upload deprecations](https://developers.google.com/google-ads/api/docs/deprecations). | 3–5 days | High; no event uploads or claims of legal compliance from a static page scan. |
| Add Demand Gen channel and AI Max settings reads | Explain surface allocation and migrations; begin from the small Now campaign read. [Channel controls](https://developers.google.com/google-ads/api/docs/demand-gen/channel-controls), [release notes](https://developers.google.com/google-ads/api/docs/release-notes). | 2–4 days | Medium; eligibility, automation opt-ins and attribution need separate fixtures. |
| Repair multi-account audit boundaries | `scripts/gads_audit.py:77` uses ThreadPoolExecutor without copying bound provider context; `scripts/gads_audit.py:105` uses directly accessible accounts rather than expanding manager hierarchies. Hosted audit is not exposed today, so cross-tenant impact is a risk, not an observed leak. | 2–4 days | High; add tenant and manager hierarchy fixtures before exposing hosted audit. |
| Preserve nested and per-entity findings | `scripts/gads_demographics.py:180` nests findings, while `scripts/gads_report.py:76` inspects top-level findings; `scripts/gads_history.py:127` keys diffs by agent/code, collapsing distinct entities. | 1–2 days | Medium; choose a stable finding identity and output migration first. |
| Harden hosted state consumption and disconnect | State consumption is read-then-delete; concurrent callbacks need atomic database handling. Disconnect decrypts before its cleanup guard, so corrupt ciphertext can prevent cleanup. `webapp/app/routes/signin_routes.py:80`, `webapp/app/routes/auth_routes.py:75`, `webapp/app/routes/account_routes.py:86`. | 1–3 days | High; database concurrency and cleanup semantics need explicit tests beyond browser-state binding. |
| Sanitise broader error output | `scripts/gads_audit.py:99` returns raw exception text and a traceback. Provider details may enter reports; no secret disclosure was observed. | 1–2 days | Medium; define useful redacted diagnostics across adapters and distinguish retryable failures from reconnect requirements. |
| Validate keyword locale choices | `scripts/gads_keywords.py:18` silently substitutes US/English for unsupported codes. Reject unknown codes or resolve constants explicitly so forecasts match the intended market. | 1 day | Medium; clarify supported input forms before changing existing callers. |

## Later

| Proposal | Evidence and value | Effort | Risk / decision |
| --- | --- | --- | --- |
| Optional read-only MCP interface or interoperability guide | Google's [Google Ads MCP](https://github.com/googleads/google-ads-mcp) provides query and resource-metadata tools. Schema discovery is useful for validating agent-generated GAQL. | 3–5 days | Medium; reuse upstream where practical; a new server changes project shape and must preserve session gates. |
| Reusable multi-account report exports | Google's [Ads API Report Fetcher](https://github.com/google/ads-api-report-fetcher) offers configurable reports and output integrations. This toolkit's reports are local Markdown/HTML. | 3–5 days | Medium; valuable for teams, but reporting infrastructure is outside the current adapter repair. |
| Read-only query export | [cohnen/mcp-google-ads](https://github.com/cohnen/mcp-google-ads) documents general GAQL tools with table, JSON and CSV output. A reviewed query/export command could cover occasional reporting gaps. | 2–3 days | Medium; validate query scope and preserve the session gate; do not copy stale example fields. |
| Agent evaluation fixtures | [google-ads-api-agent](https://github.com/itallstartedwithaidea/google-ads-api-agent) documents campaign creation, experiments and ad-schedule managers, beyond this toolkit's reads. Compare those workflows using mocked tasks, especially confirmation and unsupported requests. Its advertised capabilities have not been executed or safety-audited here. | 3–5 days | Low for offline evaluation; no unattended spend changes. |
| Monitoring integrations | [Ads Monitor](https://github.com/google-marketing-solutions/ads-monitor) uses monitoring infrastructure for account signals. Exporting findings could help existing operations teams. | 3–5 days | Medium; no autonomous session renewal or hidden background access after 24 hours. |

## Open questions and rejected directions

- Leave session behavior unchanged. `scripts/gads_auth.py:432` (`cmd_use_profile`) writes a new
  session timestamp when selecting a profile. Does switching an existing
  profile intentionally begin a new 24-hour window? Resolve with the owner;
  do not change `enforce_session` or the session hook in this pass.
- Pacing includes the current incomplete day and repeats shared budgets across
  campaigns; several findings format money as dollars regardless of account
  currency. Thresholds and budget attribution need a product decision before
  changing recommendations (`scripts/gads_pacing.py:43`, `scripts/gads_demographics.py:139`).
- Website regex checks cannot verify GA4 linking, tag firing, enhanced
  conversions or consent. Reject any "tracking is healthy" guarantee based
  solely on `gads_gtag.py` output.
- Reject unattended optimisation, an auto-apply flag, a session bypass, live
  account tests and scheduled credential renewal. These conflict with this
  repository's safety model, even if a comparable tool permits them.
- Reject paid creative-generation dependencies. Retain bring-your-own images;
  an API or beta elsewhere is not evidence that all users can access it.
- Reject building a full dashboard, agent framework rewrite or new hosted MCP
  service during this pass. Existing upstream tools are comparison points,
  not a reason to expand the architecture before repairing its boundaries.
- GAQL combinations, new-project access, account eligibility, token revocation
  responses and real browser OAuth deployment remain unverified against live
  services. The owner should validate them in a separate controlled review.

## Completion record

N1: `5d3ee11`; N2: `9eda92c`; N3: `aa4faa7`; N4: `ca03248` and
`3649efa`; N5: `e8e44fe`; N6: `73aa769`; N7: `b4fda27`; N8: `54eb00b`;
N9: `f65ad48`; N10: `5947a0e`.
All code changes have an Unreleased changelog entry. No live service or account
was used to validate these changes. The session cap and hook are unchanged.
