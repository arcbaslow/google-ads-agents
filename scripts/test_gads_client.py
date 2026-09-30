import gads_client
import gads_demographics
import gads_recommendations
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.auth.credentials import AnonymousCredentials


@pytest.fixture
def types():
    return GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                           use_proto_plus=True, version=gads_client.API_VERSION)


@pytest.mark.parametrize("dimension,enum,value", [
    ("age_range", "AgeRangeTypeEnum", "AGE_RANGE_25_34"),
    ("gender", "GenderTypeEnum", "FEMALE"),
])
def test_real_demographic_rows_keep_their_bucket(types, monkeypatch, dimension, enum, value):
    row = types.get_type("GoogleAdsRow")
    row.campaign.id = 1
    getattr(row.ad_group_criterion, dimension).type_ = getattr(getattr(types.enums, enum), value)
    row.metrics.cost_micros = 1234567
    row.metrics.conversions = 0.5
    data = gads_client._row_to_dict(row)
    assert data["ad_group_criterion"][dimension] == {"type": value}
    assert data["metrics"] == {"cost_micros": "1234567", "conversions": 0.5}
    monkeypatch.setattr(gads_client, "search_stream", lambda c, q: [data])
    read = gads_demographics.by_age if dimension == "age_range" else gads_demographics.by_gender
    assert read("123")["buckets"][0]["bucket"] == value


def test_real_recommendation_is_grouped_by_its_type(types, monkeypatch):
    row = types.get_type("GoogleAdsRow")
    row.recommendation.type_ = types.enums.RecommendationTypeEnum.KEYWORD
    row.recommendation.resource_name = "customers/123/recommendations/7"
    row.recommendation.impact.base_metrics.cost_micros = 5000000
    monkeypatch.setattr(gads_client, "search_stream", lambda c, q: [gads_client._row_to_dict(row)])
    result = gads_recommendations.fetch("123")
    assert set(result["by_type"]) == {"KEYWORD"}
    assert result["by_type"]["KEYWORD"][0]["base"]["cost"] == 5
