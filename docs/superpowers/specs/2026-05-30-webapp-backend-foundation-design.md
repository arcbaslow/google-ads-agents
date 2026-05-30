# Web app backend foundation — design

## Problem

The toolkit is single-user by construction. `gads_client.build_client()` resolves
everything from one globally-active, file-backed profile via
`gads_auth.get_credentials()`, `get_developer_token()`, and
`get_login_customer_id()`. There is no notion of "which user" — the active
profile is process-global state read from `~/.claude/gads-credentials.json`.

The product goal is a multi-tenant web app where a marketer signs in, connects
their own Google Ads account through OAuth consent, and the app resolves
credentials **per request, per user** from server-side storage. That inverts the
auth model the CLI assumes.

The 0.6.0 auth work (pluggable `AuthBackend`, `OAuthClientBackend`, the
`TokenStore` seam) already built the token-exchange / refresh / storage
machinery the web app needs. What remains for this first slice is to (a) remove
the global-state assumption so credentials resolve per user, (b) add a
DB-backed multi-tenant store, and (c) add the web OAuth redirect flow.

## Scope

This is the **first sub-project** of the web-app trajectory: the backend
multi-tenant foundation. It exposes a minimal internal HTTP API. It does **not**
include real app sign-in UI, a dashboard, async jobs, or the broader read-path
API — those are separate sub-projects (see "Out of scope").

Chosen decisions (from brainstorming):

- Web stack: **Python + FastAPI** (reuses the existing `scripts/` in-process).
- DB: **Postgres + SQLAlchemy + Alembic**.
- Token security: **app-level Fernet encryption with key versioning**.
- Developer token: **app-owned single token** (app config, not per-user data).
- Identity: **stubbed** for this slice; real sign-in deferred.
- Credential resolution: **provider seam + `contextvar`** (Approach A).

## Out of scope

- Real app authentication (passwords / SSO, cookie sessions, CSRF for app login).
- Dashboard / frontend UI.
- The full read-path HTTP API (only one proof-of-life read endpoint here).
- Async / background jobs and scheduled refreshes.
- Multiple Google connections per user (one connection per user this slice;
  the token store is still keyed by `connection_id` to keep that door open).
- Obtaining Google **standard access** for the app-owned developer token — an
  operational/policy task tracked separately.

## Architecture

### Module layout

The web service is a new top-level package. The dependency arrow points one way:
`webapp` imports the toolkit; the toolkit never imports `webapp`.

```
google-ads-agents/
  scripts/                  # CLI toolkit (read paths, gads_auth, gads_client)
    gads_provider.py        # NEW: CredentialProvider protocol, the contextvar,
                            #   get_active_provider(), bind helpers,
                            #   FileCredentialProvider default. Imports gads_auth.
  webapp/
    app/
      main.py               # FastAPI app factory, router wiring, lifespan
      config.py             # typed settings from env / secret manager
      db.py                 # SQLAlchemy engine/session, get_session dependency
      models.py             # User, Connection, OAuthState
      crypto.py             # Fernet encrypt/decrypt with key versioning
      identity.py           # current-user resolution (stub seam)
      providers.py          # WebCredentialProvider (binds via gads_provider helper)
      tokenstore_db.py      # DbTokenStore (TokenStore impl)
      oauth.py              # web OAuth redirect flow helpers
      routes/
        auth_routes.py      # GET /oauth/google/start, /oauth/google/callback
        account_routes.py   # GET /accounts, POST select, GET summary
    alembic/                # migrations
    tests/
    requirements.txt
```

Two additive touches reach into `scripts/`, both preserving current behavior:

1. A new `scripts/gads_provider.py` holds the `CredentialProvider` protocol, the
   `contextvar`, `get_active_provider()`, the per-request bind/reset helpers, and
   the `FileCredentialProvider` default (wrapping `gads_auth`). It imports
   `gads_auth`; nothing in it imports `webapp`. This is what keeps the dependency
   arrow one-way: the toolkit owns the contextvar and registry, and `webapp`
   merely supplies a `WebCredentialProvider` and calls the toolkit's bind helper.
2. `gads_client.build_client()` calls `gads_provider.get_active_provider()`
   instead of `gads_auth` directly. With no provider bound, it returns the default
   `FileCredentialProvider`, so the CLI and every script behave identically.

### Credential provider seam

Generalizes the `TokenStore` seam into a credential-resolution seam.

```python
class CredentialProvider(Protocol):
    def get_credentials(self): ...          # refreshed google.auth credentials
    def get_developer_token(self) -> str: ...
    def get_login_customer_id(self) -> str | None: ...
```

Implementations:

- **`FileCredentialProvider`** (in `scripts/`, CLI default) — wraps today's
  `gads_auth` functions verbatim. The **24-hour local session cap stays here**
  (it calls `enforce_session()`); CLI behavior is byte-for-byte unchanged.
- **`WebCredentialProvider`** (in `webapp/`) — constructed per request from the
  resolved connection. Wires `DbTokenStore` into the existing 0.6.0
  `OAuthClientBackend` (the same `select_backend(profile, store)` path) and reads
  the app-owned developer token from config. It does **not** call
  `enforce_session()`.

`get_active_provider()` (in `gads_provider.py`) resolves:

1. a provider bound to the current `contextvar`, if set (web path); else
2. the process default `FileCredentialProvider` (CLI and all scripts, unchanged).

`build_client()` calls `get_active_provider()` and uses whatever it returns.

### 24-hour session cap

The 24h cap is a **CLI-local** safety valve (force a fresh `gcloud` / OAuth
login). It does **not** apply to the web path. Web credential validity is
governed by OAuth refresh-token health plus the app's own login session (a later
sub-project). `enforce_session()` therefore lives only inside
`FileCredentialProvider`; `WebCredentialProvider` never calls it.

### Per-request binding

A FastAPI dependency resolves the current user (`identity.py`), constructs a
`WebCredentialProvider` for the target connection, and binds it to the
`contextvar`. The binding token is **reset in a `finally`** when the request
ends. `contextvar` is the correct primitive: it isolates per-request state across
async tasks without leaking between concurrent requests.

### Data model

Domain tables (SQLAlchemy, Alembic-migrated):

```
users
  id            uuid  pk
  email         text  unique (nullable during the stub phase)
  created_at    timestamptz

connections                      # one row per user's OAuth grant (one per user this slice)
  id                  uuid  pk
  user_id             uuid  fk → users
  google_email        text            # which Google identity granted consent
  refresh_token       bytea           # Fernet ciphertext (the only per-user secret)
  token_version       int             # Fernet key id used → enables rotation
  customer_id         text  null      # selected Google Ads CID for requests
  login_customer_id   text  null      # set when reached through the user's MCC
  accessible_customers jsonb          # list from listAccessibleCustomers
  scopes              text
  created_at / updated_at / revoked_at  timestamptz
```

Ephemeral / operational table (rows short-lived, deleted on use):

```
oauth_states
  state          text  pk            # random, high-entropy
  user_id        uuid  fk → users
  code_verifier  text                # PKCE verifier
  created_at     timestamptz
  expires_at     timestamptz
```

**What is and isn't encrypted.** In the app-owned-token model, `client_id` /
`client_secret` belong to the app's one Web OAuth client and live in config /
secret manager, not the DB. The developer token is app config too. The **only
per-user secret stored is the refresh token**, encrypted at rest. The record
`OAuthClientBackend` expects (`client_id`, `client_secret`, `refresh_token`) is
assembled by `DbTokenStore.get()`: it decrypts the per-user `refresh_token` from
the row and fills `client_id` / `client_secret` from config. This keeps the
`TokenStore` contract identical to `LocalFileTokenStore` and leaves
`OAuthClientBackend` untouched.

### Encryption — `crypto.py`

Fernet with key versioning. Config holds an ordered keyring (current key first).
`encrypt()` uses the current key and records its `token_version` on the row;
`decrypt()` looks up the key by the row's stored version. Rotation = prepend a
new current key; existing rows still decrypt under their stored version and can
be lazily re-encrypted on next write. `cryptography.fernet.MultiFernet` provides
this directly.

### DbTokenStore — `tokenstore_db.py`

Implements the same `TokenStore.get / set(key, record)` contract as
`LocalFileTokenStore`, keyed by `connection_id`. `set()` encrypts the refresh
token (recording `token_version`); `get()` decrypts it and merges the config
`client_id` / `client_secret` into the returned record, so `OAuthClientBackend`
is untouched. The same contract tests that cover `LocalFileTokenStore` run
against `DbTokenStore`.

### Web OAuth redirect flow — `oauth.py` + `routes/auth_routes.py`

App-owned **Web** OAuth client.

- `GET /oauth/google/start` — generate a PKCE `code_verifier` / `code_challenge`,
  persist an `oauth_states` row (random `state`, bound to `user_id`, with the
  verifier and a short TTL), build the Google authorization URL from the config
  Web client with `redirect_uri = .../oauth/google/callback`, `scope=[adwords]`,
  `access_type=offline`, `prompt=consent` (forces a refresh token), `state`, and
  the PKCE challenge. Respond `302` to Google.
- `GET /oauth/google/callback?code&state` — load the `oauth_states` row by
  `state`; reject if missing, expired, or not owned by the current user;
  **delete it (single-use)**; exchange `code` (with the PKCE verifier) via
  `google-auth-oauthlib` `Flow.fetch_token`; extract `refresh_token` and
  `google_email`; call `listAccessibleCustomers` to fill `accessible_customers`;
  encrypt and persist the refresh token through `DbTokenStore`; upsert the
  `connections` row; default `customer_id` to the first accessible customer.
  Return JSON (no UI): connection id + accessible customers.

State is verified with a constant-time comparison and is single-use: an
`oauth-state` pattern hardened with PKCE and server-side persistence.

### Identity stub — `identity.py`

A `get_current_user()` FastAPI dependency resolves the user from a trusted dev
mechanism: a signed `X-Dev-User` header / API key mapping to a seeded `users`
row (a single seeded default user if unset). Returns the `User`. The OAuth
`state` binds to this id. Real sign-in is the deferred sub-project; `identity.py`
is the seam it will later replace.

### API surface — `routes/account_routes.py`

Deliberately minimal:

- `GET /accounts` — current user's connection(s) + accessible customers.
- `POST /accounts/{connection_id}/select` `{customer_id}` — set the active
  customer for the connection.
- `GET /accounts/{connection_id}/summary` — the **proof-of-life**. Binds a
  `WebCredentialProvider` to the `contextvar` and calls one existing read path (a
  small GAQL account summary via `gads_client`) for the selected customer,
  returning JSON. This single endpoint exercises the whole seam end-to-end:
  identity → DB token → provider → `build_client` → API. It is also the vehicle
  for the cross-tenant isolation test.

All connection-scoped routes enforce that `connection.user_id == current_user.id`
before acting (IDOR protection), returning `404` on mismatch.

## Config — `config.py`

Typed settings from env / secret manager; nothing secret in git. Fail fast at
startup on missing required values.

- `DATABASE_URL`
- `FERNET_KEYS` — ordered keyring, current key first
- `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` — app Web client
- `GOOGLE_DEVELOPER_TOKEN` — app-owned
- `OAUTH_REDIRECT_URI`
- `DEV_USER` — identity-stub toggle / seeded user key

## Error handling

- OAuth: invalid / expired / missing / non-owned `state` → `400`; token-exchange
  failure → `502` with a sanitized message (never echo Google's raw error or any
  token).
- Credential resolution: a dead / revoked refresh token surfaces as a typed
  `ConnectionAuthError` → `409` instructing the client to reconnect (the
  per-connection analogue of the CLI's `AuthRequiredError`, with no 24h cap).
- Authorization: IDOR checks return `404` (not `403`, to avoid confirming
  existence).
- Secrets hygiene: refresh tokens and client secrets are never logged; structured
  logs carry `user_id` / `connection_id` only.

## Testing

- **Unit**
  - `crypto` round-trip + key rotation: encrypt under v1, rotate keyring,
    confirm v1 rows still decrypt and re-encrypt to v2.
  - `DbTokenStore` get/set run against the **same `TokenStore` contract tests** as
    `LocalFileTokenStore`.
  - `WebCredentialProvider` composes the correct record for `OAuthClientBackend`
    (Google refresh mocked, as in 0.6.0).
- **Integration** (FastAPI `TestClient`, DB fixture)
  - OAuth start → callback with Google mocked: asserts the encrypted token is
    persisted, the `oauth_states` row is consumed exactly once, and replay of the
    same callback is rejected.
  - **Cross-tenant isolation:** user B calling user A's `connection_id` gets
    `404`; concurrent requests resolve their own tokens (the `contextvar`
    isolation guarantee); the `contextvar` is reset after each request.
- **CLI regression:** the existing 154-test suite stays green — `build_client()`
  going through the default provider must not change CLI behavior.

## Risks and open questions

- **Test database engine.** SQLite is zero-setup but `jsonb` / `bytea` and some
  concurrency semantics differ from Postgres. Resolve in the plan: SQLite-
  compatible column types vs. a test Postgres (testcontainers / service). Leaning
  test-Postgres to avoid behavior gaps on the exact features used.
- **`login_customer_id` under app-owned token.** When a user's customer sits
  under their own MCC, the call may need `login_customer_id`. The flow stores it
  on the connection when known; the resolution rule is finalized in the plan.
- **`contextvar` under threadpool.** Some scripts run sync / parallel
  (`concurrent.futures`). Confirm the bound provider propagates correctly (or is
  re-bound) when work crosses threads; covered by the isolation test.
- **Google standard access.** The app-owned developer token needs standard access
  to call many accounts at scale — an operational dependency, not code.

## Forward context (not built here)

This slice is items 1–3 of the decomposition. It deliberately leaves the seams
for the next sub-projects: `identity.py` is replaced by real app auth; the single
`/summary` endpoint generalizes into the full read-path API; `connections`
extends to many-per-user; a dashboard consumes the API. See the vault note
`projects/Google Ads Agents/Roadmap.md`.
