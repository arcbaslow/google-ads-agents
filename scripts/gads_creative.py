"""Creative briefs, assets and bounded ad edits."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import gads_errors
import gads_utils
from gads_apply import WriteInputError, numeric_id, read_campaign
from gads_mutate import review_request, reviewed_mutate
from google.api_core.exceptions import NotFound

USER_AGENT = "gads-agents/0.5"
SITE_FETCH_TIMEOUT = 10
SITE_FETCH_LIMIT_BYTES = 750_000


def _video_asset(client, customer_id: str, video_id: str, name: str,
                 validate_only: bool) -> dict:
    op = client.get_type("AssetOperation")
    op.create.name = name
    op.create.youtube_video_asset.youtube_video_id = video_id
    response = reviewed_mutate(client.get_service("AssetService").mutate_assets,
                               customer_id=customer_id, operations=[op],
                               validate_only=validate_only)
    return {"status": "validated" if validate_only else "applied", "video_id": video_id,
            "asset_resource": response.results[0].resource_name if response.results else None}


def create_video_asset(customer_id: str, video_id: str, name: str,
                       validate_only: bool) -> dict:
    import gads_client

    customer_id = numeric_id(gads_utils.normalize_customer_id(customer_id), "Customer ID")
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise WriteInputError("YouTube video ID must contain exactly 11 letters, digits, _ or -")
    if not isinstance(name, str) or not name.strip():
        raise WriteInputError("Asset name must be non-empty")
    return _video_asset(gads_client.build_client(), customer_id, video_id, name, validate_only)


def upload_video(customer_id: str, file: Path, title: str, description: str = "",
                 channel_id: str | None = None, privacy: str = "UNLISTED",
                 asset_name: str | None = None, apply: bool = False) -> dict:
    import gads_client
    from google.oauth2.credentials import Credentials as UserCredentials

    customer_id = numeric_id(gads_utils.normalize_customer_id(customer_id), "Customer ID")
    path = Path(file).resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise WriteInputError("Video file must exist and be non-empty")
    if privacy not in ("UNLISTED", "PUBLIC") or privacy == "PUBLIC" and not channel_id:
        raise WriteInputError("PUBLIC privacy requires --channel-id; managed channels require UNLISTED")
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise WriteInputError("Video title must contain 1-100 characters")
    if not isinstance(description, str) or len(description) > 5000:
        raise WriteInputError("Video description must contain at most 5000 characters")
    if channel_id is not None and (not isinstance(channel_id, str) or not channel_id.strip()):
        raise WriteInputError("Channel ID must be non-empty when supplied")
    if asset_name is not None and (not isinstance(asset_name, str) or not asset_name.strip()):
        raise WriteInputError("Asset name must be non-empty when supplied")
    preview = {"customer_id": customer_id, "file": str(path), "size_bytes": path.stat().st_size,
               "title": title, "description": description,
               "channel": channel_id or "Google-managed", "privacy": privacy,
               "asset_name": asset_name or title}
    if not apply:
        return {"status": "no_op", **preview, "hint": "Pass --apply; uploads have no API validation"}
    client = gads_client.build_client()
    if channel_id and not isinstance(client.credentials, UserCredentials):
        raise WriteInputError("Brand channels require user OAuth; service accounts are not supported")
    upload = client.get_type("YouTubeVideoUpload")
    upload.video_title = title
    upload.video_description = description
    upload.video_privacy = privacy
    if channel_id:
        upload.channel_id = channel_id
    review_request(preview, "Upload without API validation")
    with path.open("rb") as stream:
        response = client.get_service("YouTubeVideoUploadService").create_you_tube_video_upload(
            customer_id=customer_id, you_tube_video_upload=upload, stream=stream, retry=None)
    resource = response.resource_name
    result = {"customer_id": customer_id, "upload_resource": resource,
              "summary": f"YouTube upload: {resource}"}
    query = f"""SELECT you_tube_video_upload.resource_name, you_tube_video_upload.state,
                      you_tube_video_upload.video_id
               FROM you_tube_video_upload
               WHERE you_tube_video_upload.resource_name = '{resource}'"""
    deadline = time.monotonic() + 600
    try:
        while time.monotonic() < deadline:
            rows = list(client.get_service("GoogleAdsService").search(
                customer_id=customer_id, query=query, retry=None,
                timeout=max(0.001, deadline - time.monotonic())))
            if rows:
                uploaded = rows[0].you_tube_video_upload
                state = uploaded.state.name
                if state in {"FAILED", "REJECTED", "UNAVAILABLE"}:
                    return {**result, "status": "upload_failed", "state": state}
                if state == "PROCESSED":
                    video_id = uploaded.video_id
                    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                        return {**result, "status": "upload_failed", "state": state,
                                "error": "Processed upload did not return a valid video_id"}
                    break
            time.sleep(min(10, max(0, deadline - time.monotonic())))
        else:
            return {**result, "status": "upload_timeout", "error": "Processing exceeded 10 minutes"}
    except Exception as exc:
        return {**result, **gads_errors.describe(exc), "status": "upload_poll_failed"}
    try:
        asset = _video_asset(client, customer_id, video_id, asset_name or title, False)
    except Exception as exc:
        return {**result, **gads_errors.describe(exc), "status": "uploaded_without_asset",
                "video_id": video_id, "error": "Video uploaded; asset creation did not complete.",
                "hint": "Use create-video-asset to finish or RemoveYouTubeVideoUpload to remove the upload.",
                "summary": f"Uploaded {video_id} at {resource}; asset creation unconfirmed. "
                           "Inspect account state, then use create-video-asset "
                           "to finish or RemoveYouTubeVideoUpload to remove the upload."}
    return {**result, **asset, "summary": f"Uploaded {video_id} at {resource}; asset {asset['asset_resource']}"}


def _ad_input(customer_id: str, payload: dict, type_name: str) -> dict:
    from google.ads.googleads.v25.common.types.ad_type_infos import (
        ResponsiveDisplayAdInfo,
        VideoResponsiveAdInfo,
    )

    info_type = VideoResponsiveAdInfo if type_name == "VIDEO_RESPONSIVE_AD" else ResponsiveDisplayAdInfo
    fields = info_type.pb().DESCRIPTOR.fields_by_name
    if not isinstance(payload, dict) or not payload or payload.keys() - fields.keys():
        raise WriteInputError(f"Editable keys for {type_name}: {', '.join(fields)}")
    converted = {}
    for key, value in payload.items():
        field = fields[key]
        message = field.message_type
        if message and message.name in {"AdTextAsset", "AdImageAsset", "AdVideoAsset"}:
            if field.is_repeated and not isinstance(value, list):
                raise WriteInputError(f"{key} must be an array")
            values = value if field.is_repeated else [value]
            items = []
            for item in values:
                if not isinstance(item, str) or not item.strip():
                    raise WriteInputError(f"{key} requires non-empty strings")
                if message.name == "AdTextAsset":
                    items.append({"text": item})
                else:
                    if not re.fullmatch(rf"customers/{customer_id}/assets/[0-9]+", item):
                        raise WriteInputError(f"{key} requires asset resource names matching the customer")
                    items.append({"asset": item})
            converted[key] = items if field.is_repeated else items[0]
        elif message:
            if (not isinstance(value, dict) or not value
                    or value.keys() - message.fields_by_name.keys()
                    or any(type(v) is not bool for v in value.values())):
                raise WriteInputError("control_spec accepts enable_asset_enhancements and enable_autogen_video booleans")
            converted[key] = value
        elif field.enum_type:
            if not isinstance(value, str) or value not in {"ALL_FORMATS", "NON_NATIVE", "NATIVE"}:
                raise WriteInputError("format_setting must be ALL_FORMATS, NON_NATIVE or NATIVE")
            converted[key] = value
        else:
            expected = bool if field.type == field.TYPE_BOOL else str
            if type(value) is not expected:
                raise WriteInputError(f"{key} must be {expected.__name__}")
            converted[key] = value
    return converted


def edit_ad(customer_id: str, ad_id: str, payload: dict, validate_only: bool) -> dict:
    import gads_client

    customer_id = numeric_id(gads_utils.normalize_customer_id(customer_id), "Customer ID")
    numeric_id(ad_id, "Ad ID")
    # Type-specific eligibility needs a read; reject malformed shapes without credentials.
    candidates = {}
    for type_name in ("VIDEO_RESPONSIVE_AD", "RESPONSIVE_DISPLAY_AD"):
        try:
            candidates[type_name] = _ad_input(customer_id, payload, type_name)
        except ValueError:
            pass
    if not candidates:
        raise WriteInputError("Invalid ad input: use documented editable keys, inline text and same-customer asset resources")
    if "VIDEO_RESPONSIVE_AD" in candidates and "RESPONSIVE_DISPLAY_AD" not in candidates:
        _require_video_fields(payload)
    client = gads_client.build_client()
    query = f"""SELECT ad_group_ad.ad.resource_name, ad_group_ad.ad.type,
                      ad_group_ad.ad_group, ad_group_ad.status, ad_group.status,
                      campaign.advertising_channel_type, campaign.status
               FROM ad_group_ad WHERE ad_group_ad.ad.id = {ad_id}"""
    rows = list(client.get_service("GoogleAdsService").search(customer_id=customer_id, query=query))
    if not rows:
        raise NotFound(f"Ad {ad_id} not_found")
    for row in rows:
        type_name = row.ad_group_ad.ad.type_.name
        channel = row.campaign.advertising_channel_type.name
        if (type_name, channel) not in {("VIDEO_RESPONSIVE_AD", "VIDEO"),
                                        ("RESPONSIVE_DISPLAY_AD", "DISPLAY")}:
            raise WriteInputError(f"Unsupported ad type {type_name} in channel {channel}")
    row = rows[0]
    type_name = row.ad_group_ad.ad.type_.name
    converted = _ad_input(customer_id, payload, type_name)
    if type_name == "VIDEO_RESPONSIVE_AD":
        _require_video_fields(payload)
    prefix = "video_responsive_ad" if type_name == "VIDEO_RESPONSIVE_AD" else "responsive_display_ad"
    op = client.get_type("AdOperation")
    op.update.resource_name = row.ad_group_ad.ad.resource_name
    setattr(op.update, prefix, converted)
    # Singular message fields (one AdTextAsset, control_spec) reject a mask on the
    # message itself (FIELD_HAS_SUBFIELDS); repeated fields are replaced whole.
    masks = []
    for key, value in converted.items():
        if isinstance(value, dict):
            masks.extend(f"{prefix}.{key}.{leaf}" for leaf in value)
        else:
            masks.append(f"{prefix}.{key}")
    op.update_mask.paths.extend(masks)
    response = reviewed_mutate(client.get_service("AdService").mutate_ads,
                               customer_id=customer_id, operations=[op], validate_only=validate_only)
    return {"status": "validated" if validate_only else "applied", "ad_id": ad_id,
            "field_mask": masks, "updated": len(response.results)}


def _require_video_fields(payload: dict) -> None:
    if any(not payload.get(key) for key in ("videos", "business_name", "logo_images")):
        raise WriteInputError("Video responsive edits require videos, business_name and logo_images")


# ---------- brief ----------

def _fetch_site(url: str) -> tuple[bool, str, str]:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=SITE_FETCH_TIMEOUT) as r:
            body = r.read(SITE_FETCH_LIMIT_BYTES).decode("utf-8", errors="ignore")
            return True, body, ""
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return False, "", gads_errors.describe(e)["error"]


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s)


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _first(pattern: str, html_text: str, group: int = 1) -> str | None:
    m = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
    return _collapse(html.unescape(m.group(group))) if m else None


def _all(pattern: str, html_text: str, group: int = 1, limit: int = 6) -> list[str]:
    out: list[str] = []
    for m in re.finditer(pattern, html_text, re.IGNORECASE | re.DOTALL):
        out.append(_collapse(html.unescape(m.group(group))))
        if len(out) >= limit:
            break
    return out


def _extract_hex_colors(html_text: str, limit: int = 8) -> list[str]:
    raw = re.findall(r"#([0-9a-fA-F]{6})\b", html_text)
    seen: list[str] = []
    for c in raw:
        c_lower = c.lower()
        # Filter near-white and near-black noise
        r, g, b = int(c_lower[0:2], 16), int(c_lower[2:4], 16), int(c_lower[4:6], 16)
        if r > 240 and g > 240 and b > 240:
            continue
        if r < 30 and g < 30 and b < 30:
            continue
        key = f"#{c_lower}"
        if key not in seen:
            seen.append(key)
        if len(seen) >= limit:
            break
    return seen


def build_brief(url: str) -> dict:
    ok, body, err = _fetch_site(url)
    if not ok:
        return {"url": url, "reachable": False, "error": err}

    title = _first(r"<title[^>]*>(.*?)</title>", body)
    meta_desc = _first(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', body)
    og_title = _first(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', body)
    og_desc = _first(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', body)
    og_image = _first(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', body)

    h1 = _all(r"<h1[^>]*>(.*?)</h1>", body, limit=3)
    h2 = _all(r"<h2[^>]*>(.*?)</h2>", body, limit=8)
    h1 = [_collapse(_strip_tags(x)) for x in h1 if _collapse(_strip_tags(x))]
    h2 = [_collapse(_strip_tags(x)) for x in h2 if _collapse(_strip_tags(x))]

    body_text = _collapse(_strip_tags(body))[:2000]

    colors = _extract_hex_colors(body)

    return {
        "url": url,
        "reachable": True,
        "title": title,
        "meta_description": meta_desc,
        "og": {"title": og_title, "description": og_desc, "image": og_image},
        "h1": h1,
        "h2": h2,
        "body_sample": body_text,
        "hex_colors": colors,
    }


# ---------- prompts ----------
#
# We don't try to write prompt copy here — that's the agent's job, given
# the brief. We just hand back the format scaffolds the agent should
# fill in. Sizes match Google Ads asset specs.

PROMPT_FORMATS = [
    {
        "field_type": "MARKETING_IMAGE",
        "ratio": "1.91:1",
        "size_px": "1200x628",
        "intent": "Hero / landscape lifestyle. Show the offer in context.",
    },
    {
        "field_type": "SQUARE_MARKETING_IMAGE",
        "ratio": "1:1",
        "size_px": "1200x1200",
        "intent": "Square product or brand-led shot. Strong centered subject.",
    },
    {
        "field_type": "PORTRAIT_MARKETING_IMAGE",
        "ratio": "4:5",
        "size_px": "960x1200",
        "intent": "Mobile / portrait. Lifestyle close-up with breathing room top and bottom.",
    },
    {
        "field_type": "LOGO",
        "ratio": "1:1",
        "size_px": "1200x1200",
        "intent": "Square brand mark on a clean background.",
    },
    {
        "field_type": "LANDSCAPE_LOGO",
        "ratio": "4:1",
        "size_px": "1200x300",
        "intent": "Wordmark or horizontal lockup, clean background.",
    },
]


def prompt_scaffold(brief: dict) -> dict:
    """A blank scaffold with brief snippets pre-filled.

    The agent fills in the actual prompt strings before handing them to
    whatever image generator the user picked (Google Ads' built-in PMax
    generator in the UI, Midjourney, Imagen on Vertex, a stock library,
    a designer).
    """
    hints = {
        "brand": brief.get("title") or "",
        "tagline": brief.get("meta_description") or brief.get("og", {}).get("description") or "",
        "themes_h1": brief.get("h1", []),
        "themes_h2": brief.get("h2", []),
        "palette": brief.get("hex_colors", [])[:5],
    }
    formats = []
    for f in PROMPT_FORMATS:
        formats.append({
            **f,
            "prompt": "",
            "negative_prompt": "no text in image, no watermark, no logos other than brand, no human faces in close-up unless a person is the subject",
        })
    return {"hints": hints, "formats": formats}


# ---------- upload ----------

def upload_image_asset(customer_id: str, image_path: Path, name: str | None,
                       validate_only: bool) -> dict:
    import gads_client

    customer_id = gads_utils.normalize_customer_id(customer_id)
    client = gads_client.build_client()
    svc = client.get_service("AssetService")

    image_bytes = Path(image_path).read_bytes()

    op = client.get_type("AssetOperation")
    asset = op.create
    asset.type_ = client.enums.AssetTypeEnum.IMAGE
    asset.name = name or Path(image_path).stem
    asset.image_asset.data = image_bytes

    resp = reviewed_mutate(
        svc.mutate_assets,
        customer_id=customer_id,
        operations=[op],
        validate_only=validate_only,
    )
    return {
        "customer_id": customer_id,
        "validate_only": validate_only,
        "asset_resource": resp.results[0].resource_name if resp.results else None,
    }


# ---------- attach ----------

PMAX_FIELD_TYPES = {
    "MARKETING_IMAGE", "SQUARE_MARKETING_IMAGE", "PORTRAIT_MARKETING_IMAGE",
    "LOGO", "LANDSCAPE_LOGO",
}

# Search campaign image-extension field type. We name only what we actually
# support attaching here.
SEARCH_FIELD_TYPES = {"AD_IMAGE"}


def attach_to_asset_group(customer_id: str, asset_group_id: str, asset_resource: str,
                          field_type: str, validate_only: bool) -> dict:
    import gads_client

    if field_type not in PMAX_FIELD_TYPES:
        raise WriteInputError(f"PMax field_type must be one of {sorted(PMAX_FIELD_TYPES)}")

    customer_id = gads_utils.normalize_customer_id(customer_id)
    client = gads_client.build_client()
    svc = client.get_service("AssetGroupAssetService")
    ag_svc = client.get_service("AssetGroupService")

    op = client.get_type("AssetGroupAssetOperation")
    aga = op.create
    aga.asset_group = ag_svc.asset_group_path(customer_id, asset_group_id)
    aga.asset = asset_resource
    aga.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type)

    resp = reviewed_mutate(
        svc.mutate_asset_group_assets,
        customer_id=customer_id,
        operations=[op],
        validate_only=validate_only,
    )
    return {
        "scope": "pmax_asset_group",
        "asset_group_id": asset_group_id,
        "field_type": field_type,
        "validate_only": validate_only,
        "attached": len(resp.results),
    }


def attach_to_search_campaign(customer_id: str, campaign_id: str, asset_resource: str,
                              field_type: str, validate_only: bool) -> dict:
    """Image-extension style attachment on a Search campaign."""
    import gads_client

    if field_type not in SEARCH_FIELD_TYPES:
        raise WriteInputError(
            f"Search campaign field_type must be one of {sorted(SEARCH_FIELD_TYPES)}"
        )

    customer_id = numeric_id(gads_utils.normalize_customer_id(customer_id), "Customer ID")
    numeric_id(campaign_id, "Campaign ID")
    if not re.fullmatch(rf"customers/{customer_id}/assets/[0-9]+", asset_resource):
        raise WriteInputError("Asset resource must match the customer")
    client = gads_client.build_client()
    campaign = read_campaign(client, customer_id, campaign_id)
    if campaign.advertising_channel_type.name != "SEARCH":
        raise WriteInputError("Search image attachment requires SEARCH; got "
                         + campaign.advertising_channel_type.name)
    svc = client.get_service("CampaignAssetService")
    campaign_svc = client.get_service("CampaignService")

    op = client.get_type("CampaignAssetOperation")
    ca = op.create
    ca.campaign = campaign_svc.campaign_path(customer_id, campaign_id)
    ca.asset = asset_resource
    ca.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type)

    resp = reviewed_mutate(
        svc.mutate_campaign_assets,
        customer_id=customer_id,
        operations=[op],
        validate_only=validate_only,
    )
    return {
        "scope": "search_campaign",
        "campaign_id": campaign_id,
        "field_type": field_type,
        "validate_only": validate_only,
        "attached": len(resp.results),
    }


# ---------- CLI ----------

def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)

    b = sub.add_parser("brief", help="Scrape a site and produce a creative brief")
    b.add_argument("--site", required=True)
    b.add_argument("--output", help="Write brief JSON to this path")

    pr = sub.add_parser("prompts", help="Emit prompt-template scaffolding from a brief")
    pr.add_argument("--brief", required=True, help="Path to brief.json")
    pr.add_argument("--output", help="Write scaffold JSON to this path")

    u = sub.add_parser("upload", help="Upload an image to Google Ads as an ImageAsset")
    u.add_argument("--customer", required=True)
    u.add_argument("--image", required=True)
    u.add_argument("--name", help="Asset display name (default: filename stem)")
    mode = u.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--apply", action="store_true")

    a = sub.add_parser("attach", help="Link an uploaded asset to a campaign or asset group")
    a.add_argument("--customer", required=True)
    a.add_argument("--asset-resource", required=True,
                   help="Resource name returned by `upload`")
    a.add_argument("--field-type", required=True,
                   help=f"PMax: one of {sorted(PMAX_FIELD_TYPES)}. Search: one of {sorted(SEARCH_FIELD_TYPES)}")
    grp = a.add_mutually_exclusive_group(required=True)
    grp.add_argument("--asset-group-id", help="PMax asset group ID")
    grp.add_argument("--campaign-id", help="Search campaign ID")
    mode = a.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--apply", action="store_true")

    uv = sub.add_parser("upload-video", help="Upload a YouTube video, then create an asset")
    uv.add_argument("--customer", required=True)
    uv.add_argument("--file", required=True)
    uv.add_argument("--title", required=True)
    uv.add_argument("--description", default="")
    uv.add_argument("--channel-id")
    uv.add_argument("--privacy", choices=("UNLISTED", "PUBLIC"), default="UNLISTED")
    uv.add_argument("--asset-name")
    uv.add_argument("--apply", action="store_true")

    va = sub.add_parser("create-video-asset", help="Create an asset for an existing YouTube video")
    va.add_argument("--customer", required=True)
    va.add_argument("--video-id", required=True)
    va.add_argument("--name", required=True)
    ea = sub.add_parser("edit-ad", help="Edit a Video responsive or responsive Display ad")
    ea.add_argument("--customer", required=True)
    ea.add_argument("--ad-id", required=True)
    ea.add_argument("--input", required=True)
    for s in (va, ea):
        mode = s.add_mutually_exclusive_group()
        mode.add_argument("--validate-only", action="store_true")
        mode.add_argument("--apply", action="store_true")

    for s in (b, pr, u, a, uv, va, ea):
        s.add_argument("--json", action="store_true")

    args = p.parse_args()
    json_mode = getattr(args, "json", False)

    if args.action in {"upload-video", "create-video-asset", "edit-ad"}:
        try:
            if args.action == "upload-video":
                result = upload_video(args.customer, Path(args.file), args.title, args.description,
                                      args.channel_id, args.privacy, args.asset_name, args.apply)
            elif not (args.validate_only or args.apply):
                result = {"status": "no_op", "hint": "Pass --validate-only or --apply"}
            elif args.action == "create-video-asset":
                result = create_video_asset(args.customer, args.video_id, args.name, not args.apply)
            else:
                payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
                result = edit_ad(args.customer, args.ad_id, payload, not args.apply)
        except Exception as exc:
            result = gads_errors.describe(exc)
            if isinstance(exc, WriteInputError):
                result["error"] = str(exc)
            result["summary"] = f"{result['error_code']}: {result['error']}"
            gads_utils.emit(result, json_mode)
            return 3
        gads_utils.emit(result, json_mode)
        return 0 if result["status"] in {"no_op", "validated", "applied"} else 3

    if args.action == "brief":
        brief = build_brief(args.site)
        _write_or_emit(brief, args.output, json_mode)
        return 0

    if args.action == "prompts":
        brief = json.loads(Path(args.brief).read_text())
        scaffold = prompt_scaffold(brief)
        _write_or_emit(scaffold, args.output, json_mode)
        return 0

    if args.action == "upload":
        if not (args.validate_only or args.apply):
            gads_utils.emit({"status": "no_op",
                             "hint": "Pass --validate-only or --apply"}, json_mode)
            return 0
        try:
            result = upload_image_asset(args.customer, Path(args.image), args.name,
                                        validate_only=not args.apply)
        except Exception as e:
            gads_utils.emit({**gads_errors.describe(e), "status": "api_error"}, json_mode)
            return 3
        gads_utils.emit({"status": "validated" if not args.apply else "applied",
                         **result}, json_mode)
        return 0

    if args.action == "attach":
        if not (args.validate_only or args.apply):
            gads_utils.emit({"status": "no_op",
                             "hint": "Pass --validate-only or --apply"}, json_mode)
            return 0
        try:
            if args.asset_group_id:
                result = attach_to_asset_group(
                    args.customer, args.asset_group_id, args.asset_resource,
                    args.field_type, validate_only=not args.apply,
                )
            else:
                result = attach_to_search_campaign(
                    args.customer, args.campaign_id, args.asset_resource,
                    args.field_type, validate_only=not args.apply,
                )
        except (ValueError, Exception) as e:
            failure = {**gads_errors.describe(e), "status": "api_error"}
            if isinstance(e, WriteInputError):
                failure["error"] = str(e)
            failure["summary"] = f"{failure['error_code']}: {failure['error']}"
            gads_utils.emit(failure, json_mode)
            return 3
        gads_utils.emit({"status": "validated" if not args.apply else "applied",
                         **result}, json_mode)
        return 0

    p.print_help()
    return 0


def _write_or_emit(data: dict, output: str | None, json_mode: bool) -> None:
    blob = json.dumps(data, indent=2, default=str)
    if output:
        Path(output).write_text(blob)
        return
    gads_utils.emit(data, json_mode)


if __name__ == "__main__":
    sys.exit(main())
