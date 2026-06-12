# Web app sign-in — design

## Problem

The webapp resolves the current user from a client-supplied `X-Dev-User`
header — the identity stub from the foundation slice. Anyone who can reach
the app can impersonate any user, list their connections, and run reads with
their stored refresh tokens. Real sign-in replaces the stub. Until this slice
ships, the app must only bind to localhost.

## Decisions (from brainstorming)

- **Google Sign-In only** (OIDC). No passwords to store, hash, or reset.
  Every user already authenticates a Google account for Ads access, so
  Google is the identity anchor.
- **Configurable allowlist**: a settings list matching email domains or full
  emails (e.g. `["goodlabs.kz", "dilshatrakhimov@gmail.com"]`). Empty list =
  open signup.
- **24-hour absolute sessions**, matching the CLI's intentional 24h cap.
  No sliding renewal.
- **DB-backed sessions** with an opaque token in an HttpOnly cookie
  (chosen over Authlib signed cookies and JWT): server-side revocation
  works instantly, and the flow reuses the already-tested PKCE / state /
  ID-token plumbing in `app/oauth.py` with zero new dependencies.

## Scope

Sign-in flow, session storage, request authentication, logout, a `/me`
probe endpoint, the allowlist, and the CSRF posture. The `X-Dev-User`
header and the `dev_user_id` setting are deleted.

## Out of scope

- Frontend UI (the callback returns JSON; a future dashboard changes it
  to a redirect).
- Sliding sessions, "remember me", MFA.
- Rate limiting and security headers (separate operational slice).
- Alembic migrations (separate slice; dev still uses `create_all`).
- Account linking beyond `google_sub` (no merging of pre-existing rows).

## Architecture

### Module layout

```
webapp/app/
  sessions.py          # NEW: mint / lookup / delete session tokens
  identity.py          # REWRITTEN: cookie -> session -> user; 401 otherwise
  routes/
    signin_routes.py   # NEW: GET /auth/google/start,
                       #      GET /auth/google/callback,
                       #      POST /auth/logout, GET /me
```

`app/oauth.py` is reused unchanged: `make_pkce`, `new_state`,
`exchange_code`, `verify_id_token`.

### Data model

- `sessions` (new): `id` (uuid pk), `token_hash` (sha256 hex, unique),
  `user_id` FK, `created_at`, `expires_at`. Only the hash is stored, so a
  database dump cannot impersonate users.
- `users`: add `google_sub` (unique, nullable) — the stable Google subject.
  `email` is refreshed from the verified ID token at every sign-in.
- `oauth_states`: add `purpose` (`'signin' | 'connect'`); `user_id` becomes
  nullable because sign-in starts with no user. Connect states stay
  user-bound exactly as today.

### Settings

- `allowed_signins: list[str] = []` — entries containing `@` match the
  full email; entries without `@` match the email's domain (the part after
  `@`) exactly, no subdomains. Case-insensitive. Empty list allows anyone.
- `signin_redirect_uri: str` — registered for `/auth/google/callback`.
- `session_max_hours: int = 24`.
- `cookie_secure: bool = True` — set `False` only for local http dev.
- `dev_user_id` — removed.

### Sign-in flow

1. `GET /auth/google/start`: mint PKCE + state (`purpose='signin'`,
   `user_id` NULL), redirect to Google. Scopes `openid email` only — no
   `adwords`, no `access_type=offline`, no forced consent. Signing in
   never asks for Ads access; connecting an Ads account stays a separate,
   heavier consent.
2. `GET /auth/google/callback`: consume the state row (single-use, TTL,
   `purpose` must be `signin`); handle the `error` param; exchange the code
   with PKCE; verify the ID token (signature, audience, expiry).
3. Reject unverified emails (403). If `allowed_signins` is non-empty, the
   verified email must match a listed domain or full email, else 403.
4. Upsert the user by `google_sub`: create with `email` + `google_sub` when
   absent, refresh `email` when changed.
5. Mint a 32-byte urlsafe token, store its sha256,
   `expires_at = now + session_max_hours`. Set cookie
   `gads_session=<token>; HttpOnly; SameSite=Lax; Max-Age=<sec>; Path=/`,
   plus `Secure` when `cookie_secure` is true.
6. Respond `{"user": {"id", "email"}, "expires_at"}`.

### Request authentication

`get_current_user`: read the cookie, hash it, look up an unexpired session,
return its user; otherwise 401 `"not signed in"`. Expired session rows are
deleted lazily on hit. All existing route signatures are unchanged; the
connect flow (`/oauth/google/start` + callback) now requires a session and
keeps its user-bound state validation.

### CSRF

`SameSite=Lax` on the session cookie is the primary cross-site defense.
On top, methods other than GET / HEAD / OPTIONS reject requests whose
`Origin` header is present but does not match the app origin, derived from
`signin_redirect_uri` (scheme + host + port). Requests without an `Origin`
header (curl, server-to-server) pass — the cookie requirement still gates
them.

### Logout

`POST /auth/logout`: delete the session row (instant server-side
revocation), clear the cookie, 200. Does not touch Ads connections —
revoking those is `/accounts/{id}/disconnect`.

### /me

`GET /me` returns `{"id", "email"}` for the signed-in user. Gives the
future frontend a cheap session probe.

## Error handling

- 401 `"not signed in"` — missing, unknown, or expired session cookie.
- 403 `"email not allowed"` — allowlist rejection.
- 403 `"email not verified"` — `email_verified` false in the ID token.
- Callback taxonomy mirrors the connect flow: 400 invalid or expired
  state, 400 `authorization failed: <error>`, 400 missing code, 502 token
  exchange failed, 502 missing or invalid ID token.

## Testing

- Unit, `sessions.py`: mint/lookup round-trip, expiry boundary, lookup
  deletes expired rows, logout delete.
- Unit, allowlist matcher: domain match, full-email match, empty list
  allows, case-insensitivity, non-matching rejected.
- API, sign-in: full mocked flow sets the cookie and creates the user;
  repeat sign-in with the same `sub` reuses the user and refreshes a
  changed email; allowlist 403; unverified email 403; state replay 400.
- API, sessions: protected routes 401 without a cookie; expired session
  401; logout then 401.
- Existing isolation tests are rewritten to use two real sessions (a test
  helper mints user + session + cookie directly in the DB) instead of
  `X-Dev-User` headers.

## Migration notes

Dev databases bootstrap via `create_all`, which creates the new table and
columns only on fresh databases; recreate dev DBs after this slice. No
production deployments exist yet; the production schema path is the
deferred Alembic slice.
