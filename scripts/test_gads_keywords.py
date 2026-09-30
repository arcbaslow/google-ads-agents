import json
from unittest.mock import Mock

import gads_keywords
import pytest
from google.ads.googleads.v25.services.types.keyword_plan_idea_service import (
    GenerateKeywordIdeaResult,
    GenerateKeywordIdeasRequest,
)


@pytest.fixture
def keyword_service(monkeypatch):
    service = Mock()
    service.generate_keyword_ideas.return_value = []
    constants = Mock()
    constants.language_constant_path.side_effect = lambda id: f"languageConstants/{id}"
    constants.geo_target_constant_path.side_effect = lambda id: f"geoTargetConstants/{id}"
    client = Mock()
    client.get_service.side_effect = {
        "KeywordPlanIdeaService": service, "GoogleAdsService": constants,
    }.__getitem__
    client.get_type.side_effect = lambda name: GenerateKeywordIdeasRequest()
    build = Mock(return_value=client)
    monkeypatch.setattr(gads_keywords.gads_client, "build_client", build)
    return service, build


@pytest.mark.parametrize("language,geo", [
    ("it", "US"), ("en", "KZ"), ("1000", "US"), ("en", "2840"),
    ("en_US", "US"), ("", "US"), ("en", ""),
])
def test_unsupported_locale_never_builds_client(keyword_service, language, geo):
    _, build = keyword_service
    with pytest.raises(ValueError, match="Unsupported (language|geo)"):
        gads_keywords.keyword_ideas("123", ["seed"], language, geo)
    build.assert_not_called()


@pytest.mark.parametrize("language,geo,language_id,geo_id", [
    ("en", "US", "1000", "2840"), ("es", "GB", "1003", "2826"),
    ("de", "CA", "1001", "2124"), ("fr", "AU", "1002", "2036"),
    (" EN ", " us ", "1000", "2840"),
])
def test_supported_locale_matches_request_and_output(
    keyword_service, language, geo, language_id, geo_id,
):
    service, _ = keyword_service
    result = gads_keywords.keyword_ideas("123", ["seed"], language, geo)
    request = service.generate_keyword_ideas.call_args.kwargs["request"]
    assert request.language == f"languageConstants/{language_id}"
    assert list(request.geo_target_constants) == [f"geoTargetConstants/{geo_id}"]
    assert request.customer_id == "123"
    assert list(request.keyword_seed.keywords) == ["seed"]
    assert request.include_adult_keywords is False
    assert result == {
        "seeds": ["seed"], "language": language.strip().lower(),
        "geo": geo.strip().upper(), "ideas": [],
    }


@pytest.mark.parametrize("option,value", [("--language", "it"), ("--geo", "KZ")])
def test_cli_rejects_unsupported_locale(keyword_service, monkeypatch, capsys, option, value):
    _, build = keyword_service
    monkeypatch.setattr("sys.argv", [
        "gads_keywords", "--customer", "123", "--seeds", "seed", option, value,
    ])
    with pytest.raises(SystemExit) as exc:
        gads_keywords.main()
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    build.assert_not_called()


def test_cli_normalizes_locale_and_retains_idea_metrics(keyword_service, monkeypatch, capsys):
    service, _ = keyword_service
    service.generate_keyword_ideas.return_value = [
        GenerateKeywordIdeaResult(text="smaller", keyword_idea_metrics={
            "avg_monthly_searches": 10, "competition": "LOW",
            "low_top_of_page_bid_micros": 1234567,
            "high_top_of_page_bid_micros": 2500000,
        }),
        GenerateKeywordIdeaResult(text="larger", keyword_idea_metrics={
            "avg_monthly_searches": 100, "competition": "HIGH",
        }),
    ]
    monkeypatch.setattr("sys.argv", [
        "gads_keywords", "--customer", "123-456-7890", "--seeds", "seed",
        "--language", "FR", "--geo", "ca", "--json",
    ])
    assert gads_keywords.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["language"] == "fr"
    assert result["geo"] == "CA"
    assert [idea["text"] for idea in result["ideas"]] == ["larger", "smaller"]
    assert result["ideas"][1] == {
        "text": "smaller", "avg_monthly_searches": 10, "competition": "LOW",
        "low_top_of_page_bid": 1.234567, "high_top_of_page_bid": 2.5,
    }
    request = service.generate_keyword_ideas.call_args.kwargs["request"]
    assert request.customer_id == "1234567890"
    assert request.language == "languageConstants/1002"
    assert list(request.geo_target_constants) == ["geoTargetConstants/2124"]
