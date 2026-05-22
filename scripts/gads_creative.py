"""Creative wizard: site brief -> prompt scaffolding -> image generation
-> upload to Google Ads -> attach to PMax asset groups or Search campaigns.

Five subcommands, each callable on its own. The `gads-creative` agent
chains them with confirmation between every step:

  brief     scrape a URL and produce a structured creative brief
  prompts   emit prompt templates per ad-format size (the agent fills
            in copy specifics from the brief)
  generate  call an image-gen provider, save PNG locally
  upload    upload a local PNG to Google Ads as an ImageAsset
  attach    link an uploaded asset to a PMax asset group or a Search
            campaign (image asset extension)

Providers for `generate`:
  - vertex  (default) Google Imagen via Vertex AI. Uses gcloud ADC,
            no extra credentials. Needs a Cloud project with the
            Vertex AI API enabled and billing on.
  - openai  OpenAI DALL-E. Reads OPENAI_API_KEY from env.

All write paths use --validate-only / --apply.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import gads_utils

USER_AGENT = "gads-agents/0.4"
SITE_FETCH_TIMEOUT = 10
SITE_FETCH_LIMIT_BYTES = 750_000


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
        return False, "", str(e)


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

    The agent fills in the actual prompt strings before generation.
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


# ---------- image generation ----------

class GenerationError(RuntimeError):
    pass


def generate_image(prompt: str, size_px: str, provider: str,
                   output_path: Path, project_id: str | None = None,
                   negative_prompt: str | None = None) -> dict:
    if provider == "vertex":
        return _generate_vertex_imagen(prompt, size_px, output_path, project_id, negative_prompt)
    if provider == "openai":
        return _generate_openai(prompt, size_px, output_path)
    raise GenerationError(f"unknown provider: {provider}")


def _ratio_for_imagen(size_px: str) -> str:
    """Imagen takes aspect_ratio strings, not pixel dimensions."""
    w, h = size_px.lower().split("x")
    w, h = int(w), int(h)
    if w == h:
        return "1:1"
    if abs(w / h - 16 / 9) < 0.05:
        return "16:9"
    if abs(w / h - 9 / 16) < 0.05:
        return "9:16"
    if abs(w / h - 4 / 3) < 0.05:
        return "4:3"
    if abs(w / h - 3 / 4) < 0.05:
        return "3:4"
    return "1:1"


def _vertex_project() -> str:
    """Best-effort project: VERTEX_PROJECT env, then ADC quota project."""
    if os.environ.get("VERTEX_PROJECT"):
        return os.environ["VERTEX_PROJECT"]
    try:
        import google.auth
        _creds, project = google.auth.default()
        if project:
            return project
    except Exception:
        pass
    raise GenerationError(
        "No Vertex project. Set VERTEX_PROJECT env var or run "
        "`gcloud auth application-default set-quota-project <PROJECT>`."
    )


def _vertex_access_token() -> str:
    import google.auth
    import google.auth.transport.requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _generate_vertex_imagen(prompt: str, size_px: str, output_path: Path,
                            project_id: str | None, negative_prompt: str | None) -> dict:
    project = project_id or _vertex_project()
    token = _vertex_access_token()

    endpoint = (
        f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/"
        f"locations/us-central1/publishers/google/models/imagen-3.0-generate-002:predict"
    )
    aspect = _ratio_for_imagen(size_px)
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect,
            "personGeneration": "allow_adult",
            "safetySetting": "block_only_high",
        },
    }
    if negative_prompt:
        payload["parameters"]["negativePrompt"] = negative_prompt

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise GenerationError(f"Vertex Imagen HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}") from e
    except urllib.error.URLError as e:
        raise GenerationError(f"Vertex Imagen: {e}") from e

    predictions = data.get("predictions") or []
    if not predictions:
        raise GenerationError(f"Vertex Imagen returned no predictions: {data}")
    b64 = predictions[0].get("bytesBase64Encoded")
    if not b64:
        raise GenerationError(f"Vertex Imagen prediction missing bytesBase64Encoded: {predictions[0]}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(b64))
    return {"provider": "vertex", "aspect_ratio": aspect, "path": str(output_path)}


def _generate_openai(prompt: str, size_px: str, output_path: Path) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise GenerationError("OPENAI_API_KEY not set")

    # DALL-E 3 sizes
    size = {
        "1200x628": "1792x1024",
        "1200x1200": "1024x1024",
        "960x1200": "1024x1792",
        "1200x300": "1792x1024",
    }.get(size_px, "1024x1024")

    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "response_format": "b64_json",
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise GenerationError(f"OpenAI HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}") from e

    b64 = data["data"][0]["b64_json"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(b64))
    return {"provider": "openai", "size": size, "path": str(output_path)}


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

    resp = svc.mutate_assets(
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
SEARCH_FIELD_TYPES = {"IMAGE"}


def attach_to_asset_group(customer_id: str, asset_group_id: str, asset_resource: str,
                          field_type: str, validate_only: bool) -> dict:
    import gads_client

    if field_type not in PMAX_FIELD_TYPES:
        raise ValueError(f"PMax field_type must be one of {sorted(PMAX_FIELD_TYPES)}")

    customer_id = gads_utils.normalize_customer_id(customer_id)
    client = gads_client.build_client()
    svc = client.get_service("AssetGroupAssetService")
    ag_svc = client.get_service("AssetGroupService")

    op = client.get_type("AssetGroupAssetOperation")
    aga = op.create
    aga.asset_group = ag_svc.asset_group_path(customer_id, asset_group_id)
    aga.asset = asset_resource
    aga.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type)

    resp = svc.mutate_asset_group_assets(
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
        raise ValueError(
            f"Search campaign field_type must be one of {sorted(SEARCH_FIELD_TYPES)}"
        )

    customer_id = gads_utils.normalize_customer_id(customer_id)
    client = gads_client.build_client()
    svc = client.get_service("CampaignAssetService")
    campaign_svc = client.get_service("CampaignService")

    op = client.get_type("CampaignAssetOperation")
    ca = op.create
    ca.campaign = campaign_svc.campaign_path(customer_id, campaign_id)
    ca.asset = asset_resource
    ca.field_type = getattr(client.enums.AssetFieldTypeEnum, field_type)

    resp = svc.mutate_campaign_assets(
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

    g = sub.add_parser("generate", help="Run an image-gen provider")
    g.add_argument("--prompt", required=True)
    g.add_argument("--size", default="1200x1200", help="Pixel dims (provider may snap to nearest)")
    g.add_argument("--provider", choices=("vertex", "openai"), default="vertex")
    g.add_argument("--project", help="Override Vertex project (default: ADC quota project)")
    g.add_argument("--negative-prompt")
    g.add_argument("--output", required=True, help="Output PNG path")

    u = sub.add_parser("upload", help="Upload a PNG to Google Ads as an ImageAsset")
    u.add_argument("--customer", required=True)
    u.add_argument("--image", required=True)
    u.add_argument("--name", help="Asset display name (default: filename stem)")
    u.add_argument("--validate-only", action="store_true")
    u.add_argument("--apply", action="store_true")

    a = sub.add_parser("attach", help="Link an uploaded asset to a campaign or asset group")
    a.add_argument("--customer", required=True)
    a.add_argument("--asset-resource", required=True,
                   help="Resource name returned by `upload`")
    a.add_argument("--field-type", required=True,
                   help=f"PMax: one of {sorted(PMAX_FIELD_TYPES)}. Search: one of {sorted(SEARCH_FIELD_TYPES)}")
    grp = a.add_mutually_exclusive_group(required=True)
    grp.add_argument("--asset-group-id", help="PMax asset group ID")
    grp.add_argument("--campaign-id", help="Search campaign ID")
    a.add_argument("--validate-only", action="store_true")
    a.add_argument("--apply", action="store_true")

    for s in (b, pr, g, u, a):
        s.add_argument("--json", action="store_true")

    args = p.parse_args()
    json_mode = getattr(args, "json", False)

    if args.action == "brief":
        brief = build_brief(args.site)
        _write_or_emit(brief, args.output, json_mode)
        return 0

    if args.action == "prompts":
        brief = json.loads(Path(args.brief).read_text())
        scaffold = prompt_scaffold(brief)
        _write_or_emit(scaffold, args.output, json_mode)
        return 0

    if args.action == "generate":
        try:
            result = generate_image(
                args.prompt, args.size, args.provider,
                Path(args.output), args.project, args.negative_prompt,
            )
        except GenerationError as e:
            gads_utils.emit({"status": "error", "error": str(e)}, json_mode)
            return 3
        gads_utils.emit({"status": "generated", **result}, json_mode)
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
            gads_utils.emit({"status": "api_error", "error": str(e)}, json_mode)
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
            gads_utils.emit({"status": "api_error", "error": str(e)}, json_mode)
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
