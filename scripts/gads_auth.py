"""
Google Ads auth.

End-user Google sign-in. The default path uses the gcloud CLI (no service
account, no per-user OAuth client registration): the gcloud CLI is itself a
registered Google application, so this is a real SSO browser flow. Restricted
Workspaces can instead use their own OAuth client via --oauth-login.

A developer token is still required by the Google Ads API. It is one-time
account setup, not OAuth, so users paste it once. login-customer-id (MCC)
is optional.

A 24-hour session cap is enforced locally on top of whatever token expiry
Google issues. After 24h the scripts refuse to run until the user signs in
again. This is intentional and not configurable.

Usage:
  python scripts/gads_auth.py --check
  python scripts/gads_auth.py --adc                 # print gcloud command
  python scripts/gads_auth.py --set-developer-token TOKEN
  python scripts/gads_auth.py --set-login-customer-id 1234567890
  python scripts/gads_auth.py --customers           # list accessible customers
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ADWORDS = "https://www.googleapis.com/auth/adwords"
CLOUD_PLATFORM = "https://www.googleapis.com/auth/cloud-platform"
OPENID = "openid"
EMAIL = "email"

CREDENTIALS_PATH = Path.home() / ".claude" / "gads-credentials.json"
SESSION_PATH = Path.home() / ".claude" / "gads-session.json"
SESSION_MAX_HOURS = 24
REVOKE_URI = "https://oauth2.googleapis.com/revoke"


class AuthRequiredError(RuntimeError):
    def __init__(self, hint: str):
        super().__init__(hint)
        self.hint = hint


class SessionExpiredError(RuntimeError):
    pass


def adc_command() -> str:
    return (
        "gcloud auth application-default login --scopes="
        + ",".join([ADWORDS, CLOUD_PLATFORM, OPENID, EMAIL])
    )


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _save(path: Path, data: dict[str, Any]) -> None:
    _ensure_dir(path)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except (PermissionError, OSError):
        pass


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_credentials() -> dict[str, Any]:
    return _load(CREDENTIALS_PATH) or {}


def save_credentials(data: dict[str, Any]) -> None:
    _save(CREDENTIALS_PATH, data)


# ---------- 24h session marker ----------

def session_start() -> None:
    _save(SESSION_PATH, {"started_at": datetime.now(timezone.utc).isoformat()})


def session_status() -> dict[str, Any]:
    s = _load(SESSION_PATH)
    if not s:
        return {"valid": False, "remaining_seconds": 0, "reason": "no session"}
    started = datetime.fromisoformat(s["started_at"])
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - started
    remaining = timedelta(hours=SESSION_MAX_HOURS) - elapsed
    if remaining.total_seconds() <= 0:
        return {"valid": False, "remaining_seconds": 0, "reason": "expired"}
    return {
        "valid": True,
        "remaining_seconds": int(remaining.total_seconds()),
        "started_at": s["started_at"],
    }


def enforce_session() -> None:
    s = session_status()
    if not s["valid"]:
        method = (active_profile() or {}).get("auth_method", "gcloud_adc")
        if method == "oauth_client":
            reauth = "python scripts/gads_auth.py --oauth-login --client-secrets client_secret.json"
        else:
            reauth = adc_command()
        raise SessionExpiredError(
            "Session expired (24h cap reached). Re-authenticate:\n  " + reauth
        )


# ---------- google.auth resolution ----------

def get_credentials():
    """Resolve credentials for the active profile's backend, after the 24h cap.

    gcloud_adc profiles use google.auth.default(); oauth_client profiles build
    Credentials from a stored refresh token. Selection lives in gads_authflow.
    """
    enforce_session()
    import gads_authflow

    name = active_profile_name()
    profile = active_profile()
    backend = gads_authflow.select_backend(name, profile)
    try:
        return backend.credentials()
    except AuthRequiredError:
        raise
    except Exception as e:
        method = (profile or {}).get("auth_method", "gcloud_adc")
        if method == "oauth_client":
            hint = (
                f"OAuth client credentials for profile '{name}' failed to refresh "
                f"({e}). Re-run:\n  python scripts/gads_auth.py --oauth-login "
                f"--client-secrets client_secret.json"
            )
        else:
            hint = f"No application default credentials found ({e}).\nRun:\n  {adc_command()}"
        raise AuthRequiredError(hint) from e


# ---------- developer token + login-customer-id ----------

# ---------- profiles ----------
#
# Credentials file layout:
#   { "active": "<name>",
#     "profiles": {
#       "<name>": {"developer_token": "...", "login_customer_id": "..."}
#     }
#   }
#
# Old flat layout ({"developer_token": "...", "login_customer_id": "..."}) is
# auto-migrated into a "default" profile on first read.

def _migrate_if_flat(data: dict[str, Any]) -> dict[str, Any]:
    if "profiles" in data:
        return data
    if not data:
        return {"active": None, "profiles": {}}
    migrated = {
        "active": "default",
        "profiles": {
            "default": {
                "developer_token": data.get("developer_token"),
                "login_customer_id": data.get("login_customer_id"),
            }
        },
    }
    save_credentials(migrated)
    return migrated


def _profiles() -> dict[str, Any]:
    return _migrate_if_flat(load_credentials())


def active_profile_name() -> str | None:
    return _profiles().get("active")


def active_profile() -> dict[str, Any]:
    data = _profiles()
    name = data.get("active")
    if not name:
        return {}
    return data.get("profiles", {}).get(name, {})


def get_developer_token() -> str:
    env = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if env:
        return env
    token = active_profile().get("developer_token")
    if not token:
        raise AuthRequiredError(
            "No developer token configured for the active profile. Run:\n"
            "  python scripts/gads_auth.py --add-profile <NAME> --developer-token <TOKEN> [--login-customer-id <MCC>]\n"
            "  python scripts/gads_auth.py --use-profile <NAME>"
        )
    return token


def get_login_customer_id() -> str | None:
    env = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if env:
        return env.replace("-", "")
    return active_profile().get("login_customer_id")


def add_profile(name: str, developer_token: str, login_customer_id: str | None = None) -> None:
    data = _profiles()
    data.setdefault("profiles", {})[name] = {
        "developer_token": developer_token.strip(),
        "login_customer_id": (login_customer_id or "").replace("-", "").strip() or None,
    }
    if not data.get("active"):
        data["active"] = name
    save_credentials(data)


def use_profile(name: str) -> None:
    data = _profiles()
    if name not in data.get("profiles", {}):
        raise AuthRequiredError(
            f"Profile '{name}' not found. Add it first:\n"
            f"  python scripts/gads_auth.py --add-profile {name} --developer-token <TOKEN>"
        )
    data["active"] = name
    save_credentials(data)


def remove_profile(name: str) -> None:
    data = _profiles()
    data.get("profiles", {}).pop(name, None)
    if data.get("active") == name:
        remaining = list(data.get("profiles", {}).keys())
        data["active"] = remaining[0] if remaining else None
    save_credentials(data)


def list_profiles() -> dict[str, Any]:
    data = _profiles()
    return {
        "active": data.get("active"),
        "profiles": {
            name: {
                "developer_token": "set" if p.get("developer_token") else "missing",
                "login_customer_id": p.get("login_customer_id"),
            }
            for name, p in data.get("profiles", {}).items()
        },
    }


# kept for back-compat: writes to the active profile (or 'default' if none)
def set_developer_token(token: str) -> None:
    data = _profiles()
    name = data.get("active") or "default"
    data.setdefault("profiles", {}).setdefault(name, {})["developer_token"] = token.strip()
    data["active"] = name
    save_credentials(data)


def set_login_customer_id(customer_id: str) -> None:
    data = _profiles()
    name = data.get("active") or "default"
    data.setdefault("profiles", {}).setdefault(name, {})["login_customer_id"] = (
        customer_id.replace("-", "").strip()
    )
    data["active"] = name
    save_credentials(data)


def set_auth_method(name: str, method: str) -> None:
    data = _profiles()
    data.setdefault("profiles", {}).setdefault(name, {})["auth_method"] = method
    if not data.get("active"):
        data["active"] = name
    save_credentials(data)


def set_oauth_credentials(
    name: str, client_id: str, client_secret: str, refresh_token: str
) -> None:
    """Persist OAuth client material and flip the profile to oauth_client."""
    from gads_tokenstore import LocalFileTokenStore

    LocalFileTokenStore().set(name, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    set_auth_method(name, "oauth_client")


# ---------- CLI ----------

def cmd_check(_args) -> int:
    out: dict[str, Any] = {}
    try:
        creds = get_credentials()
        out["adc"] = "ok"
        out["principal"] = getattr(creds, "service_account_email", None) or "user"
    except SessionExpiredError as e:
        out["session"] = "expired"
        out["hint"] = str(e)
        print(json.dumps(out, indent=2))
        return 1
    except AuthRequiredError as e:
        out["adc"] = "missing"
        out["hint"] = e.hint
        print(json.dumps(out, indent=2))
        return 1

    out["session"] = session_status()
    out["active_profile"] = active_profile_name()
    out["developer_token"] = "set" if active_profile().get("developer_token") else "missing"
    out["login_customer_id"] = get_login_customer_id() or None
    print(json.dumps(out, indent=2))
    return 0


def cmd_adc(_args) -> int:
    print(adc_command())
    return 0


def cmd_set_dev_token(args) -> int:
    set_developer_token(args.set_developer_token)
    session_start()
    print(json.dumps({"developer_token": "set", "session": session_status()}, indent=2))
    return 0


def cmd_set_login_customer_id(args) -> int:
    set_login_customer_id(args.set_login_customer_id)
    print(json.dumps({"login_customer_id": get_login_customer_id()}, indent=2))
    return 0


def cmd_customers(_args) -> int:
    from gads_client import build_client

    client = build_client()
    service = client.get_service("CustomerService")
    resource_names = service.list_accessible_customers().resource_names
    print(json.dumps({"customers": [r.split("/")[-1] for r in resource_names]}, indent=2))
    return 0


def revoke_refresh_token(token: str) -> bool:
    """Revoke a refresh token at Google. True when Google confirmed."""
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({"token": token}).encode()
    with urllib.request.urlopen(REVOKE_URI, data=data, timeout=10) as resp:
        return resp.status == 200


def cmd_logout(_args) -> int:
    revoked: dict[str, bool] = {}
    for name, prof in _profiles().get("profiles", {}).items():
        token = prof.get("refresh_token")
        if not token:
            continue
        try:
            revoked[name] = revoke_refresh_token(token)
        except Exception:
            revoked[name] = False
    for p in (CREDENTIALS_PATH, SESSION_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    print(json.dumps({"status": "cleared", "revoked": revoked}, indent=2))
    return 0


def cmd_add_profile(args) -> int:
    if not args.developer_token:
        print(json.dumps({"error": "--developer-token is required with --add-profile"}, indent=2))
        return 2
    add_profile(args.add_profile, args.developer_token, args.login_customer_id)
    session_start()
    print(json.dumps({"added": args.add_profile, "profiles": list_profiles()}, indent=2))
    return 0


def cmd_use_profile(args) -> int:
    use_profile(args.use_profile)
    session_start()
    print(json.dumps({"active": active_profile_name(), "profiles": list_profiles()}, indent=2))
    return 0


def cmd_remove_profile(args) -> int:
    remove_profile(args.remove_profile)
    print(json.dumps(list_profiles(), indent=2))
    return 0


def cmd_list_profiles(_args) -> int:
    print(json.dumps(list_profiles(), indent=2))
    return 0


def cmd_oauth_login(args) -> int:
    name = args.add_profile or active_profile_name()
    if not name:
        print(json.dumps({
            "error": "no profile. Pass --add-profile NAME --developer-token TOKEN, "
                     "or select an existing profile with --use-profile first."
        }, indent=2))
        return 2
    if args.add_profile:
        if not args.developer_token:
            print(json.dumps(
                {"error": "--developer-token is required with --add-profile"}, indent=2
            ))
            return 2
        add_profile(args.add_profile, args.developer_token, args.login_customer_id)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, scopes=[ADWORDS])
    creds = flow.run_local_server(port=0, open_browser=not args.no_browser)
    set_oauth_credentials(name, creds.client_id, creds.client_secret, creds.refresh_token)
    session_start()
    print(json.dumps({
        "profile": name,
        "auth_method": "oauth_client",
        "refresh_token": "set",
        "session": session_status(),
    }, indent=2))
    return 0


def cmd_set_oauth(args) -> int:
    """Manual fallback: store a pre-obtained client id/secret/refresh token."""
    if not (args.client_id and args.client_secret and args.refresh_token):
        print(json.dumps({
            "error": "--set-oauth needs --client-id, --client-secret, --refresh-token"
        }, indent=2))
        return 2
    set_oauth_credentials(args.set_oauth, args.client_id, args.client_secret, args.refresh_token)
    session_start()
    print(json.dumps({
        "profile": args.set_oauth,
        "auth_method": "oauth_client",
        "refresh_token": "set",
    }, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true")
    p.add_argument("--adc", action="store_true")
    p.add_argument("--add-profile", metavar="NAME")
    p.add_argument("--use-profile", metavar="NAME")
    p.add_argument("--remove-profile", metavar="NAME")
    p.add_argument("--list-profiles", action="store_true")
    p.add_argument("--developer-token", metavar="TOKEN", help="paired with --add-profile")
    p.add_argument("--login-customer-id", metavar="ID", help="paired with --add-profile (optional)")
    p.add_argument("--set-developer-token", metavar="TOKEN", help="set on the active profile")
    p.add_argument("--set-login-customer-id", metavar="ID", help="set on the active profile")
    p.add_argument("--oauth-login", action="store_true",
                   help="run the OAuth loopback flow with your own client")
    p.add_argument("--client-secrets", metavar="PATH",
                   help="client_secret.json from your Desktop OAuth client")
    p.add_argument("--no-browser", action="store_true",
                   help="print the URL instead of opening a browser")
    p.add_argument("--set-oauth", metavar="NAME",
                   help="manual fallback: set OAuth material on a profile")
    p.add_argument("--client-id", metavar="ID", help="paired with --set-oauth")
    p.add_argument("--client-secret", metavar="SECRET", help="paired with --set-oauth")
    p.add_argument("--refresh-token", metavar="TOKEN", help="paired with --set-oauth")
    p.add_argument("--customers", action="store_true")
    p.add_argument("--logout", action="store_true")
    args = p.parse_args()

    if args.check:
        return cmd_check(args)
    if args.adc:
        return cmd_adc(args)
    if args.oauth_login:
        return cmd_oauth_login(args)
    if args.set_oauth:
        return cmd_set_oauth(args)
    if args.add_profile:
        return cmd_add_profile(args)
    if args.use_profile:
        return cmd_use_profile(args)
    if args.remove_profile:
        return cmd_remove_profile(args)
    if args.list_profiles:
        return cmd_list_profiles(args)
    if args.set_developer_token:
        return cmd_set_dev_token(args)
    if args.set_login_customer_id:
        return cmd_set_login_customer_id(args)
    if args.customers:
        return cmd_customers(args)
    if args.logout:
        return cmd_logout(args)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
