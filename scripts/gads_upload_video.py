"""Upload a local video after terminal review; the upload session is opened once."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import sys
from pathlib import Path

import gads_client
import gads_errors
import gads_utils
from gads_creation import _customer_id
from gads_mutate import MutationOutcomeUnknown, review_request

VIDEO_EXTENSIONS = {".3gp", ".avi", ".flv", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ogg", ".webm", ".wmv"}
UPLOAD_TIMEOUT_SECONDS = 1800
_TRANSPORT = ("google.ads.googleads.{}.services.services.you_tube_video_upload_service."
              "transports.resumable_upload")


@contextlib.contextmanager
def _status_check_with_version():
    # google-ads 33.0.0 calls raise_formatted_for_status(response) without its required
    # version argument, so every upload response raises TypeError without this binding.
    module = importlib.import_module(_TRANSPORT.format(gads_client.API_VERSION))
    original = module.raise_formatted_for_status

    def check(response, *args, **kwargs):
        if not args and "version" not in kwargs:
            kwargs["version"] = gads_client.API_VERSION
        return original(response, *args, **kwargs)

    module.raise_formatted_for_status = check
    try:
        yield
    finally:
        module.raise_formatted_for_status = original


def upload_video(customer_id: str, file: str, title: str, description: str,
                 privacy: str = "UNLISTED", channel_id: str | None = None) -> dict:
    cid = _customer_id(customer_id)
    path = Path(file).resolve()
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Unsupported video extension")
    if not path.is_file():
        raise ValueError("Video file must exist and be a regular file")
    if not path.stat().st_size:
        raise ValueError("Video file must be non-empty")
    if privacy not in ("UNLISTED", "PUBLIC"):
        raise ValueError("privacy must be UNLISTED or PUBLIC")
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError("title must contain 1-100 characters")
    if not isinstance(description, str) or len(description) > 5000:
        raise ValueError("description must contain at most 5000 characters")
    if channel_id is not None and (not isinstance(channel_id, str) or not channel_id.strip()):
        raise ValueError("channel_id must be non-empty when supplied")
    client = gads_client.build_client()
    req = client.get_type("CreateYouTubeVideoUploadRequest")
    req.customer_id = cid
    req.you_tube_video_upload.video_title = title
    req.you_tube_video_upload.video_description = description
    req.you_tube_video_upload.video_privacy = getattr(client.enums.YouTubeVideoPrivacyEnum, privacy)
    if channel_id is not None:
        req.you_tube_video_upload.channel_id = channel_id
    service = client.get_service("YouTubeVideoUploadService")
    preview = {"customer_id": cid, "title": title, "description": description,
               "privacy": privacy, "channel": channel_id or "Google-managed",
               "file": str(path), "size_bytes": path.stat().st_size}
    review_request(preview, "Upload")
    with path.open("rb") as stream, _status_check_with_version():
        try:
            response = service.create_you_tube_video_upload(
                request=req, stream=stream, retry=None, timeout=UPLOAD_TIMEOUT_SECONDS)
        except Exception as exc:
            # A failed chunk or finalize, or the SDK deadline raising RuntimeError mid-session,
            # can follow bytes the server already accepted, so no failure is safely definite.
            raise MutationOutcomeUnknown("Upload was sent; no confirmed result") from exc
    resource = response.resource_name
    upload_id = resource.rsplit("/", 1)[-1]
    hint = "Query you_tube_video_upload with MCP run_gaql for processing state and YouTube video ID."
    query = ("SELECT you_tube_video_upload.resource_name, you_tube_video_upload.state, "
             "you_tube_video_upload.video_id FROM you_tube_video_upload "
             f"WHERE you_tube_video_upload.resource_name = '{resource}'")
    return {"status": "uploaded", "customer_id": cid, "resource_name": resource,
            "upload_id": upload_id, "hint": hint, "query": query,
            "summary": f"Upload {upload_id}: {resource}\n{hint}\n{query}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--privacy", choices=("UNLISTED", "PUBLIC"), default="UNLISTED")
    parser.add_argument("--channel-id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = upload_video(args.customer, args.file, args.title, args.description,
                              args.privacy, args.channel_id)
    except Exception as exc:
        failure = gads_errors.describe(exc)
        if type(exc) is ValueError:
            failure["error"] = str(exc)
        if not args.json:
            failure["summary"] = failure["error"]
        gads_utils.emit(failure, args.json)
        return 3
    gads_utils.emit(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
