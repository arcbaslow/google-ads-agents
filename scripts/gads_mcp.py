"""Google Ads tools for an MCP host.

register() adds the read-only tools to a host FastMCP; main() serves them
alone over stdio. They only call GoogleAdsService search, CustomerService
list_accessible_customers and GoogleAdsFieldService search. register_writes()
adds the gated write tools, which change an account only on a confirmed call.
Each call binds a credential provider for its duration: the host's
provider_factory(profile), or the active local profile. The `profile`
argument every tool exposes is consumed by that binding.
"""

from __future__ import annotations

import base64
import binascii
import concurrent.futures
import functools
import hashlib
import inspect
import itertools
import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from contextvars import copy_context
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

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
    "not_supported": (
        "The Google Ads API does not accept this change for this campaign type (Video campaigns "
        "reject every API change). Make it in the Google Ads UI."
    ),
}

_GOOGLE_ADS_ERRORS = (
    ("authentication_error", "auth_required"),
    ("authorization_error", "permission_denied"),
    ("quota_error", "quota_exceeded"),
    ("internal_error", "upstream_error"),
    ("request_error.RESOURCE_NOT_FOUND", "not_found"),
    ("operation_access_denied_error.OPERATION_NOT_PERMITTED_FOR_CAMPAIGN_TYPE", "not_supported"),
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
_MAX_WRITE_ITEMS = 200
_ROW_STATUSES = ("ENABLED", "PAUSED", "REMOVED")


class _Failure(Exception):
    """A refusal that already carries a contract category and a client-safe hint."""

    def __init__(self, category: str, hint: str, errors: list[dict] | None = None):
        super().__init__(hint)
        self.category = category
        self.hint = hint
        self.errors = errors


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


def _id(value, name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _Failure("invalid_argument", f"{name} must be a numeric Google Ads ID.")
    value = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,20}", value):
        raise _Failure("invalid_argument", f"{name} must be a numeric Google Ads ID.")
    return value


def _ids(values, name: str) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= _MAX_WRITE_ITEMS:
        raise _Failure("invalid_argument", f"{name} must list 1 to {_MAX_WRITE_ITEMS} IDs.")
    ids = [_id(value, name) for value in values]
    if len(set(ids)) != len(ids):
        raise _Failure("invalid_argument", f"{name} contains duplicates.")
    return ids


def _status(value, allowed: tuple[str, ...], name: str = "status") -> str:
    if value not in allowed:
        raise _Failure("invalid_argument", f"{name} must be one of {', '.join(allowed)}.")
    return value


def _date(value, name: str) -> date:
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise _Failure("invalid_argument", f"{name} must be a date in YYYY-MM-DD format.") from None


def _scope(campaign_id, ad_group_id=None) -> list[str]:
    where = []
    if campaign_id is not None:
        where.append(f"campaign.id = {_id(campaign_id, 'campaign_id')}")
    if ad_group_id is not None:
        where.append(f"ad_group.id = {_id(ad_group_id, 'ad_group_id')}")
    return where


def _select(cid: str, fields: str, resource: str, where: list[str], order: str, limit: int):
    import gads_export

    query = f"SELECT {fields} FROM {resource} WHERE {' AND '.join(where)} ORDER BY {order}"
    result = gads_export.query_rows(cid, query, limit)
    return result["rows"], not result["truncated"]


def _criterion_id(resource_name: str | None) -> str | None:
    # customers/{customer_id}/adGroupCriteria/{ad_group_id}~{criterion_id}
    return resource_name.rpartition("~")[2] if resource_name else None


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

    Status fields (campaign.status, ad_group.status, ad_group_criterion.status,
    ad_group_ad.status) hold the current status, not the status during the date range.
    When selecting metrics over a date range do not filter on status: entities paused or
    removed during the range drop out, understating cost and conversions. Drop
    zero-impression rows after the query instead. Filter on status only for what is live now.
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


def keywords(
    customer_id: str,
    campaign_id: str | None = None,
    ad_group_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
    profile: str | None = None,
) -> dict[str, Any]:
    """List keyword criteria (not negatives) with criterion ID, ad group ID, campaign ID, text,
    match type and status, ordered by criterion ID. Filter by `campaign_id`, `ad_group_id` and
    `status` (ENABLED, PAUSED or REMOVED; default all but REMOVED). The IDs are what
    set_keyword_status takes. `limit` defaults to 200, maximum 500.
    """
    cid = _customer_id(customer_id)
    limit = _bounded("limit", limit, 1, 500)
    where = ["ad_group_criterion.type = 'KEYWORD'", "ad_group_criterion.negative = FALSE"]
    if status is None:
        where.append("ad_group_criterion.status != 'REMOVED'")
    else:
        where.append(f"ad_group_criterion.status = '{_status(status, _ROW_STATUSES)}'")
    rows, complete = _select(
        cid,
        "campaign.id, ad_group.id, ad_group_criterion.criterion_id, "
        "ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type, "
        "ad_group_criterion.status",
        "ad_group_criterion",
        where + _scope(campaign_id, ad_group_id),
        "ad_group_criterion.criterion_id",
        limit,
    )
    items = []
    for row in rows:
        criterion = row.get("ad_group_criterion", {})
        items.append({
            "criterion_id": criterion.get("criterion_id"),
            "ad_group_id": row.get("ad_group", {}).get("id"),
            "campaign_id": row.get("campaign", {}).get("id"),
            "text": criterion.get("keyword", {}).get("text"),
            "match_type": criterion.get("keyword", {}).get("match_type"),
            "status": criterion.get("status"),
        })
    return {"customer_id": cid, "keywords": items, "rows_returned": len(items),
            "complete": complete}


def ads(
    customer_id: str,
    campaign_id: str | None = None,
    ad_group_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
    profile: str | None = None,
) -> dict[str, Any]:
    """List ads with ad ID, ad group ID, campaign ID, ad type, status, policy approval status and
    final URLs, ordered by ad ID. Filter by `campaign_id`, `ad_group_id` and `status` (ENABLED,
    PAUSED or REMOVED; default all but REMOVED). The IDs are what set_ad_status takes. `limit`
    defaults to 200, maximum 500.
    """
    cid = _customer_id(customer_id)
    limit = _bounded("limit", limit, 1, 500)
    if status is None:
        where = ["ad_group_ad.status != 'REMOVED'"]
    else:
        where = [f"ad_group_ad.status = '{_status(status, _ROW_STATUSES)}'"]
    rows, complete = _select(
        cid,
        "campaign.id, ad_group.id, ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status, "
        "ad_group_ad.policy_summary.approval_status, ad_group_ad.ad.final_urls",
        "ad_group_ad",
        where + _scope(campaign_id, ad_group_id),
        "ad_group_ad.ad.id",
        limit,
    )
    items = []
    for row in rows:
        ad_group_ad = row.get("ad_group_ad", {})
        ad = ad_group_ad.get("ad", {})
        items.append({
            "ad_id": ad.get("id"),
            "ad_group_id": row.get("ad_group", {}).get("id"),
            "campaign_id": row.get("campaign", {}).get("id"),
            "type": ad.get("type"),
            "status": ad_group_ad.get("status"),
            "approval_status": ad_group_ad.get("policy_summary", {}).get("approval_status"),
            "final_urls": ad.get("final_urls", []),
        })
    return {"customer_id": cid, "ads": items, "rows_returned": len(items), "complete": complete}


def search_terms(
    customer_id: str,
    date_from: str,
    date_to: str,
    campaign_id: str | None = None,
    limit: int = 200,
    profile: str | None = None,
) -> dict[str, Any]:
    """Search terms report between `date_from` and `date_to` (YYYY-MM-DD, inclusive), highest
    cost first: search term, its status (ADDED, EXCLUDED, ADDED_EXCLUDED or NONE), campaign and
    ad group IDs, the matched keyword's text, match type and criterion ID, cost (micros),
    clicks, impressions and conversions. The matched keyword's own status is not available from
    this report; look it up with keywords. One row per term, ad group and matched keyword.
    `limit` defaults to 200, maximum 500.
    """
    cid = _customer_id(customer_id)
    limit = _bounded("limit", limit, 1, 500)
    start, end = _date(date_from, "date_from"), _date(date_to, "date_to")
    if start > end:
        raise _Failure("invalid_argument", "date_from must not be after date_to.")
    rows, complete = _select(
        cid,
        "search_term_view.search_term, search_term_view.status, campaign.id, ad_group.id, "
        "segments.keyword.info.text, segments.keyword.info.match_type, "
        "segments.keyword.ad_group_criterion, metrics.cost_micros, metrics.clicks, "
        "metrics.impressions, metrics.conversions",
        "search_term_view",
        [f"segments.date BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"]
        + _scope(campaign_id),
        "metrics.cost_micros DESC",
        limit,
    )
    items = []
    for row in rows:
        view = row.get("search_term_view", {})
        keyword = row.get("segments", {}).get("keyword", {})
        metrics = row.get("metrics", {})
        items.append({
            "search_term": view.get("search_term"),
            "status": view.get("status"),
            "campaign_id": row.get("campaign", {}).get("id"),
            "ad_group_id": row.get("ad_group", {}).get("id"),
            "keyword_text": keyword.get("info", {}).get("text"),
            "keyword_match_type": keyword.get("info", {}).get("match_type"),
            "keyword_criterion_id": _criterion_id(keyword.get("ad_group_criterion")),
            "cost_micros": int(metrics.get("cost_micros", 0)),
            "clicks": int(metrics.get("clicks", 0)),
            "impressions": int(metrics.get("impressions", 0)),
            "conversions": float(metrics.get("conversions", 0)),
        })
    return {"customer_id": cid, "date_range": {"start": start.isoformat(), "end": end.isoformat()},
            "search_terms": items, "rows_returned": len(items), "complete": complete}


def asset_group_assets(
    customer_id: str,
    campaign_id: str | None = None,
    asset_group_id: str | None = None,
    limit: int = 200,
    profile: str | None = None,
) -> dict[str, Any]:
    """List Performance Max asset group asset links (not REMOVED): campaign and asset group IDs,
    field type, asset ID, asset type, asset name or text, link status and primary status. API
    v25 has no asset performance label; primary_status (ELIGIBLE, LIMITED, NOT_ELIGIBLE,
    PAUSED, PENDING) is the serving state Google reports. The IDs and field types are what
    update_asset_group_assets takes. `limit` defaults to 200, maximum 500.
    """
    cid = _customer_id(customer_id)
    limit = _bounded("limit", limit, 1, 500)
    where = ["campaign.advertising_channel_type = 'PERFORMANCE_MAX'",
             "asset_group_asset.status != 'REMOVED'"]
    if asset_group_id is not None:
        where.append(f"asset_group.id = {_id(asset_group_id, 'asset_group_id')}")
    rows, complete = _select(
        cid,
        "campaign.id, asset_group.id, asset_group_asset.field_type, asset_group_asset.status, "
        "asset_group_asset.primary_status, asset.id, asset.type, asset.name, asset.text_asset.text",
        "asset_group_asset",
        where + _scope(campaign_id),
        "asset_group.id, asset_group_asset.field_type",
        limit,
    )
    items = []
    for row in rows:
        link = row.get("asset_group_asset", {})
        asset = row.get("asset", {})
        items.append({
            "campaign_id": row.get("campaign", {}).get("id"),
            "asset_group_id": row.get("asset_group", {}).get("id"),
            "field_type": link.get("field_type"),
            "asset_id": asset.get("id"),
            "asset_type": asset.get("type"),
            "name": asset.get("name"),
            "text": asset.get("text_asset", {}).get("text"),
            "status": link.get("status"),
            "primary_status": link.get("primary_status"),
        })
    return {"customer_id": cid, "assets": items, "rows_returned": len(items),
            "complete": complete}


TOOLS: tuple[tuple[str, str, Callable[..., dict[str, Any]]], ...] = (
    ("list_accounts", "List Google Ads accounts", list_accounts),
    ("run_gaql", "Run a GAQL query", run_gaql),
    ("resource_metadata", "Look up GAQL resources and fields", resource_metadata),
    ("account_audit", "Audit a Google Ads account", account_audit),
    ("anomalies_and_pacing", "Find anomalies and budget pacing", anomalies_and_pacing),
    ("change_history", "Show recent account changes", change_history),
    ("keywords", "List keywords", keywords),
    ("ads", "List ads", ads),
    ("search_terms", "Search terms report", search_terms),
    ("asset_group_assets", "List Performance Max asset group assets", asset_group_assets),
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
        # Error messages and trigger values can echo submitted data; only the codes are read.
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
            out = {"error": category, "hint": hint}
            if isinstance(exc, _Failure) and exc.errors:
                out["errors"] = exc.errors
            return out

    return tool


CONFIRM_TTL_SECONDS = 600
MAX_PENDING_CONFIRMS = 100
_CONFIRM_RE = re.compile(r"[0-9a-f]{32}")
_STALE_CONFIRM = (
    "confirm is unknown, expired, already used or was issued for a different request. Nothing "
    "was sent. Call again without confirm for a new dry run, check it, then confirm."
)
_CONFIRM_HINT = (
    "Google Ads validated this request (validate_only); nothing was changed. To send exactly "
    "this request once, repeat the call with identical arguments plus confirm within 10 "
    "minutes; a token works once."
)
_CONFLICT_HINT = (
    "The resources changed since the dry run. Nothing was sent. Run the dry run again and "
    "review it."
)
_UNKNOWN_OUTCOME = (
    "The write was sent but no answer came back, so it may have been applied. Read the "
    "resources before trying again."
)
_ENABLE_PAUSE = ("ENABLED", "PAUSED")
# No client deadline means a hung mutate never returns; 60 s covers 200 operations.
_WRITE_TIMEOUT_SECONDS = 60.0
_WRITE_HINTS = {
    "permission_denied": (
        "These credentials cannot change this account. The Google Ads user needs Standard or "
        "Admin access, and the profile's manager account must manage the customer."
    ),
    "invalid_argument": (
        "Google Ads rejected the change; errors lists the codes and field paths. Nothing was "
        "changed."
    ),
    "not_found": "The resource to change was not found or is not accessible with this profile.",
}
_pending: dict[str, tuple[str, str, float]] = {}
_pending_lock = threading.Lock()


def _arguments(local: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in local.items() if key not in ("confirm", "gate")}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _issue(digest: str, reviewed: str) -> str:
    now = time.monotonic()
    token = secrets.token_hex(16)
    with _pending_lock:
        for old in [t for t, (_, _, at) in _pending.items() if now - at > CONFIRM_TTL_SECONDS]:
            del _pending[old]
        _pending[token] = (digest, reviewed, now)
        while len(_pending) > MAX_PENDING_CONFIRMS:
            del _pending[next(iter(_pending))]
    return token


def _check_confirm(confirm) -> None:
    if confirm is not None and (not isinstance(confirm, str) or not _CONFIRM_RE.fullmatch(confirm)):
        raise _Failure("invalid_argument", _STALE_CONFIRM)


def _refusal(gate: Callable[[], Any]) -> dict[str, Any] | None:
    refusal = gate()
    if refusal is None:
        return None
    if isinstance(refusal, dict):
        return refusal
    return {"error": "permission_denied", "hint": "The host does not allow writes."}


def _api_errors(exc: Exception) -> list[dict] | None:
    """Error codes and field paths only: messages and trigger values can echo the request."""
    from google.ads.googleads.errors import GoogleAdsException

    if not isinstance(exc, GoogleAdsException):
        return None
    errors = []
    for error in itertools.islice(exc.failure.errors, _MAX_WRITE_ITEMS):
        kind = error.error_code._pb.WhichOneof("error_code")
        value = getattr(getattr(error.error_code, kind), "name", "") if kind else ""
        path = "".join(
            f".{element.field_name}" + (f"[{element.index}]" if element._pb.HasField("index") else "")
            for element in error.location.field_path_elements
        )
        errors.append({"code": f"{kind}.{value}" if kind else "unknown",
                       "field_path": path.lstrip(".") or None})
    return errors


def _mutate(client, service: str, method: str, request_type: str, cid: str, operations: list,
            validate_only: bool):
    request = client.get_type(request_type)
    request.customer_id = cid
    request.operations.extend(operations)
    request.validate_only = validate_only
    try:
        # A retried write could be applied twice.
        return getattr(client.get_service(service), method)(
            request=request, retry=None, timeout=_WRITE_TIMEOUT_SECONDS)
    except Exception as exc:
        category, hint = _classify(exc)
        hint = _WRITE_HINTS.get(category, hint)
        if not validate_only and category == "upstream_error":
            hint = _UNKNOWN_OUTCOME
        raise _Failure(category, hint, _api_errors(exc)) from None


def _review(tool: str, arguments: dict, confirm: str | None, gate: Callable[[], Any], target: str,
            state: Any, head: dict[str, Any], send: Callable[[bool], Any]) -> dict[str, Any]:
    """Dry run: validate_only and a token. Confirmed: gate, redeem, then send once."""
    digest = _digest({"tool": tool, **arguments})
    reviewed = _digest(state)
    if confirm is None:
        send(True)
        return {"dry_run": True, **head, "validated": True, "confirm": _issue(digest, reviewed),
                "confirm_expires_in": CONFIRM_TTL_SECONDS, "hint": _CONFIRM_HINT}
    refusal = _refusal(gate)
    if refusal is not None:
        return refusal
    with _pending_lock:
        entry = _pending.pop(confirm, None)
    if entry is None or time.monotonic() - entry[2] > CONFIRM_TTL_SECONDS or entry[0] != digest:
        raise _Failure("invalid_argument", _STALE_CONFIRM)
    if entry[1] != reviewed:
        raise _Failure("conflict", _CONFLICT_HINT)
    try:
        response = send(False)
    except Exception as exc:
        log.info("gads write %s %s outcome=%s", tool, target, _classify(exc)[0])
        raise
    log.info("gads write %s %s outcome=ok", tool, target)
    return {"dry_run": False, **head, "applied": len(response.results),
            "resource_names": [result.resource_name for result in response.results]}


def _writable(row: dict) -> None:
    if row.get("campaign", {}).get("advertising_channel_type") == "VIDEO":
        raise _Failure("not_supported", _HINTS["not_supported"])


def _found(ids: list[str], rows: dict[str, dict], label: str) -> list[dict]:
    missing = [i for i in ids if i not in rows]
    if missing:
        raise _Failure("not_found", f"No {label} with ID {', '.join(missing[:20])} was found.")
    return [rows[i] for i in ids]


def set_keyword_status(
    customer_id: str,
    ad_group_id: str,
    criterion_ids: list[str],
    status: str,
    confirm: str | None = None,
    profile: str | None = None,
    *,
    gate: Callable[[], Any],
) -> dict[str, Any]:
    """Set up to 200 keywords of one ad group to ENABLED or PAUSED in one mutate. Take the IDs
    from keywords. A call without confirm changes nothing: it reads the keywords, validates the
    update with Google Ads (validate_only) and returns each keyword's current and new status
    plus a single-use confirm token valid for 10 minutes. The identical call with that token
    sends the update once. If a keyword changed in between, nothing is sent and the result is
    conflict. Keywords in Video campaigns return not_supported.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    ag = _id(ad_group_id, "ad_group_id")
    ids = _ids(criterion_ids, "criterion_ids")
    status = _status(status, _ENABLE_PAUSE)
    _check_confirm(confirm)
    rows = gads_client.search_stream(cid, f"""
        SELECT ad_group_criterion.criterion_id, ad_group_criterion.status,
          ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
          campaign.advertising_channel_type
        FROM ad_group_criterion
        WHERE ad_group.id = {ag} AND ad_group_criterion.type = 'KEYWORD'
          AND ad_group_criterion.criterion_id IN ({', '.join(ids)})""")
    state = _found(ids, {r["ad_group_criterion"]["criterion_id"]: r for r in rows}, "keyword")
    changes = []
    for row in state:
        _writable(row)
        criterion = row["ad_group_criterion"]
        changes.append({
            "criterion_id": criterion["criterion_id"],
            "text": criterion.get("keyword", {}).get("text"),
            "match_type": criterion.get("keyword", {}).get("match_type"),
            "status": criterion.get("status"),
            "new_status": status,
        })
    client = gads_client.build_client()
    operations = []
    for criterion_id in ids:
        op = client.get_type("AdGroupCriterionOperation")
        op.update.resource_name = f"customers/{cid}/adGroupCriteria/{ag}~{criterion_id}"
        op.update.status = getattr(client.enums.AdGroupCriterionStatusEnum, status)
        op.update_mask.paths.append("status")
        operations.append(op)
    head = {"customer_id": cid, "ad_group_id": ag, "changes": changes}
    return _review(
        "set_keyword_status", arguments, confirm, gate, f"customers/{cid}/adGroups/{ag}", state,
        head, lambda validate_only: _mutate(
            client, "AdGroupCriterionService", "mutate_ad_group_criteria",
            "MutateAdGroupCriteriaRequest", cid, operations, validate_only))


def set_ad_status(
    customer_id: str,
    ad_group_id: str,
    ad_ids: list[str],
    status: str,
    confirm: str | None = None,
    profile: str | None = None,
    *,
    gate: Callable[[], Any],
) -> dict[str, Any]:
    """Set up to 200 ads of one ad group to ENABLED or PAUSED in one mutate. Take the IDs from
    ads. A call without confirm changes nothing: it reads the ads, validates the update with
    Google Ads (validate_only) and returns each ad's current and new status plus a single-use
    confirm token valid for 10 minutes. The identical call with that token sends the update
    once. If an ad changed in between, nothing is sent and the result is conflict. Ads in Video
    campaigns return not_supported.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    ag = _id(ad_group_id, "ad_group_id")
    ids = _ids(ad_ids, "ad_ids")
    status = _status(status, _ENABLE_PAUSE)
    _check_confirm(confirm)
    rows = gads_client.search_stream(cid, f"""
        SELECT ad_group_ad.ad.id, ad_group_ad.ad.type, ad_group_ad.status,
          campaign.advertising_channel_type
        FROM ad_group_ad
        WHERE ad_group.id = {ag} AND ad_group_ad.ad.id IN ({', '.join(ids)})""")
    state = _found(ids, {r["ad_group_ad"]["ad"]["id"]: r for r in rows}, "ad")
    changes = []
    for row in state:
        _writable(row)
        ad_group_ad = row["ad_group_ad"]
        changes.append({"ad_id": ad_group_ad["ad"]["id"], "type": ad_group_ad["ad"].get("type"),
                        "status": ad_group_ad.get("status"), "new_status": status})
    client = gads_client.build_client()
    operations = []
    for ad_id in ids:
        op = client.get_type("AdGroupAdOperation")
        op.update.resource_name = f"customers/{cid}/adGroupAds/{ag}~{ad_id}"
        op.update.status = getattr(client.enums.AdGroupAdStatusEnum, status)
        op.update_mask.paths.append("status")
        operations.append(op)
    head = {"customer_id": cid, "ad_group_id": ag, "changes": changes}
    return _review(
        "set_ad_status", arguments, confirm, gate, f"customers/{cid}/adGroups/{ag}", state, head,
        lambda validate_only: _mutate(client, "AdGroupAdService", "mutate_ad_group_ads",
                                      "MutateAdGroupAdsRequest", cid, operations, validate_only))


def update_campaign_schedule(
    customer_id: str,
    campaign_id: str,
    end_date: str | None = None,
    start_date: str | None = None,
    confirm: str | None = None,
    profile: str | None = None,
    *,
    gate: Callable[[], Any],
) -> dict[str, Any]:
    """Change a campaign's end date and, while the campaign has not started yet, its start date
    (YYYY-MM-DD, customer time zone). The end is sent as end_date_time "YYYY-MM-DD 23:59:59" and
    the start as start_date_time "YYYY-MM-DD 00:00:00". A call without confirm changes nothing:
    it reads the campaign, validates the update with Google Ads (validate_only) and returns the
    current and new values plus a single-use confirm token valid for 10 minutes. Google Ads
    rejects a start change on a started campaign (CANNOT_MODIFY_START_DATE_IF_ALREADY_STARTED)
    and dates in the past (CANNOT_SET_DATE_TO_PAST). The identical call with that token sends
    the update once; if the campaign changed in between, nothing is sent and the result is
    conflict. Video campaigns return not_supported.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    campaign = _id(campaign_id, "campaign_id")
    if end_date is None and start_date is None:
        raise _Failure("invalid_argument", "Pass end_date, start_date or both.")
    end = None if end_date is None else _date(end_date, "end_date")
    start = None if start_date is None else _date(start_date, "start_date")
    if start and end and start > end:
        raise _Failure("invalid_argument", "start_date must not be after end_date.")
    _check_confirm(confirm)
    rows = gads_client.search_stream(cid, f"""
        SELECT campaign.id, campaign.status, campaign.advertising_channel_type,
          campaign.start_date_time, campaign.end_date_time
        FROM campaign WHERE campaign.id = {campaign}""")
    if not rows:
        raise _Failure("not_found", f"No campaign with ID {campaign} was found.")
    _writable(rows[0])
    current = rows[0]["campaign"]
    client = gads_client.build_client()
    op = client.get_type("CampaignOperation")
    op.update.resource_name = f"customers/{cid}/campaigns/{campaign}"
    changes = {}
    for field, day, clock in (("start_date_time", start, "00:00:00"),
                              ("end_date_time", end, "23:59:59")):
        if day is not None:
            value = f"{day.isoformat()} {clock}"
            setattr(op.update, field, value)
            op.update_mask.paths.append(field)
            changes[field] = {"current": current.get(field), "new": value}
    head = {"customer_id": cid, "campaign_id": campaign, "campaign_status": current.get("status"),
            "advertising_channel_type": current.get("advertising_channel_type"),
            "changes": changes}
    return _review(
        "update_campaign_schedule", arguments, confirm, gate, op.update.resource_name, rows, head,
        lambda validate_only: _mutate(client, "CampaignService", "mutate_campaigns",
                                      "MutateCampaignsRequest", cid, [op], validate_only))


def set_conversion_action_goal(
    customer_id: str,
    conversion_action_id: str,
    primary: bool,
    confirm: str | None = None,
    profile: str | None = None,
    *,
    gate: Callable[[], Any],
) -> dict[str, Any]:
    """Set primary_for_goal on a conversion action. Primary means the action counts in
    Conversions and is used for bidding in campaigns that optimize toward its standard goal;
    secondary means it is reported in All conversions only. An action that is part of a custom
    conversion goal keeps driving bidding and Conversions for campaigns on that custom goal
    whatever this value is, so secondary does not by itself stop optimization there. A call
    without confirm changes nothing: it reads the action, validates the update with Google
    Ads (validate_only) and returns the current and new value plus a single-use confirm token
    valid for 10 minutes. The identical call with that token sends the update once; if the
    action changed in between, nothing is sent and the result is conflict.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    action = _id(conversion_action_id, "conversion_action_id")
    if type(primary) is not bool:
        raise _Failure("invalid_argument", "primary must be true or false.")
    _check_confirm(confirm)
    rows = gads_client.search_stream(cid, f"""
        SELECT conversion_action.id, conversion_action.name, conversion_action.status,
          conversion_action.category, conversion_action.primary_for_goal
        FROM conversion_action WHERE conversion_action.id = {action}""")
    if not rows:
        raise _Failure("not_found", f"No conversion action with ID {action} was found.")
    current = rows[0]["conversion_action"]
    client = gads_client.build_client()
    op = client.get_type("ConversionActionOperation")
    op.update.resource_name = f"customers/{cid}/conversionActions/{action}"
    op.update.primary_for_goal = primary
    op.update_mask.paths.append("primary_for_goal")
    head = {"customer_id": cid, "conversion_action_id": action, "name": current.get("name"),
            "category": current.get("category"), "status": current.get("status"),
            "changes": {"primary_for_goal": {"current": current.get("primary_for_goal", False),
                                             "new": primary}}}
    return _review(
        "set_conversion_action_goal", arguments, confirm, gate, op.update.resource_name, rows,
        head, lambda validate_only: _mutate(
            client, "ConversionActionService", "mutate_conversion_actions",
            "MutateConversionActionsRequest", cid, [op], validate_only))


def _strings(values, name: str) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values):
        raise _Failure("invalid_argument", f"{name} must be a list of non-empty strings.")
    cleaned = [value.strip() for value in values]
    if len(set(cleaned)) != len(cleaned):
        raise _Failure("invalid_argument", f"{name} contains duplicates.")
    return cleaned


def add_placement_exclusions(
    customer_id: str,
    campaign_id: str,
    placements: list[str] | None = None,
    youtube_channel_ids: list[str] | None = None,
    youtube_video_ids: list[str] | None = None,
    mobile_app_ids: list[str] | None = None,
    confirm: str | None = None,
    profile: str | None = None,
    *,
    gate: Callable[[], Any],
) -> dict[str, Any]:
    """Exclude up to 200 placements from one campaign in one atomic mutate, as campaign-level
    negative criteria: website `placements` (URL or domain), `youtube_channel_ids` (UC...),
    `youtube_video_ids` and `mobile_app_ids` ("{platform}-{app id}": "1-123456789" for an iOS
    App Store ID, "2-com.example.app" for an Android package name). A call without confirm changes
    nothing: it reads the campaign, validates the exclusions with Google Ads (validate_only) and
    returns them plus a single-use confirm token valid for 10 minutes. The identical call with
    that token sends them once; either all are added or none. Video campaigns return
    not_supported.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    campaign = _id(campaign_id, "campaign_id")
    targets = [(kind, value) for kind, values in (
        ("placement", _strings(placements, "placements")),
        ("youtube_channel", _strings(youtube_channel_ids, "youtube_channel_ids")),
        ("youtube_video", _strings(youtube_video_ids, "youtube_video_ids")),
        ("mobile_application", _strings(mobile_app_ids, "mobile_app_ids")),
    ) for value in values]
    if not 1 <= len(targets) <= _MAX_WRITE_ITEMS:
        raise _Failure("invalid_argument", f"Pass 1 to {_MAX_WRITE_ITEMS} exclusions in total.")
    _check_confirm(confirm)
    rows = gads_client.search_stream(cid, f"""
        SELECT campaign.id, campaign.status, campaign.advertising_channel_type
        FROM campaign WHERE campaign.id = {campaign}""")
    if not rows:
        raise _Failure("not_found", f"No campaign with ID {campaign} was found.")
    _writable(rows[0])
    client = gads_client.build_client()
    campaign_path = f"customers/{cid}/campaigns/{campaign}"
    fields = {"placement": "url", "youtube_channel": "channel_id",
              "youtube_video": "video_id", "mobile_application": "app_id"}
    operations = []
    for kind, value in targets:
        op = client.get_type("CampaignCriterionOperation")
        op.create.campaign = campaign_path
        op.create.negative = True
        setattr(getattr(op.create, kind), fields[kind], value)
        operations.append(op)
    head = {"customer_id": cid, "campaign_id": campaign,
            "advertising_channel_type": rows[0]["campaign"].get("advertising_channel_type"),
            "exclusions": [{"type": kind, "value": value} for kind, value in targets]}
    return _review(
        "add_placement_exclusions", arguments, confirm, gate, campaign_path, rows, head,
        lambda validate_only: _mutate(
            client, "CampaignCriterionService", "mutate_campaign_criteria",
            "MutateCampaignCriteriaRequest", cid, operations, validate_only))


def _asset_links(items, name: str) -> list[tuple[str, str]]:
    from google.ads.googleads.v25.enums.types.asset_field_type import AssetFieldTypeEnum

    if items is None:
        return []
    known = set(AssetFieldTypeEnum.AssetFieldType.__members__) - {"UNSPECIFIED", "UNKNOWN"}
    if not isinstance(items, list) or any(
            not isinstance(item, dict) or set(item) != {"asset_id", "field_type"}
            for item in items):
        raise _Failure("invalid_argument",
                       f"{name} items must be objects with exactly asset_id and field_type.")
    links = []
    for item in items:
        if item["field_type"] not in known:
            raise _Failure("invalid_argument",
                           f"{name}: field_type must be an AssetFieldType such as HEADLINE, "
                           "DESCRIPTION, LONG_HEADLINE, MARKETING_IMAGE, LOGO or YOUTUBE_VIDEO.")
        links.append((_id(item["asset_id"], f"{name} asset_id"), item["field_type"]))
    return links


def update_asset_group_assets(
    customer_id: str,
    asset_group_id: str,
    add: list[dict] | None = None,
    remove: list[dict] | None = None,
    confirm: str | None = None,
    profile: str | None = None,
    *,
    gate: Callable[[], Any],
) -> dict[str, Any]:
    """Link existing assets to a Performance Max asset group and unlink others in one atomic
    mutate, unlinks first. Items in `add` and `remove` are {"asset_id": "...", "field_type":
    "HEADLINE"}; up to 200 in total. Unlinking removes only the link, not the asset; nothing is
    uploaded. A call without confirm changes nothing: it reads the group's current links,
    validates the change with Google Ads (validate_only, which also checks the group's asset
    minimums) and returns it plus a single-use confirm token valid for 10 minutes. The identical
    call with that token sends it once; if the group's links changed in between, nothing is
    sent and the result is conflict.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    group = _id(asset_group_id, "asset_group_id")
    adds, removes = _asset_links(add, "add"), _asset_links(remove, "remove")
    links = adds + removes
    if not 1 <= len(links) <= _MAX_WRITE_ITEMS:
        raise _Failure("invalid_argument", f"Pass 1 to {_MAX_WRITE_ITEMS} add and remove items.")
    if len(set(links)) != len(links):
        raise _Failure("invalid_argument", "add and remove contain the same link twice.")
    _check_confirm(confirm)
    groups = gads_client.search_stream(cid, f"""
        SELECT asset_group.id, asset_group.status, campaign.id, campaign.advertising_channel_type
        FROM asset_group WHERE asset_group.id = {group}""")
    if not groups:
        raise _Failure("not_found", f"No asset group with ID {group} was found.")
    _writable(groups[0])
    current = gads_client.search_stream(cid, f"""
        SELECT asset.id, asset_group_asset.field_type, asset_group_asset.status
        FROM asset_group_asset
        WHERE asset_group.id = {group} AND asset_group_asset.status != 'REMOVED'""")
    reviewed = sorted((row["asset"]["id"], row["asset_group_asset"]["field_type"],
                       row["asset_group_asset"]["status"]) for row in current)
    linked = [link[:2] for link in reviewed]
    missing = [f"{asset}/{field}" for asset, field in removes if (asset, field) not in linked]
    if missing:
        raise _Failure("not_found", f"Not linked to this asset group: {', '.join(missing[:20])}.")
    client = gads_client.build_client()
    group_path = f"customers/{cid}/assetGroups/{group}"
    operations = []
    for asset, field in removes:
        op = client.get_type("AssetGroupAssetOperation")
        op.remove = f"customers/{cid}/assetGroupAssets/{group}~{asset}~{field}"
        operations.append(op)
    for asset, field in adds:
        op = client.get_type("AssetGroupAssetOperation")
        op.create.asset_group = group_path
        op.create.asset = f"customers/{cid}/assets/{asset}"
        op.create.field_type = getattr(client.enums.AssetFieldTypeEnum, field)
        operations.append(op)
    head = {"customer_id": cid, "asset_group_id": group,
            "remove": [{"asset_id": a, "field_type": f} for a, f in removes],
            "add": [{"asset_id": a, "field_type": f} for a, f in adds],
            "linked_before": len(linked)}
    return _review(
        "update_asset_group_assets", arguments, confirm, gate, group_path, [groups, reviewed], head,
        lambda validate_only: _mutate(
            client, "AssetGroupAssetService", "mutate_asset_group_assets",
            "MutateAssetGroupAssetsRequest", cid, operations, validate_only))


def manage_labels(
    customer_id: str, operation: str, name: str | None = None,
    background_color: str | None = None, description: str | None = None,
    label_id: str | None = None, confirm: str | None = None, profile: str | None = None,
    *, gate: Callable[[], Any],
) -> dict[str, Any]:
    """Create, update or remove one label. Names contain 1-80 characters, descriptions at
    most 200, and colors are #RRGGBB. UPDATE sends only supplied fields; REMOVE takes only
    label_id. Without confirm, validate_only returns current and new values and a single-use
    token valid for 10 minutes. Repeat identical arguments with the token to send once after
    the host gate. A changed label state returns conflict without sending.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    operation = _status(operation, ("CREATE", "UPDATE", "REMOVE"), "operation")
    fields = {key: value for key, value in {
        "name": name, "background_color": background_color, "description": description,
    }.items() if value is not None}
    if operation == "CREATE":
        if name is None or label_id is not None:
            raise _Failure("invalid_argument", "CREATE requires name and does not accept label_id.")
    else:
        label_id = _id(label_id, "label_id")
        if operation == "UPDATE" and not fields or operation == "REMOVE" and fields:
            raise _Failure("invalid_argument", "UPDATE requires fields; REMOVE accepts only label_id.")
    if name is not None:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise _Failure("invalid_argument", "name must contain 1 to 80 characters after stripping.")
        fields["name"] = name.strip()
    if description is not None and (not isinstance(description, str) or len(description) > 200):
        raise _Failure("invalid_argument", "description must contain at most 200 characters.")
    if background_color is not None and (
            not isinstance(background_color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", background_color)):
        raise _Failure("invalid_argument", "background_color must be #RRGGBB.")
    _check_confirm(confirm)
    if operation == "CREATE":
        escaped = fields["name"].replace("\\", "\\\\").replace("'", "\\'")
        where = f"label.name = '{escaped}'"
    else:
        where = f"label.id = {label_id}"
    state = gads_client.search_stream(cid, f"""
        SELECT label.id, label.name, label.status, label.text_label.background_color,
          label.text_label.description FROM label WHERE {where} ORDER BY label.id""")
    current = state[0]["label"] if state else {}
    if operation == "CREATE":
        duplicates = [str(row["label"]["id"]) for row in state if row["label"].get("status") == "ENABLED"]
        if duplicates and confirm is None:
            raise _Failure("invalid_argument", f"An ENABLED label with this name exists: {', '.join(duplicates)}.")
        current = {}
    elif not current or current.get("status") == "REMOVED":
        raise _Failure("not_found", f"No label with ID {label_id} was found.")
    client = gads_client.build_client()
    op = client.get_type("LabelOperation")
    target = f"customers/{cid}/labels/{label_id}" if label_id else f"customers/{cid}"
    changes = []
    if operation == "REMOVE":
        op.remove = target
        changes.append({"field": "status", "current": current.get("status"), "new": "REMOVED"})
    else:
        label = op.create if operation == "CREATE" else op.update
        if operation == "UPDATE":
            label.resource_name = target
        for field, value in fields.items():
            path = field if field == "name" else f"text_label.{field}"
            setattr(label if field == "name" else label.text_label, field, value)
            if operation == "UPDATE":
                op.update_mask.paths.append(path)
            previous = current if field == "name" else current.get("text_label", {})
            changes.append({"field": path, "current": previous.get(field), "new": value})
    head = {"customer_id": cid, "label_id": label_id, "operation": operation, "changes": changes}
    return _review(
        "manage_labels", arguments, confirm, gate, target, state, head,
        lambda validate_only: _mutate(client, "LabelService", "mutate_labels",
                                      "MutateLabelsRequest", cid, [op], validate_only))


def manage_label_associations(
    customer_id: str, operation: str, association_type: str, label_id: str,
    resource_ids: list[str] | None = None, confirm: str | None = None,
    profile: str | None = None, *, gate: Callable[[], Any],
) -> dict[str, Any]:
    """Attach or remove an ENABLED label on 1-200 campaigns, ad groups or ad group criteria.
    Criteria use ad_group_id~criterion_id. CREATE rejects existing links; REMOVE requires
    them. Video campaigns return not_supported. Without confirm, validate_only returns
    before/after links and a single-use token valid for 10 minutes. Repeat identical
    arguments with the token to send once after the host gate. Changed target or
    association state returns conflict without sending.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    operation = _status(operation, ("CREATE", "REMOVE"), "operation")
    # CUSTOMER is left out: v25 documents customerLabels/{label_id} with output-only fields,
    # which contradicts Google's own server, and no live call has settled it.
    association_type = _status(association_type, ("CAMPAIGN", "AD_GROUP", "AD_GROUP_CRITERION"),
                               "association_type")
    label_id = _id(label_id, "label_id")
    if association_type == "AD_GROUP_CRITERION":
        if not isinstance(resource_ids, list) or not 1 <= len(resource_ids) <= _MAX_WRITE_ITEMS:
            raise _Failure("invalid_argument", "resource_ids must list 1 to 200 IDs.")
        ids = []
        for value in resource_ids:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]+~[0-9]+", value):
                raise _Failure("invalid_argument", "Criterion IDs must be ad_group_id~criterion_id.")
            ids.append("~".join(_id(part, "resource_ids") for part in value.split("~")))
        if len(set(ids)) != len(ids):
            raise _Failure("invalid_argument", "resource_ids contains duplicates.")
    else:
        ids = _ids(resource_ids, "resource_ids")
    _check_confirm(confirm)
    labels = gads_client.search_stream(cid, f"""
        SELECT label.id, label.name, label.status FROM label WHERE label.id = {label_id}""")
    if not labels or labels[0]["label"].get("status") != "ENABLED":
        raise _Failure("not_found", f"No ENABLED label with ID {label_id} was found.")
    entity, stem, plural, segment = {
        "CAMPAIGN": ("campaign", "Campaign", "campaigns", "campaignLabels"),
        "AD_GROUP": ("ad_group", "AdGroup", "adGroups", "adGroupLabels"),
        "AD_GROUP_CRITERION": ("ad_group_criterion", "AdGroupCriterion", "adGroupCriteria", "adGroupCriterionLabels"),
    }[association_type]
    paths = {i: f"customers/{cid}/{plural}/{i}" for i in ids}
    path_list = ", ".join(f"'{path}'" for path in paths.values())
    fields = f"{entity}.resource_name, {entity}.status, campaign.advertising_channel_type"
    if entity != "ad_group_criterion":
        fields += f", {entity}.name"
    rows = gads_client.search_stream(cid, f"""
        SELECT {fields} FROM {entity} WHERE {entity}.resource_name IN ({path_list})""")
    targets = _found(ids, {r[entity]["resource_name"].rsplit("/", 1)[-1]: r for r in rows
                           if r[entity].get("status") != "REMOVED"}, entity)
    for row in targets:
        _writable(row)
    association = f"{entity}_label"
    label_path = f"customers/{cid}/labels/{label_id}"
    links = gads_client.search_stream(cid, f"""
        SELECT {association}.resource_name, {association}.{entity}, {association}.label
        FROM {association} WHERE {association}.label = '{label_path}'
          AND {association}.{entity} IN ({path_list})""")
    # resource_name is not sortable in GAQL; the conflict digest needs a stable order.
    links.sort(key=lambda r: r[association]["resource_name"])
    linked = {r[association][entity] for r in links}
    mismatched = [i for i in ids if (paths[i] in linked) == (operation == "CREATE")]
    if mismatched and confirm is None:
        category = "invalid_argument" if operation == "CREATE" else "not_found"
        message = "already have" if operation == "CREATE" else "do not have"
        raise _Failure(category, f"Targets {', '.join(mismatched)} {message} label {label_id}.")
    client = gads_client.build_client()
    operations, changes = [], []
    for i, row in zip(ids, targets):
        op = client.get_type(f"{stem}LabelOperation")
        if operation == "CREATE":
            setattr(op.create, entity, paths[i])
            op.create.label = label_path
        else:
            op.remove = f"customers/{cid}/{segment}/{i}~{label_id}"
        operations.append(op)
        changes.append({"resource_id": i, "name": row[entity].get("name"),
                        "has_label": paths[i] in linked, "new_has_label": operation == "CREATE"})
    state = {"label": labels, "targets": targets, "associations": links}
    head = {"customer_id": cid, "label_id": label_id, "association_type": association_type, "changes": changes}
    return _review(
        "manage_label_associations", arguments, confirm, gate, label_path, state, head,
        lambda validate_only: _mutate(client, f"{stem}LabelService", f"mutate_{entity}_labels",
                                      f"Mutate{stem}LabelsRequest", cid, operations, validate_only))


def create_asset(
    customer_id: str, asset_type: str, name: str | None = None,
    final_urls: list[str] | None = None, final_mobile_urls: list[str] | None = None,
    tracking_url_template: str | None = None, final_url_suffix: str | None = None,
    text: str | None = None, image_data: str | None = None, image_mime_type: str | None = None,
    youtube_video_id: str | None = None, sitelink_link_text: str | None = None,
    sitelink_description1: str | None = None, sitelink_description2: str | None = None,
    callout_text: str | None = None, structured_snippet_header: str | None = None,
    structured_snippet_values: list[str] | None = None, confirm: str | None = None,
    profile: str | None = None, *, gate: Callable[[], Any],
) -> dict[str, Any]:
    """Create one unlinked TEXT, IMAGE, YOUTUBE_VIDEO, SITELINK, CALLOUT or STRUCTURED_SNIPPET
    asset. Use update_asset_group_assets for Performance Max linking. URLs are HTTP(S), up to
    10 per list. Images are base64 PNG, JPEG or GIF, at most 5120 KB; no local file paths.
    Sitelink text and callouts allow 25 characters, descriptions 35; snippets need 3-10 values
    of at most 25 characters. Without confirm, validate_only returns the fields (images only
    as mime, byte count and SHA-256) and a single-use token valid for 10 minutes. Repeat the
    identical call with the token to send once after the host gate. Changed customer state
    returns conflict without sending.
    """
    arguments = _arguments(locals())
    import gads_client

    cid = _customer_id(customer_id)
    kinds = {
        "TEXT": ("text",), "IMAGE": ("image_data", "image_mime_type"),
        "YOUTUBE_VIDEO": ("youtube_video_id",),
        "SITELINK": ("sitelink_link_text", "sitelink_description1", "sitelink_description2"),
        "CALLOUT": ("callout_text",),
        "STRUCTURED_SNIPPET": ("structured_snippet_header", "structured_snippet_values"),
    }
    asset_type = _status(asset_type, tuple(kinds), "asset_type")
    for kind, fields in kinds.items():
        for field in fields:
            value = arguments[field]
            if kind != asset_type and value is not None:
                raise _Failure("invalid_argument", f"{field} does not apply to {asset_type}.")
            if kind == asset_type and value is None and field not in ("sitelink_description1", "sitelink_description2"):
                raise _Failure("invalid_argument", f"{field} is required for {asset_type}.")
    common = {}
    for field in ("name", "tracking_url_template", "final_url_suffix"):
        value = arguments[field]
        if value is not None:
            if not isinstance(value, str):
                raise _Failure("invalid_argument", f"{field} must be text.")
            common[field] = value
    for field in ("final_urls", "final_mobile_urls"):
        values = arguments[field]
        if values is None:
            continue
        if not isinstance(values, list) or len(values) > 10:
            raise _Failure("invalid_argument", f"{field} must list at most 10 HTTP(S) URLs.")
        for value in values:
            try:
                url = urlsplit(value) if isinstance(value, str) else None
                valid = url and url.scheme in ("http", "https") and url.hostname and not any(c.isspace() for c in value)
            except ValueError:
                valid = False
            if not valid:
                raise _Failure("invalid_argument", f"{field} must contain HTTP(S) URLs with a host.")
        common[field] = values
    if asset_type == "SITELINK" and not final_urls:
        raise _Failure("invalid_argument", "SITELINK requires final_urls.")
    for field in kinds[asset_type]:
        value = arguments[field]
        if field in ("image_data", "image_mime_type", "structured_snippet_values") or value is None:
            continue
        maximum = 35 if field in ("sitelink_description1", "sitelink_description2") else (
            25 if field in ("sitelink_link_text", "callout_text") else None)
        if not isinstance(value, str) or not value.strip() or maximum and len(value) > maximum:
            raise _Failure("invalid_argument", f"{field} must be non-empty text" +
                           (f" of at most {maximum} characters." if maximum else "."))
    if asset_type == "YOUTUBE_VIDEO" and not re.fullmatch(r"[A-Za-z0-9_-]{11}", youtube_video_id):
        raise _Failure("invalid_argument", "youtube_video_id must contain 11 letters, digits, _ or -.")
    if asset_type == "STRUCTURED_SNIPPET":
        if (not isinstance(structured_snippet_values, list) or not 3 <= len(structured_snippet_values) <= 10
                or any(not isinstance(v, str) or not v.strip() or len(v) > 25 for v in structured_snippet_values)):
            raise _Failure("invalid_argument", "structured_snippet_values needs 3 to 10 non-empty values of at most 25 characters.")
    image = None
    if asset_type == "IMAGE":
        magic = {"IMAGE_PNG": (b"\x89PNG\r\n\x1a\n",), "IMAGE_JPEG": (b"\xff\xd8\xff",),
                 "IMAGE_GIF": (b"GIF87a", b"GIF89a")}
        _status(image_mime_type, tuple(magic), "image_mime_type")
        if not isinstance(image_data, str) or len(image_data) > 4 * ((5 * 1024 * 1024 + 2) // 3):
            raise _Failure("invalid_argument", "image_data must be base64 of at most 5120 KB decoded.")
        try:
            image = base64.b64decode(image_data, validate=True)
        except (ValueError, binascii.Error):
            raise _Failure("invalid_argument", "image_data must be strict base64.") from None
        if len(image) > 5 * 1024 * 1024 or not image.startswith(magic[image_mime_type]):
            raise _Failure("invalid_argument", "Image must match its mime signature and be at most 5120 KB.")
        arguments["image_data"] = {"sha256": hashlib.sha256(image).hexdigest(), "size_bytes": len(image)}
    _check_confirm(confirm)
    state = gads_client.search_stream(cid, "SELECT customer.id, customer.status FROM customer")
    if not state:
        raise _Failure("not_found", f"No customer with ID {cid} was found.")
    client = gads_client.build_client()
    op = client.get_type("AssetOperation")
    op.create = common
    change = {"asset_type": asset_type, "name": name, **common}
    if asset_type == "IMAGE":
        op.create.image_asset.data = image
        op.create.image_asset.mime_type = getattr(client.enums.MimeTypeEnum, image_mime_type)
        change.update(image_mime_type=image_mime_type, **arguments["image_data"])
    else:
        destination = getattr(op.create, asset_type.lower() + "_asset")
        for field in kinds[asset_type]:
            value = arguments[field]
            if value is not None:
                api_field = field.removeprefix("sitelink_").removeprefix("structured_snippet_")
                if field == "structured_snippet_values":
                    destination.values.extend(value)
                else:
                    setattr(destination, api_field, value)
                change[field] = value
    head = {"customer_id": cid, "changes": [change]}
    return _review(
        "create_asset", arguments, confirm, gate, f"customers/{cid}", state, head,
        lambda validate_only: _mutate(client, "AssetService", "mutate_assets",
                                      "MutateAssetsRequest", cid, [op], validate_only))


WRITE_TOOLS: tuple[tuple[str, str, Callable[..., dict[str, Any]], bool], ...] = (
    ("set_keyword_status", "Enable or pause keywords", set_keyword_status, False),
    ("set_ad_status", "Enable or pause ads", set_ad_status, False),
    ("update_campaign_schedule", "Change campaign start or end date", update_campaign_schedule,
     False),
    ("set_conversion_action_goal", "Make a conversion action primary or secondary",
     set_conversion_action_goal, False),
    ("add_placement_exclusions", "Exclude placements from a campaign", add_placement_exclusions,
     False),
    ("update_asset_group_assets", "Link or unlink Performance Max asset group assets",
     update_asset_group_assets, True),
    ("manage_labels", "Create, update or remove labels", manage_labels, True),
    ("manage_label_associations", "Attach or remove labels", manage_label_associations, True),
    ("create_asset", "Create an unlinked asset", create_asset, False),
)


def _bind_gate(fn: Callable[..., Any], gate: Callable[[], Any]) -> Callable[..., Any]:
    def tool(*args, **kwargs):
        return fn(*args, **kwargs, gate=gate)

    # FastMCP builds the input schema from __signature__; the gate is not an argument.
    signature = inspect.signature(fn, eval_str=True)
    tool.__signature__ = signature.replace(
        parameters=[p for p in signature.parameters.values() if p.name != "gate"])
    tool.__name__ = fn.__name__
    tool.__doc__ = fn.__doc__
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


def register_writes(server, gate, prefix: str = "", provider_factory=None) -> int:
    """Add every tool in WRITE_TOOLS to a host FastMCP and return how many were added.

    gate() is called before every confirmed write, never for a dry run. It returns None to
    allow the write, or an error dict that the tool returns unchanged without sending anything.
    provider_factory works as in register().
    """
    from mcp.types import ToolAnnotations

    if not callable(gate):
        raise TypeError("gate must be a callable that returns None or an error dict")
    for name, title, fn, destructive in WRITE_TOOLS:
        server.add_tool(
            _guarded(_bind_gate(fn, gate), provider_factory),
            name=prefix + name,
            title=title,
            description=inspect.cleandoc(fn.__doc__),
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=destructive,
                                        idempotentHint=False, openWorldHint=True),
        )
    return len(WRITE_TOOLS)


def main() -> None:
    from importlib.metadata import PackageNotFoundError, version

    from mcp.server.fastmcp import FastMCP

    server = FastMCP("google-ads-agents")
    # FastMCP takes no version argument; without this the handshake reports the mcp SDK version.
    try:
        server._mcp_server.version = version("google-ads-agents")
    except PackageNotFoundError:
        server._mcp_server.version = "0.0.0+source"
    register(server)
    server.run()


if __name__ == "__main__":
    main()
