"""Creative wizard — brief parsing, prompt scaffolding, attach validation.

API-touching paths (upload, attach mutate) are not covered here —
they're integration concerns.
"""

from __future__ import annotations

import pytest

import gads_creative


# ---------- brief extraction ----------

_SAMPLE_HTML = """
<!doctype html>
<html>
<head>
  <title>Acme Widgets — Industrial widgets since 1992</title>
  <meta name="description" content="The fastest widgets in the business. Same-day shipping.">
  <meta property="og:title" content="Acme Widgets" />
  <meta property="og:description" content="Industrial widgets you can trust">
  <meta property="og:image" content="https://example.com/hero.jpg">
  <style>
    body { background: #FFFFFF; color: #111111; }
    .accent { color: #D24B22; border: 1px solid #1F73B7; }
  </style>
</head>
<body>
  <h1>The strongest widgets you'll ever buy</h1>
  <h2>Built in Ohio</h2>
  <h2>Free shipping on orders over $50</h2>
  <h2>30-year warranty</h2>
  <p>We've been making widgets since 1992. Trusted by NASA and your local hardware store.</p>
</body>
</html>
"""


def test_build_brief_parses_known_fields(monkeypatch):
    monkeypatch.setattr(gads_creative, "_fetch_site",
                        lambda url: (True, _SAMPLE_HTML, ""))
    brief = gads_creative.build_brief("https://acme.example")
    assert brief["reachable"] is True
    assert brief["title"].startswith("Acme Widgets")
    assert "fastest widgets" in brief["meta_description"]
    assert brief["og"]["image"] == "https://example.com/hero.jpg"
    assert brief["h1"] == ["The strongest widgets you'll ever buy"]
    assert "Built in Ohio" in brief["h2"]


def test_build_brief_handles_unreachable(monkeypatch):
    monkeypatch.setattr(gads_creative, "_fetch_site",
                        lambda url: (False, "", "DNS error"))
    brief = gads_creative.build_brief("https://nope.example")
    assert brief["reachable"] is False
    assert brief["error"] == "DNS error"


def test_extract_hex_colors_filters_extremes():
    html = """
    body { color: #ffffff; background: #FFFFFF; border: #000000; }
    .a { color: #D24B22; }
    .b { color: #1F73B7; }
    .c { color: #d24b22; }   /* dup, different case */
    """
    colors = gads_creative._extract_hex_colors(html)
    assert "#d24b22" in colors
    assert "#1f73b7" in colors
    # Both near-white and near-black are filtered
    assert "#ffffff" not in colors
    assert "#000000" not in colors
    # Dedup: lowercased same hex isn't repeated
    assert colors.count("#d24b22") == 1


def test_strip_tags_and_collapse():
    s = gads_creative._collapse(gads_creative._strip_tags(
        "<p>Hello   <b>world</b></p>\n<p>Again</p>"))
    assert s == "Hello world Again"


# ---------- prompt scaffold ----------

def test_prompt_scaffold_carries_brief_hints():
    brief = {
        "title": "Acme Widgets",
        "meta_description": "Industrial widgets you can trust",
        "h1": ["Strongest widgets"],
        "h2": ["Built in Ohio"],
        "hex_colors": ["#d24b22", "#1f73b7", "#000033"],
    }
    scaffold = gads_creative.prompt_scaffold(brief)
    assert scaffold["hints"]["brand"] == "Acme Widgets"
    assert "Industrial widgets" in scaffold["hints"]["tagline"]
    assert scaffold["hints"]["palette"] == ["#d24b22", "#1f73b7", "#000033"]


def test_prompt_scaffold_emits_all_ad_formats():
    scaffold = gads_creative.prompt_scaffold({"title": "x"})
    field_types = [f["field_type"] for f in scaffold["formats"]]
    assert set(field_types) == {
        "MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE",
        "LOGO", "LANDSCAPE_LOGO",
    }


def test_prompt_scaffold_empty_prompts_for_agent_to_fill():
    scaffold = gads_creative.prompt_scaffold({"title": "x"})
    for f in scaffold["formats"]:
        assert f["prompt"] == ""
        assert "no text in image" in f["negative_prompt"]


# ---------- attach validation ----------

def test_attach_to_asset_group_rejects_bad_field_type():
    with pytest.raises(ValueError):
        gads_creative.attach_to_asset_group("1", "ag1", "asset/1",
                                            "SITELINK", validate_only=True)


def test_attach_to_search_campaign_rejects_bad_field_type():
    with pytest.raises(ValueError):
        gads_creative.attach_to_search_campaign("1", "c1", "asset/1",
                                                 "MARKETING_IMAGE", validate_only=True)
