"""Offline schema checks; these do not prove GAQL field compatibility."""

import inspect
import re

import gads_assets
import gads_client
import gads_query
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials

QUERIES = {
    name: fn() if not inspect.signature(fn).parameters else fn("2026-09-01", "2026-09-28")
    for name, fn in inspect.getmembers(gads_query, inspect.isfunction)
}
QUERIES.update(rsa=gads_assets.RSA_QUERY, pmax_inventory=gads_assets.PMAX_ASSET_QUERY)


@pytest.mark.parametrize("query", QUERIES.values(), ids=QUERIES.keys())
def test_query_resource_and_field_names_exist_in_selected_schema(query):
    client = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                            use_proto_plus=True, version=gads_client.API_VERSION)
    row = client.get_type("GoogleAdsRow")._pb.DESCRIPTOR
    resource = re.search(r"\bFROM\s+(\w+)", query).group(1)
    assert resource in row.fields_by_name
    for path in re.findall(r"\b[a-z_]+(?:\.[a-z_][a-z_0-9]*)+", query):
        descriptor = row
        for part in path.split("."):
            # Python protobuf keywords have a trailing underscore.
            field = descriptor.fields_by_name.get(part) or descriptor.fields_by_name.get(part + "_")
            assert field is not None, f"{gads_client.API_VERSION}: missing {path}"
            descriptor = field.message_type


def test_video_and_shopping_queries_use_current_reporting_names():
    for query in [QUERIES["youtube_campaigns"], QUERIES["display_campaigns"]]:
        assert "metrics.video_trueview_views" in query
        assert "metrics.video_views" not in query
    assert "metrics.video_trueview_view_rate" in QUERIES["youtube_campaigns"]
    assert "campaign.shopping_setting.feed_label" in QUERIES["shopping_campaigns"]
    assert "sales_country" not in QUERIES["shopping_campaigns"]
