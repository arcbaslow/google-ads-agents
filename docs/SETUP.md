# Setup

Walkthrough for getting `google-ads-agents` running end-to-end.

## 1. Install gcloud

If `gcloud` isn't already on your machine, follow
https://cloud.google.com/sdk/docs/install.

Verify:

```
gcloud --version
```

## 2. Get a developer token

The Google Ads API requires a developer token. It is account-level
(tied to a manager account / MCC), not user-level.

1. Sign into a Google Ads manager account at https://ads.google.com.
2. Go to **Tools & Settings → API Center**
   (URL: https://ads.google.com/aw/apicenter).
3. Apply for a token if you don't have one. A new token defaults to
   **test access** which is fine for read paths against test accounts.
   Production access requires a separate approval.

Keep the token. You'll paste it once.

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

If your Workspace admin blocks the gcloud sign-in ("Access blocked: this app
is blocked"), use your own OAuth client. It does not depend on the gcloud app
and needs no admin help.

1. Create a Google Cloud project in your Workspace org
   (https://console.cloud.google.com/projectcreate).
2. APIs & Services -> OAuth consent screen -> User type **Internal**.
   Internal apps skip Google verification for the restricted `adwords`
   scope and are not subject to the org's third-party-app block.
3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID ->
   Application type **Desktop app**. Download the JSON as
   `client_secret.json`.
4. Run the loopback flow:

```
python scripts/gads_auth.py --oauth-login \
    --client-secrets client_secret.json \
    --add-profile acme --developer-token <TOKEN> --login-customer-id <MCC>
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

Add a profile per manager account. Each profile owns its developer token
and (optional) login-customer-id.

```
python scripts/gads_auth.py --add-profile acme \
    --developer-token <TOKEN> \
    --login-customer-id <MCC-id>
```

If you only have one MCC, one profile is enough — it becomes active
automatically. For multiple MCCs, add a profile per account and switch
with `--use-profile`:

```
python scripts/gads_auth.py --add-profile widgets --developer-token <TOKEN2> --login-customer-id <MCC2>
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
- **`developer_token missing`** — run
  `python scripts/gads_auth.py --set-developer-token <TOKEN>`.
- **API returns `DEVELOPER_TOKEN_NOT_APPROVED`** — your token is in
  test mode; either apply for production access at the API Center, or
  use a test account.
- **`USER_PERMISSION_DENIED`** — the signed-in Google account doesn't
  have access to that Ads customer ID. Check via `--customers`.

## Reviewing writes

Negative-keyword, placement and creative writes enforce JSON review and `y/N`
in the Python adapter. Preview and prompt go to stderr; the result goes to
stdout. Both validation and application require a human answer. `--apply`
validates first and stops on validation failure. Missing input cancels.

Campaign creation is planning-only. Its draft is not API operation JSON; both
write flags return `unsupported` without creating a client or budget.

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

Read-result JSON preserves snake_case field names and uses the API spelling
for Python reserved words (`type`, not `type_`). This keeps demographic and
recommendation enum labels intact.
