"""Read-only Google Ads tools for an MCP host.

register() adds six tools to a host FastMCP; main() serves them alone over
stdio. The tools only call GoogleAdsService search, CustomerService
list_accessible_customers and GoogleAdsFieldService search; none of them can
change an account. Each call binds a credential provider for its duration:
the host's provider_factory(profile), or the active local profile. The
`profile` argument every tool exposes is consumed by that binding.
"""

from __future__ import annotations

import concurrent.futures
import functools
import inspect
import itertools
import logging
import os
import re
from collections.abc import Callable
from contextvars import copy_context
from pathlib import Path
from typing import Any, Literal

import gads_provider

log = logging.getLogger(__name__)

_HINTS = {
    "auth_required": (
        "Google credentials are missing, expired or revoked. Re-authenticate this profile "
        "(local toolkit: python scripts/gads_auth.py --check)."
    ),
    "permission_denied": (
        "These credentials cannot read the account. Check the user's access to the customer "
        "and the profile's manager account (login-customer-id)."
    ),
    "quota_exceeded": "Google Ads API quota or rate limit reached. Retry later or narrow the request.",
    "invalid_argument": (
        "Google Ads rejected the request. Check the customer ID, the query and the field names "
        "(resource_metadata lists them)."
    ),
    "not_found": "The customer or resource was not found or is not accessible with this profile.",
    "upstream_error": "The Google Ads API request failed. Retry later.",
}

_GOOGLE_ADS_ERRORS = (
    ("authentication_error", "auth_required"),
    ("authorization_error", "permission_denied"),
    ("quota_error", "quota_exceeded"),
    ("internal_error", "upstream_error"),
    ("request_error.RESOURCE_NOT_FOUND", "not_found"),
)

_SECRET_TEXT = re.compile(
    r"ya29\.[\w.-]+|1//[\w.-]+|GOCSPX-[\w-]+"
    r"|\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{20,}"
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
)

_GAQL_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_GAQL_CHARS = re.compile(r"[A-Za-z0-9_\s.,()=!<>'\"-]*")
_GAQL_LIMIT = re.compile(r"\s+LIMIT\s+([1-9][0-9]*)\s*$", re.IGNORECASE)
_GAQL_HINT = (
    "Pass one GAQL statement: SELECT <fields> FROM <resource>, optionally WHERE, ORDER BY and "
    "one trailing LIMIT n, with no PARAMETERS, comments or semicolons; rows are also bounded "
    "by the limit argument."
)

_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")
_FIELD_COLUMNS = "name, category, data_type, selectable, filterable, sortable, is_repeated"
_FIELD_LISTS = ("enum_values", "selectable_with", "attribute_resources", "metrics", "segments")

_ACCOUNTS_QUERY = """
    SELECT customer_client.id, customer_client.descriptive_name, customer_client.level,
      customer_client.manager, customer_client.currency_code, customer_client.time_zone,
      customer_client.status
    FROM customer_client
    ORDER BY customer_client.level, customer_client.id
    LIMIT {limit}
"""

_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_AUDIT_WORKERS = 4
# gads_history.CHANGE_QUERY ends with LIMIT 500, so a full page may hide older events.
_HISTORY_QUERY_CAP = 500


class _Failure(Exception):
    """A refusal that already carries a contract category and a client-safe hint."""

    def __init__(self, category: str, hint: str):
        super().__init__(hint)
        self.category = category
        self.hint = hint


def _scrub(text: str) -> str:
    return _SECRET_TEXT.sub("[redacted]", text)[:500]


def _customer_id(value: str) -> str:
    cid = str(value).replace("-", "").strip()
    if not re.fullmatch(r"[0-9]{10}", cid):
        raise _Failure("invalid_argument", "customer_id must be a 10-digit Google Ads customer ID.")
    return cid


def _bounded(name: str, value, low, high):
    numeric = int if isinstance(low, int) and isinstance(high, int) else (int, float)
    if isinstance(value, bool) or not isinstance(value, numeric) or not low <= value <= high:
        raise _Failure("invalid_argument", f"{name} must be between {low} and {high}.")
    return value


# ---------- tools ----------

def list_accounts(limit: int = 200, profile: str | None = None) -> dict[str, Any]:
    """List Google Ads accounts (customer IDs, names, currency, time zone, status) reachable
    under the profile's manager account (MCC), manager first. When the profile has no manager
    account, lists the customer IDs the credentials can access directly. `limit` defaults to
    200, maximum 500.
    """
    import gads_client

    limit = _bounded("limit", limit, 1, 500)
    manager = gads_provider.get_active_provider().get_login_customer_id()
    if manager:
        manager = str(manager).replace("-", "")
        rows = gads_client.search_stream(manager, _ACCOUNTS_QUERY.format(limit=limit + 1))
        accounts = []
        for row in rows[:limit]:
            client = row.get("customer_client", {})
            accounts.append({
                "id": client.get("id"),
                "name": client.get("descriptive_name"),
                "level": int(client.get("level", 0)),
                "manager": client.get("manager", False),
                "currency": client.get("currency_code"),
                "time_zone": client.get("time_zone"),
                "status": client.get("status"),
            })
    else:
        import gads_audit

        rows = sorted(gads_audit.list_all_customers())
        accounts = [{"id": cid} for cid in rows[:limit]]
    return {
        "profile": profile,
        "manager": manager or None,
        "accounts": accounts,
        "rows_returned": len(accounts),
        "complete": len(rows) <= limit,
    }


def run_gaql(
    customer_id: str, query: str, limit: int = 100, profile: str | None = None
) -> dict[str, Any]:
    """Run one read-only Google Ads Query Language (GAQL) SELECT query for a customer ID and
    return the rows. Pass a single
    `SELECT <fields> FROM <resource> [WHERE ...] [ORDER BY ...] [LIMIT n]` statement without
    PARAMETERS, comments or semicolons. Rows are bounded by the smaller of the query's LIMIT and
    `limit` (default 100, maximum 500). Use resource_metadata to discover fields.
    """
    import gads_export

    cid = _customer_id(customer_id)
    limit = _bounded("limit", limit, 1, 500)
    # Same-length masking keeps match positions valid in the original query.
    masked = _GAQL_STRING.sub(lambda m: "'" + " " * (len(m.group()) - 2) + "'", query)
    if not _GAQL_CHARS.fullmatch(masked):
        raise _Failure("invalid_argument", "The query contains characters outside GAQL. " + _GAQL_HINT)
    trailing = _GAQL_LIMIT.search(masked)
    if trailing:
        # query_rows appends its own LIMIT, so the caller's clause becomes the row bound.
        query = query[:trailing.start()]
        limit = min(limit, int(trailing.group(1)))
    try:
        result = gads_export.query_rows(cid, query, limit)
    except ValueError as exc:
        raise _Failure("invalid_argument", f"{_scrub(str(exc))}. {_GAQL_HINT}") from None
    return {
        "customer_id": cid,
        "rows": result["rows"],
        "rows_returned": len(result["rows"]),
        "complete": not result["truncated"],
    }


def resource_metadata(
    name: str | None = None, detail: bool = False, limit: int = 200, profile: str | None = None
) -> dict[str, Any]:
    """Look up Google Ads API field metadata for writing GAQL: resources, fields, and whether
    each field is selectable, filterable or sortable. No `name` lists every resource. A
    resource or field prefix (`campaign`, `metrics`, `segments`, `ad_group_criterion.keyword`)
    lists the fields under it. `detail=true` with an exact resource or field name returns its
    enum values and the resources, metrics and segments it can be selected with. `limit`
    (default 200, maximum 500) bounds fields and each detail list.
    """
    import gads_client

    limit = _bounded("limit", limit, 1, 500)
    if name is not None and not _FIELD_NAME.fullmatch(name):
        raise _Failure("invalid_argument", "name must be a lowercase GAQL resource or field name.")
    if detail:
        if name is None:
            raise _Failure("invalid_argument", "detail=true needs a resource or field name.")
        query = f"SELECT {_FIELD_COLUMNS}, {', '.join(_FIELD_LISTS)} WHERE name = '{name}'"
    elif name is None:
        query = f"SELECT {_FIELD_COLUMNS} WHERE category = 'RESOURCE' ORDER BY name"
    else:
        query = f"SELECT {_FIELD_COLUMNS} WHERE name LIKE '{name}.%' ORDER BY name"

    service = gads_client.build_client().get_service("GoogleAdsFieldService")
    pager = service.search_google_ads_fields(request={"query": query, "page_size": limit})
    fields = []
    complete = True
    for field in itertools.islice(pager, limit):
        info = {
            "name": field.name,
            "category": field.category.name,
            "data_type": field.data_type.name,
            "selectable": field.selectable,
            "filterable": field.filterable,
            "sortable": field.sortable,
            "is_repeated": field.is_repeated,
        }
        if detail:
            for key in _FIELD_LISTS:
                values = list(getattr(field, key))
                info[key] = values[:limit]
                info[key + "_total"] = len(values)
                complete = complete and len(values) <= limit
        fields.append(info)
    if detail and not fields:
        raise _Failure("not_found", f"No resource or field named {name!r}. Call without detail to list names.")
    return {
        "name": name,
        "fields": fields,
        "rows_returned": len(fields),
        "complete": complete and pager.total_results_count <= limit,
    }


def account_audit(
    customer_id: str, days: int = 28, limit: int = 50, profile: str | None = None
) -> dict[str, Any]:
    """Audit a Google Ads account: run every read-only audit agent (conversion health, search,
    search terms, Performance Max, app, display, Demand Gen, shopping, YouTube, auction insights,
    placements, recommendations, bid strategy, pacing, quality score, demographics) over the
    last `days` (1-90) and return each agent's status and summary plus the top `limit`
    findings by severity (default 50, maximum 200). Raw agent data is not returned.
    """
    import gads_audit
    import gads_client
    import gads_findings
    import gads_utils

    cid = _customer_id(customer_id)
    days = _bounded("days", days, 1, 90)
    limit = _bounded("limit", limit, 1, 200)
    start, end = gads_utils.date_range(days)
    # Fail once with the real auth hint instead of sixteen times inside the agents.
    gads_client.build_client()

    def run_agent(name, fn):
        try:
            out = fn(cid, days)
        except Exception as exc:
            category = _classify(exc)[0]
            log.warning("account_audit agent %s failed: %s (%s)", name, category, type(exc).__name__)
            return {"status": "failed", "error": category}
        return out if isinstance(out, dict) else {"data": out}

    agents: dict[str, Any] = {}
    findings: list[dict] = []
    # gads_audit.run() is not reused: its failure path calls gads_errors.describe(),
    # which imports gads_mutate.
    with concurrent.futures.ThreadPoolExecutor(max_workers=_AUDIT_WORKERS) as pool:
        # Each worker needs its own copy of the context that holds the bound provider.
        futures = {
            pool.submit(copy_context().run, run_agent, name, fn): name
            for name, fn in gads_audit.DEFAULT_AGENTS
        }
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            out = future.result()
            found = gads_findings.collect({"agents": {name: out}})
            findings.extend(found)
            if out.get("status") == "failed":
                agents[name] = {"status": "failed", "error": out["error"]}
            else:
                agents[name] = {"status": "ok", "summary": out.get("summary"), "findings": len(found)}

    findings.sort(key=lambda f: (_SEVERITY.get(f.get("severity"), len(_SEVERITY)), f["agent"]))
    failed = sorted(name for name, agent in agents.items() if agent["status"] == "failed")
    return {
        "customer_id": cid,
        "date_range": {"start": start, "end": end},
        "agents": dict(sorted(agents.items())),
        "failed_agents": failed,
        "total_findings": len(findings),
        "findings": findings[:limit],
        "rows_returned": min(len(findings), limit),
        "complete": len(findings) <= limit and not failed,
    }


def anomalies_and_pacing(
    customer_id: str,
    check: Literal["both", "anomalies", "pacing"] = "both",
    days: int = 30,
    baseline_days: int | None = None,
    z_threshold: float = 2.0,
    limit: int = 50,
    profile: str | None = None,
) -> dict[str, Any]:
    """Detect day-level anomalies in campaign cost, clicks, impressions and conversions, and
    check month-to-date budget pacing (projected over- or under-spend) for enabled campaigns.
    `check` picks "anomalies", "pacing" or "both". Anomalies read the last `days` (2-90): the
    first `baseline_days` of that window (default min(14, days - 1), maximum 60) are warm-up
    only, and each later day is scored against the `baseline_days` before it, flagging
    |z| >= `z_threshold` (0.5-10), strongest first. Pacing ignores those three arguments. Each
    list returns at most `limit` items (default 50, maximum 200).
    """
    import gads_anomalies
    import gads_pacing

    cid = _customer_id(customer_id)
    limit = _bounded("limit", limit, 1, 200)
    if check not in ("both", "anomalies", "pacing"):
        raise _Failure("invalid_argument", 'check must be "anomalies", "pacing" or "both".')

    out: dict[str, Any] = {"customer_id": cid, "check": check}
    totals: list[int] = []
    returned = 0
    if check in ("both", "anomalies"):
        days = _bounded("days", days, 2, 90)
        if baseline_days is None:
            baseline_days = min(14, days - 1)
        baseline_days = _bounded("baseline_days", baseline_days, 1, min(60, days - 1))
        z_threshold = _bounded("z_threshold", z_threshold, 0.5, 10)
        result = gads_anomalies.detect(cid, days, z_threshold, baseline_days)
        items = sorted(result["anomalies"], key=lambda a: -abs(a["z_score"]))
        out["anomalies"] = {
            "date_range": result["date_range"],
            "baseline_days": baseline_days,
            "summary": result["summary"],
            "total": len(items),
            "items": items[:limit],
        }
        totals.append(len(items))
        returned += len(out["anomalies"]["items"])
    if check in ("both", "pacing"):
        result = gads_pacing.analyze(cid)
        campaigns = sorted(result["campaigns"], key=lambda c: -abs(c["delta_pct"]))
        out["pacing"] = {
            "as_of": result["as_of"],
            "days_elapsed": result["days_elapsed"],
            "days_in_month": result["days_in_month"],
            "summary": result["summary"],
            "total": len(campaigns),
            "campaigns": campaigns[:limit],
            "findings": result["findings"][:limit],
        }
        totals += [len(campaigns), len(result["findings"])]
        returned += len(out["pacing"]["campaigns"])
    out["rows_returned"] = returned
    out["complete"] = all(total <= limit for total in totals)
    return out


def change_history(
    customer_id: str, days: int = 7, limit: int = 50, profile: str | None = None
) -> dict[str, Any]:
    """Show recent Google Ads account changes from the change_event log: which campaigns, ad
    groups and other resources were created, updated or removed, when, through which client
    (UI, API, scripts), and by which actor domain over the last `days` (1-30), newest first.
    Actor emails are reduced to their domain. `limit` defaults to 50, maximum 200; the log
    query itself stops at 500 events.
    """
    import gads_history

    cid = _customer_id(customer_id)
    days = _bounded("days", days, 1, 30)
    limit = _bounded("limit", limit, 1, 200)
    result = gads_history.changes(cid, days)

    events = []
    by_actor: dict[str, int] = {}
    for row in result["events"]:
        event = dict(row.get("change_event", {}))
        email = event.pop("user_email", None)
        if email and "@" in email:
            event["user_domain"] = email.rpartition("@")[2]
        actor = event.get("user_domain") or event.get("client_type") or "unknown"
        by_actor[actor] = by_actor.get(actor, 0) + 1
        if len(events) < limit:
            events.append(event)
    return {
        "customer_id": cid,
        "date_range": result["date_range"],
        "total": result["total"],
        "by_actor": by_actor,
        "by_resource": result["by_resource"],
        "events": events,
        "rows_returned": len(events),
        "complete": result["total"] <= limit and result["total"] < _HISTORY_QUERY_CAP,
    }


TOOLS: tuple[tuple[str, str, Callable[..., dict[str, Any]]], ...] = (
    ("list_accounts", "List Google Ads accounts", list_accounts),
    ("run_gaql", "Run a GAQL query", run_gaql),
    ("resource_metadata", "Look up GAQL resources and fields", resource_metadata),
    ("account_audit", "Audit a Google Ads account", account_audit),
    ("anomalies_and_pacing", "Find anomalies and budget pacing", anomalies_and_pacing),
    ("change_history", "Show recent account changes", change_history),
)


# ---------- credentials and errors ----------

def credentials_present() -> bool:
    """True when the default file provider has something to authenticate with.

    Checks only that a credential file exists; never opens one and makes no
    network call, so the gcloud metadata server is never probed.
    """
    try:
        if (Path.home() / ".claude" / "gads-credentials.json").is_file():
            return True
        explicit = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if explicit and Path(explicit).is_file():
            return True
        # Same lookup order as google-auth uses for the gcloud configuration directory.
        config = os.environ.get("CLOUDSDK_CONFIG")
        if config:
            gcloud = Path(config)
        elif os.name == "nt":
            root = os.environ.get("APPDATA") or os.environ.get("SystemDrive", "C:") + "\\"
            gcloud = Path(root) / "gcloud"
        else:
            gcloud = Path.home() / ".config" / "gcloud"
        return (gcloud / "application_default_credentials.json").is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def _file_provider(profile: str | None):
    import gads_auth

    try:
        data = gads_auth.load_credentials()
    except ValueError:
        raise _Failure(
            "auth_required",
            "The local Google Ads credentials file is unreadable. Re-create the profile with "
            "python scripts/gads_auth.py --add-profile NAME.",
        ) from None
    if data and "profiles" not in data:
        # gads_auth migrates this legacy layout by rewriting the file on first read.
        raise _Failure(
            "auth_required",
            "The local credentials file uses the legacy flat layout. Run "
            "python scripts/gads_auth.py --check once to migrate it.",
        )
    if profile is not None and profile != data.get("active"):
        if profile not in data.get("profiles", {}):
            raise _Failure(
                "invalid_argument",
                "Unknown profile. List profiles with python scripts/gads_auth.py --list-profiles.",
            )
        raise _Failure(
            "invalid_argument",
            f"Profile {profile!r} is not the active local profile, and the local provider does "
            "not switch profiles. Omit profile, or switch locally with "
            f"python scripts/gads_auth.py --use-profile {profile}.",
        )
    return gads_provider.FileCredentialProvider()


def _classify(exc: Exception) -> tuple[str, str]:
    """Map an exception to a contract category and a hint without upstream text."""
    if isinstance(exc, _Failure):
        return exc.category, exc.hint

    import gads_auth
    import grpc
    from google.ads.googleads.errors import GoogleAdsException
    from google.api_core import exceptions as api_errors
    from google.auth import exceptions as auth_errors

    if isinstance(exc, (gads_auth.AuthRequiredError, gads_auth.SessionExpiredError)):
        return "auth_required", _scrub(str(exc))
    if isinstance(exc, auth_errors.RefreshError) and exc.retryable:
        return "upstream_error", _HINTS["upstream_error"]
    if isinstance(exc, (auth_errors.RefreshError, auth_errors.DefaultCredentialsError)):
        return "auth_required", _HINTS["auth_required"]
    if isinstance(exc, GoogleAdsException):
        # Error messages and field paths can echo submitted data; only the codes are read.
        codes = set()
        for error in exc.failure.errors:
            kind = error.error_code._pb.WhichOneof("error_code")
            if kind:
                codes |= {kind, f"{kind}.{getattr(getattr(error.error_code, kind), 'name', '')}"}
        for code, category in _GOOGLE_ADS_ERRORS:
            if code in codes:
                return category, _HINTS[category]
        return "invalid_argument", _HINTS["invalid_argument"]
    if isinstance(exc, grpc.RpcError):
        exc = api_errors.from_grpc_error(exc)
    if isinstance(exc, api_errors.GoogleAPICallError):
        # gRPC reports a failed token refresh inside its auth plugin as UNAVAILABLE.
        message = str(exc).lower()
        if "reauthentication is needed" in message or "invalid_grant" in message:
            return "auth_required", _HINTS["auth_required"]
        for cls, category in (
            (api_errors.Unauthorized, "auth_required"),
            (api_errors.Forbidden, "permission_denied"),
            (api_errors.TooManyRequests, "quota_exceeded"),
            (api_errors.NotFound, "not_found"),
            (api_errors.BadRequest, "invalid_argument"),
        ):
            if isinstance(exc, cls):
                return category, _HINTS[category]
    elif isinstance(exc, ValueError):
        return "invalid_argument", "Check the supplied arguments."
    return "upstream_error", _HINTS["upstream_error"]


def _guarded(fn: Callable[..., dict[str, Any]], provider_factory) -> Callable[..., dict[str, Any]]:
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def tool(*args, **kwargs):
        try:
            profile = signature.bind(*args, **kwargs).arguments.get("profile")
            provider = provider_factory(profile) if provider_factory else _file_provider(profile)
            if provider is None:
                # Binding None would silently fall back to the local file provider.
                raise _Failure("invalid_argument", "Unknown profile for this server.")
            with gads_provider.bind_provider(provider):
                return fn(*args, **kwargs)
        except Exception as exc:
            category, hint = _classify(exc)
            log.warning("%s failed: %s (%s)", fn.__name__, category, type(exc).__name__)
            return {"error": category, "hint": hint}

    return tool


# ---------- MCP ----------

def register(server, prefix: str = "", provider_factory=None) -> int:
    """Add every tool in TOOLS to a host FastMCP and return how many were added.

    provider_factory(profile) returns a gads_provider.CredentialProvider for
    that profile name (None for the default); without it the active local
    profile is used.
    """
    from mcp.types import ToolAnnotations

    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
    )
    for name, title, fn in TOOLS:
        server.add_tool(
            _guarded(fn, provider_factory),
            name=prefix + name,
            title=title,
            description=inspect.cleandoc(fn.__doc__),
            annotations=annotations,
        )
    return len(TOOLS)


def main() -> None:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("google-ads-agents")
    register(server)
    server.run()


if __name__ == "__main__":
    main()
