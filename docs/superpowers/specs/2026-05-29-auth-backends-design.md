# Auth backends + bring-your-own OAuth client — design

## Problem

The toolkit resolves credentials in exactly one way: `google.auth.default()`
picks up gcloud Application Default Credentials written by
`gcloud auth application-default login` (see `gads_auth.get_credentials`).

That single path breaks under a restrictive Google Workspace. A Workspace
admin can block the "Google Cloud SDK" OAuth client used by gcloud, or
restrict the `adwords` scope, at the org level via App Access Control. A
non-admin user then has no way to sign in and no workaround.

The project's founding decision — "no per-user OAuth client to register" —
is exactly what fails here. It must become one option among several rather
than the only path.

## Forward context (not built here)

This CLI is intended to grow into a multi-tenant web app where marketers
connect their own Google Ads account and get a dashboard. That future
inverts the auth model: the **app** owns one OAuth client (Web type) and one
developer token with standard access, and each marketer grants OAuth consent
so the app stores **their** refresh token server-side.

The relevant consequence for this design: the token-exchange, refresh, and
storage code added now is the same machinery the web app needs. Only the
*flow* (loopback vs. redirect) and the *store* (local file vs. database)
differ later. This spec builds the CLI backend and designs those two seams
cleanly; it does not build the server, the database store, or the
centralized developer token.

Note on scopes: `adwords` is a restricted scope. A public web app needs
Google OAuth verification for it. An **Internal** Workspace OAuth app does
not — which is also why an Internal client unblocks the restricted-Workspace
user today.

## Goals

1. Add an auth backend that does not depend on the gcloud OAuth client, so a
   restricted-Workspace user can authenticate with their own OAuth client.
2. Keep gcloud ADC as the default; existing setups are unaffected.
3. Leave every downstream script unchanged — they call
   `gads_client.build_client()`, which transparently supports both backends.
4. Design the token store and refresh core as clean seams the future web app
   can extend without rewriting backend or client code.

## Non-goals

- Web server, multi-tenant database token store, dashboard.
- OAuth app verification submission.
- App-owned / centralized developer token (stays per-profile here).
- Service-account / domain-wide-delegation backend (a plausible third
  backend later for admins; not built now).

## Architecture

### Auth backends — `scripts/gads_authflow.py`

A small protocol:

```python
class AuthBackend(Protocol):
    def credentials(self):
        """Return a refreshed google.auth credentials object."""
```

Two implementations:

- `GcloudAdcBackend` — wraps the current
  `google.auth.default(scopes=[ADWORDS])`. Default backend.
- `OAuthClientBackend` — constructs
  `google.oauth2.credentials.Credentials(token=None, refresh_token=...,
  client_id=..., client_secret=..., token_uri="https://oauth2.googleapis.com/token",
  scopes=[ADWORDS])` and refreshes it via
  `google.auth.transport.requests.Request`. No gcloud dependency.

`gads_auth.get_credentials()` remains the single entry point. It reads the
active profile's `auth_method`, dispatches to the matching backend, then
calls `enforce_session()` exactly as today. The 24-hour session cap is
unchanged and applies to both backends.

`gads_client.build_client()` is unchanged: it already calls
`gads_auth.get_credentials()`.

### Profile schema

Each profile gains `auth_method`, one of `"gcloud_adc"` (default) or
`"oauth_client"`. For `oauth_client`, the profile also carries `client_id`,
`client_secret`, and `refresh_token`.

`_migrate_if_flat` and `add_profile` default `auth_method` to `gcloud_adc`,
so migrated and existing profiles keep working with no change in behavior.

Credentials file layout after this change:

```json
{
  "active": "acme",
  "profiles": {
    "acme": {
      "developer_token": "...",
      "login_customer_id": "...",
      "auth_method": "gcloud_adc"
    },
    "widgets": {
      "developer_token": "...",
      "login_customer_id": "...",
      "auth_method": "oauth_client",
      "client_id": "...",
      "client_secret": "...",
      "refresh_token": "..."
    }
  }
}
```

### Token-store seam — `scripts/gads_tokenstore.py`

A minimal interface:

```python
class TokenStore(Protocol):
    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, record: dict) -> None: ...
```

`key` is the profile name; `record` holds `client_id`, `client_secret`,
`refresh_token`.

The only implementation now is `LocalFileTokenStore`, backed by the existing
`~/.claude/gads-credentials.json` (the OAuth fields live inside the profile,
written at file mode `0600`, as today). All refresh-token reads and writes go
through this interface so the web app can later drop in a `DbTokenStore`
keyed by user id without touching `OAuthClientBackend` or `gads_client`.

Decision: refresh tokens stay inside the existing credentials file behind the
store interface rather than a new file. Simpler, one fewer file to manage,
still swappable.

### Login command — loopback browser flow

New subcommand on `gads_auth.py`:

```
python scripts/gads_auth.py --oauth-login \
    --client-secrets client_secret.json \
    [--add-profile NAME --developer-token TOKEN --login-customer-id MCC] \
    [--no-browser]
```

Behavior:

1. `google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
   client_secrets, scopes=[ADWORDS])`.
2. `flow.run_local_server(port=0)` opens the browser and captures the
   loopback redirect, returning credentials including a refresh token.
   `--no-browser` calls `run_local_server(open_browser=False)` and prints the
   URL for headless or remote sessions.
3. Persist `client_id`, `client_secret`, `refresh_token` via the token store,
   set `auth_method="oauth_client"` on the target profile (creating it when
   `--add-profile` is supplied), and start the 24-hour session.

Manual fallback: for the rare case where even GCP project creation is blocked,
a profile can be populated by pasting a pre-obtained `refresh_token` plus
`client_id`/`client_secret` through a documented set path. This reuses the
same backend; no extra code beyond the setter.

The loopback redirect requires a **Desktop** OAuth client type and a free
localhost port. Documented in SETUP.

### New dependency

Add `google-auth-oauthlib` (the standard companion to `google-auth` for the
installed-app flow) to `scripts/requirements.txt` and `pyproject.toml`.

## Documentation

`docs/SETUP.md` gains "Option B — your own OAuth client (restricted Google
Workspace)":

1. Create a Google Cloud project in your Workspace org.
2. OAuth consent screen → **Internal** (no Google verification needed for the
   restricted `adwords` scope; Internal sidesteps the org's third-party-app
   block).
3. Create an OAuth client of type **Desktop**; download `client_secret.json`.
4. `python scripts/gads_auth.py --oauth-login --client-secrets client_secret.json`.

gcloud ADC stays documented as "Option A" (the default, for unrestricted
users). A short note records the web-app trajectory: the same flow becomes a
Web client with a redirect URI, the same refresh core is reused, and
`DbTokenStore` replaces the file store.

README "Authenticate" section gets a one-paragraph pointer to Option B for
Workspace users.

## Testing

`scripts/test_gads_authflow.py` and additions to
`scripts/test_gads_auth.py`:

- Backend selection: a profile with `auth_method="oauth_client"` routes to
  `OAuthClientBackend`; default and migrated profiles route to
  `GcloudAdcBackend`.
- `OAuthClientBackend` constructs `Credentials` with the expected fields and
  triggers a refresh; the network refresh is mocked.
- `LocalFileTokenStore` get/set round-trips and preserves `0600`.
- Migration: an old flat credentials file and pre-existing profiles default to
  `auth_method="gcloud_adc"`.
- `--oauth-login` persistence: with `InstalledAppFlow` mocked, the resulting
  refresh token and `auth_method` land on the correct profile and the session
  starts. The browser loopback itself is not exercised.

## Risks and notes

- `run_console` was removed from recent `google-auth-oauthlib`; use
  `run_local_server`. Loopback requires a Desktop client and an open localhost
  port. Both are documented.
- If a Workspace blocks GCP project creation entirely, Option B is
  unavailable; the manual refresh-token paste fallback covers that case.
- The 24-hour session cap behavior is intentionally unchanged for both
  backends.
