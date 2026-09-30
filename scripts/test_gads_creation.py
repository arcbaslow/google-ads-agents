"""Campaign creation validator. Does not hit the API."""

from __future__ import annotations

import gads_creation
import pytest


def _valid_ctx(**overrides):
    base = {
        "business": "Acme Widgets",
        "website": "https://acme.example",
        "goal": "leads",
        "analytics_ok": True,
        "conversions_ok": True,
        "budget": 50,
        "bidding": "MAXIMIZE_CONVERSIONS",
        "geos": ["2840"],
        "languages": ["1000"],
        "channel": "SEARCH",
    }
    base.update(overrides)
    return base


def test_valid_ctx_passes():
    assert gads_creation.validate(_valid_ctx()) == []


def test_missing_fields_listed():
    ctx = _valid_ctx()
    del ctx["website"]
    errs = gads_creation.validate(ctx)
    assert any("missing: website" in e for e in errs)


def test_bad_goal_rejected():
    errs = gads_creation.validate(_valid_ctx(goal="vibes"))
    assert any("goal must be one of" in e for e in errs)


def test_bad_channel_rejected():
    errs = gads_creation.validate(_valid_ctx(channel="SOCIAL"))
    assert any("channel must be one of" in e for e in errs)


def test_analytics_off_blocks_launch():
    errs = gads_creation.validate(_valid_ctx(analytics_ok=False))
    assert any("analytics_ok is false" in e for e in errs)


def test_no_conversions_blocks_when_goal_needs_them():
    errs = gads_creation.validate(_valid_ctx(conversions_ok=False, goal="sales"))
    assert any("conversions_ok is false" in e for e in errs)


def test_no_conversions_ok_for_awareness_goal():
    """Awareness campaigns don't need a primary conversion."""
    errs = gads_creation.validate(_valid_ctx(conversions_ok=False, goal="awareness"))
    assert errs == []


def test_propose_mutate_shape():
    out = gads_creation.propose_mutate(_valid_ctx(budget=42.5))
    assert out["campaign"]["status"] == "PAUSED"
    assert out["campaign"]["campaign_budget"]["amount_micros"] == 42_500_000
    assert out["campaign"]["advertising_channel_type"] == "SEARCH"


def test_propose_mutate_default_name():
    out = gads_creation.propose_mutate(_valid_ctx())
    assert "Acme Widgets" in out["campaign"]["name"]
    assert "leads" in out["campaign"]["name"]


@pytest.mark.parametrize("dry", [True, False])
def test_incomplete_writer_never_constructs_client(monkeypatch, dry):
    from unittest.mock import Mock

    import gads_client
    build = Mock(side_effect=AssertionError("client must not be built"))
    monkeypatch.setattr(gads_client, "build_client", build)
    with pytest.raises(NotImplementedError, match="No budget or campaign was sent"):
        gads_creation.send_mutate("123", gads_creation.propose_mutate(_valid_ctx()), dry)
    build.assert_not_called()


@pytest.mark.parametrize("flag", ["--apply", "--validate-only"])
def test_cli_rejects_writer_before_reading_context(monkeypatch, capsys, flag):
    import json

    monkeypatch.setattr("sys.argv", ["gads_creation", "--customer", "123",
                        "--context-file", "nonexistent.json", flag, "--json"])
    assert gads_creation.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "unsupported"


def test_cli_labels_draft_as_planning_only(monkeypatch, tmp_path, capsys):
    import json

    ctx = tmp_path / "context.json"
    ctx.write_text(json.dumps(_valid_ctx()))
    monkeypatch.setattr("sys.argv", ["gads_creation", "--customer", "123",
                        "--context-file", str(ctx), "--json"])
    assert gads_creation.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "planning_only"
    assert result["campaign_plan"]["campaign"]["status"] == "PAUSED"
