"""GoogleAdsClient backed by gcloud user ADC.

The google-ads-python library normally expects either a refresh token in a
config file or a service-account JSON. We bypass both by constructing the
client from in-memory credentials returned by google.auth.default(). The
developer token and optional login-customer-id come from the active local
profile written by gads_auth.
"""

from __future__ import annotations

from typing import Any

API_VERSION = "v25"


def build_client():
    """Return a configured GoogleAdsClient for the active credential provider."""
    import gads_provider
    from google.ads.googleads.client import GoogleAdsClient

    provider = gads_provider.get_active_provider()
    # load_from_dict does not accept a live credentials object; the GoogleAdsClient
    # constructor does. Pass in-memory credentials (ADC or user OAuth) directly.
    login = provider.get_login_customer_id()
    kwargs: dict[str, Any] = {
        "credentials": provider.get_credentials(),
        "developer_token": provider.get_developer_token(),
        "use_proto_plus": True,
        "version": API_VERSION,
    }
    if login:
        kwargs["login_customer_id"] = login
    return GoogleAdsClient(**kwargs)


def search_stream(customer_id: str, query: str) -> list[dict[str, Any]]:
    """Run a GAQL query and return a flat list of row dicts."""
    client = build_client()
    svc = client.get_service("GoogleAdsService")
    rows: list[dict[str, Any]] = []
    for batch in svc.search_stream(customer_id=customer_id.replace("-", ""), query=query):
        for row in batch.results:
            rows.append(_row_to_dict(row))
    return rows


def _row_to_dict(row) -> dict[str, Any]:
    """Shallow flatten of a GoogleAdsRow. Only walks fields populated on the row."""
    return {field.name: _msg_to_dict(value) for field, value in row._pb.ListFields()}


def _msg_to_dict(value) -> Any:
    from google.protobuf.json_format import MessageToDict

    if hasattr(value, "DESCRIPTOR"):
        data = MessageToDict(value, preserving_proto_field_name=True)
        return _restore_reserved_names(data, value.DESCRIPTOR)
    return value


def _restore_reserved_names(data, descriptor):
    """Use API names for Python-keyword fields while keeping snake_case keys.

    The Python schema calls fields such as `type` `type_`; preserving proto
    names otherwise makes real responses disagree with the adapters' fixtures.
    """
    if not isinstance(data, dict):
        return data
    result = {}
    for key, value in data.items():
        field = descriptor.fields_by_name.get(key)
        name = key
        if field is not None:
            if key.endswith("_") and field.json_name == key[:-1]:
                name = field.json_name
            nested = field.message_type
            if nested is not None:
                if nested.GetOptions().map_entry:
                    message = nested.fields_by_name["value"].message_type
                    if message is not None:
                        value = {k: _restore_reserved_names(v, message) for k, v in value.items()}
                elif isinstance(value, list):
                    value = [_restore_reserved_names(v, nested) for v in value]
                else:
                    value = _restore_reserved_names(value, nested)
        result[name] = value
    return result
