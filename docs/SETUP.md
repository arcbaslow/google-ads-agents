# Setup

Walkthrough for getting `google-ads-agents` running end-to-end.

## 1. Install gcloud

If `gcloud` isn't already on your machine, follow
https://cloud.google.com/sdk/docs/install.

Verify:

```
gcloud --version
```

## 2. Approve the OAuth Cloud project

API access belongs to the Google Cloud project that owns your OAuth client.
Enable the Google Ads API and apply for the appropriate access level in that
project's Google Ads API page in Cloud Console. Developer tokens were retired
on September 9, 2026. A token from another project does not grant access.
See Google's [migration guide](https://developers.google.com/google-ads/api/docs/api-policy/developer-token).

For new integrations, use your own OAuth client in the approved project
(Option B). With gcloud ADC, confirm which OAuth client/project issues the
credentials; setting a quota project alone does not transfer API access.
Workspace administrator policy can still require approval of the OAuth app.

## 3. Sign in

Two ways to authenticate. Pick one per profile.

### Option A — gcloud (default)

From the project directory:

```
python scripts/gads_auth.py --adc
```

It prints the exact `gcloud auth application-default login --scopes=...`
command. Run it. A browser opens, sign in, grant access.

### Option B — your own OAuth client (restricted Google Workspace)

Use your own OAuth client to select the Cloud project with approved Ads API
access. Your organisation may still require administrator approval.

1. Create a Google Cloud project in your Workspace org
   (https://console.cloud.google.com/projectcreate).
2. APIs & Services -> OAuth consent screen -> User type **Internal**.
   Follow the applicable verification and administrator requirements.
3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID ->
   Application type **Desktop app**. Download the JSON as
   `client_secret.json`.
4. Run the loopback flow:

```
python scripts/gads_auth.py --oauth-login \
    --client-secrets client_secret.json \
    --add-profile acme --login-customer-id <MCC>
```

A browser opens on a localhost port; sign in and grant access. The refresh
token is stored in the profile (file mode 0600) and the 24h session starts.
On a headless machine add `--no-browser` to print the URL instead.

If even creating a Cloud project is blocked, obtain a refresh token with your
client elsewhere and paste it:

```
python scripts/gads_auth.py --set-oauth acme \
    --client-id <ID> --client-secret <SECRET> --refresh-token <TOKEN>
```

> Web-app trajectory: the same flow becomes a **Web** OAuth client with a
> redirect URI, the refresh/exchange code is reused, and a database token
> store replaces the local file. See
> `docs/superpowers/specs/2026-05-29-auth-backends-design.md`.

## 4. Configure local credentials

Option B users who passed `--add-profile` to `--oauth-login` already have a
profile and can skip to Verify.

Add a profile per manager account. Each profile stores its authentication method
and optional login-customer-id. Legacy developer tokens remain optional.

```
python scripts/gads_auth.py --add-profile acme \
    --login-customer-id <MCC-id>
```

If you only have one MCC, one profile is enough — it becomes active
automatically. For multiple MCCs, add a profile per account and switch
with `--use-profile`:

```
python scripts/gads_auth.py --add-profile widgets --login-customer-id <MCC2>
python scripts/gads_auth.py --use-profile widgets
python scripts/gads_auth.py --list-profiles
```

The customer ID is the 10-digit account number, with or without dashes.

## 5. Verify

```
python scripts/gads_auth.py --check
python scripts/gads_auth.py --customers
```

`--customers` lists every Ads customer your signed-in user can access.

## 6. Run an audit

```
python scripts/gads_search.py --customer <id> --days 28 --json
```

or from inside Claude Code:

```
/gads audit <id>
```

The audit driver preserves a bound credential provider across account and
adapter workers. Custom providers must support concurrent reads; copying
their context does not make a database session safe to share between threads.
The hosted service does not expose the audit driver.

## Session expiry

The local session is good for 24 hours from the last
`--set-developer-token` (or `--check` after re-auth). After that, every
script refuses to run and prints the gcloud command. Re-sign-in and the
24h clock resets.

## Troubleshooting

- **`AuthRequiredError: No application default credentials found`** —
  you haven't run the `gcloud auth application-default login` command,
  or `~/.config/gcloud/application_default_credentials.json` was
  deleted.
- A missing legacy developer token is allowed; verify the OAuth Cloud project has access.
- **`CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION`** — request production access
  in the OAuth project's Google Ads API page in Cloud Console.
- **`USER_PERMISSION_DENIED`** — the signed-in Google account doesn't
  have access to that Ads customer ID. Check via `--customers`.

## Reviewing writes

Negative-keyword, placement and creative writes enforce JSON review and `y/N`
in the Python adapter. Preview and prompt go to stderr; the result goes to
stdout. Both validation and application require a human answer. `--apply`
validates first and stops on validation failure. Missing input cancels.

Campaign context remains planning-only. The strict `--search-spec` writer creates
a PAUSED Search shell with a dedicated budget and explicit locations. See
[bounded writes](WRITES.md) before using validation or application.

Brand catalogue lookup returns entity IDs, display names, primary URLs and
catalogue states. Brand exclusion writes are unavailable until shared-list
management is implemented. No exclusion request is sent.

## Hosted account discovery

The optional hosted service constructs its Ads client from the connected
user's refreshed in-memory credentials. It lists directly accessible customer
IDs after OAuth consent; this is not a recursive manager-account expansion.
If listing fails, the callback retains the connection and returns a warning.

A permanent OAuth refresh failure on the hosted account summary returns HTTP
409 with `reconnect required`. Reconnect through OAuth consent. Retryable
refresh failures are not classified as revoked grants.

Hosted sign-in must start and finish in the same browser. A short-lived
HttpOnly SameSite=Lax cookie binds the callback to that browser; production
uses Secure cookies and therefore requires HTTPS. Starting another sign-in
flow replaces the previous cookie. Restart sign-in if a flow expires.

Disconnect clears the locally stored token even if its ciphertext or key
version is unreadable. The response's `revoked` flag is false when revocation
at Google could not be confirmed; local disconnection alone does not revoke
the Google grant. Database write failures still require operator attention.

## API compatibility

The adapters select API v25 and require `google-ads>=33.0.0,<34.0.0`.
Reinstall the project dependencies when updating from an older checkout.
Shopping output uses `feed_label` rather than `sales_country`; a feed label
need not be a country. Video reporting uses `video_trueview_views` and
`video_trueview_view_rate`. Search image attachment uses `AD_IMAGE`.

PMax asset output is an inventory of non-removed group links, grouped by type
and status. It does not include campaign branding, groups without links,
performance labels or required-coverage findings. A link status is not proof
that an asset is serving. See ROADMAP.md for reporting proposals and sources.

## Demand Gen reads

Use `python scripts/gads_demandgen.py --customer <id> --days 28 --json` or
`/gads demandgen <id>`. The audit driver includes the same read. It returns
campaign status, bidding type, impressions, cost_micros, conversions and
conversion value. It excludes removed campaigns and uses a date range ending
yesterday. Zero-activity campaigns may be absent from a metrics query.

Clicks and channel/asset breakdowns are deliberately outside this adapter.
Google documents a CROSS_NETWORK click-type filter for Demand Gen clicks;
applying that filter to other totals would change their scope. See the
[reporting guide](https://developers.google.com/google-ads/api/docs/demand-gen/reporting).

Age demographics uses the API's `age_range_view`. Run
`python scripts/gads_demographics.py --customer <id> --days 28 --json age`.

## Keyword research locales

`gads_keywords.py` accepts languages `en`, `es`, `de`, `fr` and countries
`US`, `GB`, `CA`, `AU`. Input is trimmed and case-insensitive. Omitting the
options still selects English and the US. Any other code, numeric ID or
resource name is rejected before client construction; unsupported input no
longer silently selects English or the US. Python callers receive ValueError;
the CLI reports the supported choices and exits with status 2.

These are adapter limits, not the full set of Google Ads locales. The
[keyword request reference](https://developers.google.com/google-ads/api/reference/rpc/v25/GenerateKeywordIdeasRequest)
defines language and geography as resource names. Supporting additional
markets needs explicit constant resolution rather than a fallback.

Read-result JSON preserves snake_case field names and uses the API spelling
for Python reserved words (`type`, not `type_`). This keeps demographic and
recommendation enum labels intact.

Hosted OAuth callbacks consume state with one database DELETE RETURNING before
code exchange. State remains bound to its purpose and owner or initiating browser.
Concurrent callbacks cannot reuse it; failures require starting a new flow.

Audit and write failures use safe error categories, without provider exception
text or tracebacks. Retry hints do not trigger retries; inspect account state
before retrying a write whose result is unknown.
