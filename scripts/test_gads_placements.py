"""Placement classification against the bundled rules file."""

from __future__ import annotations

from pathlib import Path

import gads_placements

RULES = Path(__file__).parent / "placements_rules.json"


def _rules():
    return gads_placements.load_rules(RULES)


def test_loads_rules_file():
    rules = _rules()
    assert len(rules) > 5
    cats = {r["category"] for r in rules}
    assert {"scam", "bot", "politics", "religion", "games", "gambling", "adult", "mfa"} <= cats


def test_gambling_classification():
    rules = _rules()
    assert gads_placements.classify("topcasino-bonuses.com", rules) == "gambling"
    assert gads_placements.classify("sportsbook of the week", rules) == "gambling"


def test_adult_classification():
    rules = _rules()
    assert gads_placements.classify("pornhub.com /channels", rules) == "adult"
    assert gads_placements.classify("XXX something", rules) == "adult"


def test_politics_classification():
    rules = _rules()
    assert gads_placements.classify("breitbart.com", rules) == "politics"
    assert gads_placements.classify("election 2026 coverage", rules) == "politics"


def test_religion_classification():
    rules = _rules()
    assert gads_placements.classify("bible study weekly", rules) == "religion"
    assert gads_placements.classify("godtube.com", rules) == "religion"


def test_games_classification():
    rules = _rules()
    assert gads_placements.classify("mobileapp://com.king.candycrush", rules) == "games"
    assert gads_placements.classify("kongregate.com", rules) == "games"


def test_scam_tld_match():
    rules = _rules()
    assert gads_placements.classify("crazydeals.tk/page", rules) == "scam"


def test_safe_site_returns_none():
    rules = _rules()
    assert gads_placements.classify("nytimes.com", rules) is None
    assert gads_placements.classify("github.com/anthropic", rules) is None


def test_empty_text_returns_none():
    rules = _rules()
    assert gads_placements.classify("", rules) is None
    assert gads_placements.classify(None, rules) is None
