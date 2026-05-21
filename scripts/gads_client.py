"""Build a GoogleAdsClient backed by gcloud user ADC.

The google-ads-python library normally expects either a refresh token in a
config file or a service-account JSON. We bypass that by constructing the
client from in-memory credentials returned by google.auth.default(). Same
shape google.auth uses for ADC, but the developer token and optional
login-customer-id are picked up from our own credentials file.
"""

from __future__ import annotations

from typing import Any

import gads_auth


def _config() -> dict[str, Any]:
    creds = gads_auth.get_credentials()
    cfg: dict[str, Any] = {
        "developer_token": gads_auth.get_developer_token(),
        "use_proto_plus": True,
        "credentials": creds,
    }
    login = gads_auth.get_login_customer_id()
    if login:
        cfg["login_customer_id"] = login
    return cfg


def build_client():
    """Return a configured GoogleAdsClient."""
    from google.ads.googleads.client import GoogleAdsClient

    return GoogleAdsClient.load_from_dict({
        "developer_token": _config()["developer_token"],
        "use_proto_plus": True,
        **({"login_customer_id": _config()["login_customer_id"]} if _config().get("login_customer_id") else {}),
    } | {"credentials": _config()["credentials"]})


def search_stream(customer_id: str, query: str) -> list[dict[str, Any]]:
    """Run a GAQL query and return a flat list of row dicts."""
    from google.ads.googleads.client import GoogleAdsClient  # noqa: F401

    client = build_client()
    svc = client.get_service("GoogleAdsService")
    customer_id = customer_id.replace("-", "")
    stream = svc.search_stream(customer_id=customer_id, query=query)
    rows: list[dict[str, Any]] = []
    for batch in stream:
        for row in batch.results:
            rows.append(_row_to_dict(row))
    return rows


def _row_to_dict(row) -> dict[str, Any]:
    """Shallow flatten of a GoogleAdsRow. Only walks fields populated on the row."""
    out: dict[str, Any] = {}
    for field, value in row._pb.ListFields():
        out[field.name] = _msg_to_dict(value)
    return out


def _msg_to_dict(value) -> Any:
    from google.protobuf.json_format import MessageToDict

    if hasattr(value, "DESCRIPTOR"):
        return MessageToDict(value, preserving_proto_field_name=True)
    return value
