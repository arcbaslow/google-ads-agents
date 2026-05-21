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

From the project directory:

```
python scripts/gads_auth.py --adc
```

It prints the exact `gcloud auth application-default login --scopes=...`
command. Run it. A browser opens, sign in, grant access.

## 4. Configure local credentials

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
