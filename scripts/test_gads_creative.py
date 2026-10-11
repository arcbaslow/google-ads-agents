"""Creative parsing and reviewed writes with real v25 messages."""

from __future__ import annotations

import json
from unittest.mock import Mock

import gads_client
import gads_creative
import pytest
from gads_mutate import MutationCancelled
from google.ads.googleads.client import GoogleAdsClient
from google.api_core.exceptions import NotFound
from google.auth.credentials import AnonymousCredentials
from google.oauth2.credentials import Credentials as UserCredentials

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


@pytest.fixture
def api(monkeypatch, tmp_path):
    types = GoogleAdsClient(credentials=AnonymousCredentials(), developer_token="test",
                           use_proto_plus=True, version="v25")
    services = {}

    def service(name):
        return services.setdefault(name, Mock())

    client = Mock(get_type=types.get_type, enums=types.enums, get_service=service,
                  credentials=UserCredentials(token="test"))
    monkeypatch.setattr(gads_client, "build_client", Mock(return_value=client))
    monkeypatch.setattr("builtins.input", lambda: "y")
    path = tmp_path / "video.mp4"
    path.write_bytes(b"private-video-bytes")
    upload_response = types.get_type("CreateYouTubeVideoUploadResponse")
    upload_response.resource_name = "customers/123/youTubeVideoUploads/42"
    service("YouTubeVideoUploadService").create_you_tube_video_upload.return_value = upload_response
    response = types.get_type("MutateAssetsResponse")
    response.results.append({"resource_name": "customers/123/assets/7"})
    service("AssetService").mutate_assets.return_value = response
    service("AdService").mutate_ads.return_value = types.get_type("MutateAdsResponse")
    row = types.get_type("GoogleAdsRow")
    row.you_tube_video_upload.state = "PROCESSED"
    row.you_tube_video_upload.video_id = "Abc_def-123"
    row.ad_group_ad.ad.type_ = "VIDEO_RESPONSIVE_AD"
    row.ad_group_ad.ad.resource_name = "customers/123/ads/99"
    row.ad_group_ad.ad_group = "customers/123/adGroups/8"
    row.ad_group_ad.status = "PAUSED"
    row.ad_group.status = "ENABLED"
    row.campaign.status = "ENABLED"
    row.campaign.advertising_channel_type = "VIDEO"
    service("GoogleAdsService").search.return_value = [row]
    return client, row, service, path


def test_upload_reviews_and_polling(api, monkeypatch, capsys):
    client, row, service, path = api
    upload = service("YouTubeVideoUploadService").create_you_tube_video_upload
    assets = service("AssetService").mutate_assets
    pending = client.get_type("GoogleAdsRow")
    pending.you_tube_video_upload.state = "PENDING"
    service("GoogleAdsService").search.side_effect = [[pending], [row]]
    sleep = Mock()
    monkeypatch.setattr(gads_creative.time, "sleep", sleep)
    reviews = []

    def approve():
        err = capsys.readouterr().err
        document, prompt = err.rsplit("\n", 2)[:2]
        preview = json.loads(document)
        reviews.append(preview)
        assert prompt.endswith("y/N")
        assets.assert_not_called()
        if len(reviews) == 1:
            upload.assert_not_called()
            assert preview["file"] == str(path.resolve())
            assert preview["size_bytes"] == path.stat().st_size
            assert preview["privacy"] == "UNLISTED"
            assert "private-video-bytes" not in err
        else:
            assert upload.call_count == 1
            assert preview["operations"][0]["create"]["youtube_video_asset"]["youtube_video_id"] == "Abc_def-123"
        return "y"

    def send(**kwargs):
        assert kwargs["stream"].read() == b"private-video-bytes"
        assert "validate_only" not in kwargs
        assert kwargs["retry"] is None
        assert kwargs["you_tube_video_upload"].video_title == "Title"
        assert kwargs["you_tube_video_upload"].video_privacy.name == "UNLISTED"
        return upload.return_value

    upload.side_effect = send
    monkeypatch.setattr("builtins.input", approve)
    result = gads_creative.upload_video("123", path, "Title", apply=True)
    assert result["status"] == "applied"
    assert result["video_id"] == "Abc_def-123"
    assert result["upload_resource"].endswith("/42")
    assert len(reviews) == 2
    sleep.assert_called_once_with(10)
    assert [c.kwargs["validate_only"] for c in assets.call_args_list] == [True, False]
    assert upload.call_args.kwargs["stream"].closed


@pytest.mark.parametrize("answer", ["n", EOFError(), OSError()])
def test_upload_cancelled_before_send(api, monkeypatch, answer):
    _, _, service, path = api
    monkeypatch.setattr("builtins.input", Mock(side_effect=answer if isinstance(answer, Exception) else None,
                                               return_value=answer))
    with pytest.raises(MutationCancelled):
        gads_creative.upload_video("123", path, "Title", apply=True)
    service("YouTubeVideoUploadService").create_you_tube_video_upload.assert_not_called()
    service("AssetService").mutate_assets.assert_not_called()


@pytest.mark.parametrize("apply", [True, False])
def test_public_without_channel_before_client(api, apply):
    _, _, _, path = api
    with pytest.raises(ValueError, match="PUBLIC"):
        gads_creative.upload_video("123", path, "Title", privacy="PUBLIC", apply=apply)
    gads_client.build_client.assert_not_called()


def test_upload_noop_and_file_checks(api):
    _, _, _, path = api
    assert gads_creative.upload_video("123", path, "Title")["status"] == "no_op"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="non-empty"):
        gads_creative.upload_video("123", path, "Title")
    with pytest.raises(ValueError, match="exist"):
        gads_creative.upload_video("123", path.with_name("missing"), "Title")
    gads_client.build_client.assert_not_called()


@pytest.mark.parametrize("state", ["FAILED", "REJECTED", "UNAVAILABLE"])
def test_upload_terminal_failure(api, state):
    _, row, service, path = api
    row.you_tube_video_upload.state = state
    result = gads_creative.upload_video("123", path, "Title", apply=True)
    assert result["status"] == "upload_failed"
    assert result["state"] == state
    assert result["upload_resource"].endswith("/42")
    service("AssetService").mutate_assets.assert_not_called()


def test_upload_timeout(api, monkeypatch):
    _, row, service, path = api
    row.you_tube_video_upload.state = "UPLOADED"
    now = [0]
    monkeypatch.setattr(gads_creative.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(gads_creative.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    result = gads_creative.upload_video("123", path, "Title", apply=True)
    assert result["status"] == "upload_timeout"
    assert result["upload_resource"].endswith("/42")
    assert now[0] == 600
    assert service("GoogleAdsService").search.call_count == 60
    service("AssetService").mutate_assets.assert_not_called()


@pytest.mark.parametrize("failure", ["cancel", "validate", "apply", "poll"])
def test_upload_partial_failure_retains_resource(api, monkeypatch, failure):
    _, _, service, path = api
    assets = service("AssetService").mutate_assets
    if failure == "cancel":
        monkeypatch.setattr("builtins.input", Mock(side_effect=["y", "n"]))
    elif failure == "poll":
        service("GoogleAdsService").search.side_effect = RuntimeError("private provider error")
    elif failure == "validate":
        assets.side_effect = RuntimeError("private provider error")
    else:
        assets.side_effect = [assets.return_value, RuntimeError("private provider error")]
    result = gads_creative.upload_video("123", path, "Title", apply=True)
    assert result["upload_resource"].endswith("/42")
    assert "private provider error" not in json.dumps(result)
    if failure == "poll":
        assert result["status"] == "upload_poll_failed"
    else:
        assert result["status"] == "uploaded_without_asset"
        assert result["video_id"] == "Abc_def-123"
        assert "create-video-asset" in result["hint"]
        assert "RemoveYouTubeVideoUpload" in result["hint"]
    if failure in {"cancel", "poll"}:
        assets.assert_not_called()


def test_brand_channel_user_oauth(api):
    client, _, service, path = api
    result = gads_creative.upload_video("123", path, "Title", channel_id="UCbrand",
                                       privacy="PUBLIC", apply=True)
    assert result["status"] == "applied"
    upload = service("YouTubeVideoUploadService").create_you_tube_video_upload
    assert upload.call_args.kwargs["you_tube_video_upload"].channel_id == "UCbrand"
    assert upload.call_args.kwargs["you_tube_video_upload"].video_privacy.name == "PUBLIC"
    upload.reset_mock()
    client.credentials = AnonymousCredentials()
    with pytest.raises(ValueError, match="user OAuth"):
        gads_creative.upload_video("123", path, "Title", channel_id="UCbrand", apply=True)
    upload.assert_not_called()


@pytest.mark.parametrize("video_id", ["short", "Abc_def-12345", "Abc_def!1234", "https://youtu.be/Abc_def-1234"])
def test_video_asset_bad_id_before_client(api, video_id):
    with pytest.raises(ValueError, match="11"):
        gads_creative.create_video_asset("123", video_id, "Name", False)
    gads_client.build_client.assert_not_called()


@pytest.mark.parametrize("dry", [True, False])
def test_video_asset(api, dry):
    _, _, service, _ = api
    result = gads_creative.create_video_asset("123", "Abc_def-123", "Name", dry)
    assert result["status"] == ("validated" if dry else "applied")
    calls = service("AssetService").mutate_assets.call_args_list
    assert [c.kwargs["validate_only"] for c in calls] == ([True] if dry else [True, False])
    assert calls[0].kwargs["operations"][0].create.youtube_video_asset.youtube_video_id == "Abc_def-123"


VRA_INPUT = {"videos": ["customers/123/assets/7"], "business_name": "Brand",
             "logo_images": ["customers/123/assets/8"], "headlines": ["Headline"],
             "long_headlines": ["Long headline"], "descriptions": ["Description"],
             "call_to_actions": ["Buy"], "companion_banners": ["customers/123/assets/9"],
             "breadcrumb1": "shop", "breadcrumb2": "sale"}
RDA_INPUT = {"marketing_images": ["customers/123/assets/1"],
             "square_marketing_images": ["customers/123/assets/2"],
             "logo_images": ["customers/123/assets/3"], "square_logo_images": [],
             "headlines": ["Headline"], "long_headline": "Long headline",
             "descriptions": ["Description"], "youtube_videos": ["customers/123/assets/7"],
             "business_name": "Brand", "main_color": "#ffffff", "accent_color": "#000000",
             "allow_flexible_color": False, "call_to_action_text": "Buy", "price_prefix": "From",
             "promo_text": "Sale", "format_setting": "NATIVE",
             "control_spec": {"enable_asset_enhancements": False, "enable_autogen_video": True}}


@pytest.mark.parametrize("payload,ad_type,channel,prefix", [
    (VRA_INPUT, "VIDEO_RESPONSIVE_AD", "VIDEO", "video_responsive_ad"),
    (RDA_INPUT, "RESPONSIVE_DISPLAY_AD", "DISPLAY", "responsive_display_ad"),
])
def test_edit_ad_exact_masks(api, payload, ad_type, channel, prefix):
    _, row, service, _ = api
    row.ad_group_ad.ad.type_ = ad_type
    row.campaign.advertising_channel_type = channel
    result = gads_creative.edit_ad("123", "99", payload, False)
    calls = service("AdService").mutate_ads.call_args_list
    assert [c.kwargs["validate_only"] for c in calls] == [True, False]
    op = calls[-1].kwargs["operations"][0]
    singular = {"business_name": "text"} if channel == "VIDEO" else {"long_headline": "text"}
    expected = {f"{prefix}.{key}" for key in payload if key not in singular and key != "control_spec"}
    expected |= {f"{prefix}.{key}.{leaf}" for key, leaf in singular.items()}
    if "control_spec" in payload:
        expected |= {f"{prefix}.control_spec.{key}" for key in payload["control_spec"]}
    assert set(op.update_mask.paths) == expected
    assert set(result["field_mask"]) == expected
    assert op.update.resource_name == "customers/123/ads/99"
    info = getattr(op.update, prefix)
    assert info.headlines[0].text == "Headline"
    if channel == "VIDEO":
        assert info.business_name.text == "Brand"
        assert info.videos[0].asset == "customers/123/assets/7"
    else:
        assert info.business_name == "Brand"
        assert info.allow_flexible_color is False


@pytest.mark.parametrize("ad_type,channel", [("VIDEO_AD", "VIDEO"),
                                            ("RESPONSIVE_SEARCH_AD", "SEARCH"),
                                            ("VIDEO_RESPONSIVE_AD", "DISPLAY"),
                                            ("RESPONSIVE_DISPLAY_AD", "VIDEO")])
def test_edit_ad_type_channel_guard(api, ad_type, channel):
    _, row, service, _ = api
    row.ad_group_ad.ad.type_ = ad_type
    row.campaign.advertising_channel_type = channel
    with pytest.raises(ValueError, match=f"{ad_type}.*{channel}"):
        gads_creative.edit_ad("123", "99", {"headlines": ["Headline"]}, False)
    service("AdService").mutate_ads.assert_not_called()


@pytest.mark.parametrize("missing", ["videos", "business_name", "logo_images"])
def test_edit_video_required_fields(api, missing):
    payload = {k: v for k, v in VRA_INPUT.items() if k != missing}
    with pytest.raises(ValueError, match="require videos, business_name and logo_images"):
        gads_creative.edit_ad("123", "99", payload, False)
    gads_client.build_client.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"final_urls": ["https://example.test"]},
    {"videos": ["customers/999/assets/1"]}, {"headlines": "x"}, {"headlines": [{"text": "x"}]},
    {"allow_flexible_color": 1}, {"format_setting": "UNKNOWN"},
    {"control_spec": {"enable_autogen_video": 1}}, {"logo_images": ["bad"]}])
def test_edit_invalid_shape_before_client(api, payload):
    with pytest.raises(ValueError):
        gads_creative.edit_ad("123", "99", payload, False)
    gads_client.build_client.assert_not_called()


def test_edit_not_found(api):
    _, _, service, _ = api
    service("GoogleAdsService").search.return_value = []
    with pytest.raises(NotFound, match="not_found"):
        gads_creative.edit_ad("123", "99", VRA_INPUT, False)
    service("AdService").mutate_ads.assert_not_called()


def test_upload_cli_no_validation_mode(api, monkeypatch):
    _, _, _, path = api
    monkeypatch.setattr("sys.argv", ["creative", "upload-video", "--customer", "123", "--file", str(path),
                                     "--title", "Title", "--validate-only"])
    with pytest.raises(SystemExit) as exc:
        gads_creative.main()
    assert exc.value.code == 2
    gads_client.build_client.assert_not_called()


@pytest.mark.parametrize("json_mode", [True, False])
def test_edit_cli_channel_error_visible(api, monkeypatch, tmp_path, capsys, json_mode):
    _, row, service, _ = api
    row.ad_group_ad.ad.type_ = "RESPONSIVE_SEARCH_AD"
    row.campaign.advertising_channel_type = "SEARCH"
    path = tmp_path / "edit.json"
    path.write_text(json.dumps({"headlines": ["Headline"]}))
    args = ["creative", "edit-ad", "--customer", "123", "--ad-id", "99", "--input", str(path), "--apply"]
    monkeypatch.setattr("sys.argv", args + (["--json"] if json_mode else []))
    assert gads_creative.main() == 3
    output = capsys.readouterr().out
    assert "RESPONSIVE_SEARCH_AD" in output and "SEARCH" in output
    service("AdService").mutate_ads.assert_not_called()


def test_display_partial_update_and_video_required_after_read(api):
    _, row, service, _ = api
    with pytest.raises(ValueError, match="require videos"):
        gads_creative.edit_ad("123", "99", {"headlines": ["Headline"]}, True)
    service("AdService").mutate_ads.assert_not_called()
    row.ad_group_ad.ad.type_ = "RESPONSIVE_DISPLAY_AD"
    row.campaign.advertising_channel_type = "DISPLAY"
    gads_creative.edit_ad("123", "99", {"headlines": ["Headline"]}, True)
    mutation = service("AdService").mutate_ads
    assert mutation.call_count == 1
    op = mutation.call_args.kwargs["operations"][0]
    assert list(op.update_mask.paths) == ["responsive_display_ad.headlines"]
    assert mutation.call_args.kwargs["validate_only"] is True


@pytest.mark.parametrize("action,args", [
    ("create-video-asset", ["--video-id", "Abc_def-123", "--name", "Video"]),
    ("edit-ad", ["--ad-id", "99", "--input", "unused.json"]),
])
def test_new_creative_cli_noop(api, monkeypatch, capsys, action, args):
    monkeypatch.setattr("sys.argv", ["creative", action, "--customer", "123", *args, "--json"])
    assert gads_creative.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_op"
    gads_client.build_client.assert_not_called()
