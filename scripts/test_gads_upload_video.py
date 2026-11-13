import importlib
import io
import json
import sys
from unittest.mock import Mock

import gads_client
import gads_upload_video
import pytest
import requests
from gads_mutate import MutationCancelled, MutationOutcomeUnknown
from google.ads.googleads.errors import GoogleAdsException, raise_formatted_for_status
from google.api_core import exceptions as api_errors
from test_gads_mcp import CUSTOMER, TYPES


@pytest.fixture
def upload(monkeypatch, tmp_path):
    service = Mock()
    response = TYPES.get_type("CreateYouTubeVideoUploadResponse")
    response.resource_name = f"customers/{CUSTOMER}/youTubeVideoUploads/42"
    service.create_you_tube_video_upload.return_value = response
    client = Mock(get_type=TYPES.get_type, enums=TYPES.enums)
    client.get_service.return_value = service
    monkeypatch.setattr(gads_client, "build_client", Mock(return_value=client))
    path = tmp_path / "video.mp4"
    path.write_bytes(b"offline-video")
    monkeypatch.setattr("builtins.input", lambda: "y")
    return service.create_you_tube_video_upload, path


def run(path, **kwargs):
    return gads_upload_video.upload_video(CUSTOMER, str(path), "Title", "Description", **kwargs)


@pytest.mark.parametrize("privacy,channel", [("UNLISTED", None), ("PUBLIC", "UCexample")])
def test_request_preview_and_single_send(upload, monkeypatch, capsys, privacy, channel):
    send, path = upload

    def approve():
        send.assert_not_called()
        preview, prompt = capsys.readouterr().err.rsplit("\n", 2)[:2]
        data = json.loads(preview)
        assert data == {"customer_id": CUSTOMER, "file": str(path.resolve()), "size_bytes": 13,
                        "title": "Title", "description": "Description", "privacy": privacy,
                        "channel": channel or "Google-managed"}
        assert prompt == "Upload these operations? y/N"
        return "y"

    def respond(**kwargs):
        assert kwargs["stream"].read() == b"offline-video"
        assert transport_module().raise_formatted_for_status is not raise_formatted_for_status
        return send.return_value

    monkeypatch.setattr("builtins.input", approve)
    send.side_effect = respond
    result = run(path, privacy=privacy, channel_id=channel)
    send.assert_called_once()
    kwargs = send.call_args.kwargs
    assert kwargs["retry"] is None and kwargs["timeout"] == 1800
    assert kwargs["stream"].closed
    request = kwargs["request"]
    assert request.customer_id == CUSTOMER
    video = request.you_tube_video_upload
    assert video.video_title == "Title" and video.video_description == "Description"
    assert video.video_privacy.name == privacy and video.channel_id == (channel or "")
    assert result["upload_id"] == "42" and result["resource_name"] == send.return_value.resource_name
    assert "you_tube_video_upload.state" in result["query"] and "you_tube_video_upload.video_id" in result["query"]


@pytest.mark.parametrize("case", ["extension", "missing", "directory", "empty"])
def test_invalid_file_sends_nothing(upload, tmp_path, case):
    send, path = upload
    if case == "extension":
        path = tmp_path / "video.txt"
        path.write_bytes(b"data")
    elif case == "missing":
        path = tmp_path / "missing.mp4"
    elif case == "directory":
        path = tmp_path / "directory.mp4"
        path.mkdir()
    else:
        path.write_bytes(b"")
    with pytest.raises(ValueError):
        run(path)
    send.assert_not_called()
    gads_client.build_client.assert_not_called()


@pytest.mark.parametrize("tty,answer", [(False, "y"), (True, "n"), (True, "yes")])
def test_terminal_refusal(upload, monkeypatch, tty, answer):
    send, path = upload
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda: answer)
    with pytest.raises(MutationCancelled):
        run(path)
    send.assert_not_called()


@pytest.mark.parametrize("failure", [
    TypeError("raise_formatted_for_status() missing 1 required positional argument: 'version'"),
    RuntimeError("Upload deadline was exceeded"),
    api_errors.RetryError("private upstream response", cause=None),
])
def test_send_failure_is_unknown_without_retry(upload, failure):
    send, path = upload
    send.side_effect = failure
    with pytest.raises(MutationOutcomeUnknown, match="no confirmed result"):
        run(path)
    send.assert_called_once()
    assert send.call_args.kwargs["retry"] is None and send.call_args.kwargs["stream"].closed


@pytest.mark.parametrize("failure", [False, True])
def test_cli_json_and_exit_code(upload, monkeypatch, capsys, failure):
    send, path = upload
    if failure:
        send.side_effect = RuntimeError("secret upstream response")
    monkeypatch.setattr(sys, "argv", ["gads_upload_video.py", "--customer", CUSTOMER,
                                      "--file", str(path), "--title", "Title", "--description", "Description", "--json"])
    assert gads_upload_video.main() == (3 if failure else 0)
    out = json.loads(capsys.readouterr().out)
    if failure:
        assert out["error_code"] == "outcome_unknown" and out["retryable"] is False
        assert "secret" not in json.dumps(out)
    else:
        assert out["upload_id"] == "42"
        assert send.call_args.kwargs["request"].you_tube_video_upload.video_privacy.name == "UNLISTED"
    send.assert_called_once()


def test_private_not_offered(upload, monkeypatch):
    send, path = upload
    monkeypatch.setattr(sys, "argv", ["gads_upload_video.py", "--customer", CUSTOMER, "--file", str(path),
                                      "--title", "Title", "--description", "Description", "--privacy", "PRIVATE"])
    with pytest.raises(SystemExit) as exc:
        gads_upload_video.main()
    assert exc.value.code == 2
    send.assert_not_called()


@pytest.mark.parametrize("failure", [False, True])
def test_cli_human_output(upload, monkeypatch, capsys, failure):
    send, path = upload
    if failure:
        send.side_effect = RuntimeError("secret")
    monkeypatch.setattr(sys, "argv", ["gads_upload_video.py", "--customer", CUSTOMER,
                                      "--file", str(path), "--title", "Title", "--description", "Description"])
    assert gads_upload_video.main() == (3 if failure else 0)
    out = capsys.readouterr().out
    if failure:
        assert "may have been applied" in out and "secret" not in out
    else:
        assert "Upload 42:" in out and send.return_value.resource_name in out
        assert "run_gaql" in out and "you_tube_video_upload.state" in out


def transport_module():
    return importlib.import_module(gads_upload_video._TRANSPORT.format(gads_client.API_VERSION))


def http_response(status, headers=None, body=b"{}"):
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = body
    response.url = "https://example.test/upload"
    response.request = requests.Request("POST", response.url).prepare()
    return response


class OneResponse:
    def __init__(self, response):
        self.response = response

    def request(self, method, url, data=None, headers=None, timeout=None):
        return self.response


def test_real_transport_accepts_ok_response_and_restores_check():
    module = transport_module()
    original = module.raise_formatted_for_status
    upload = module.ResumableUpload("https://example.test/upload", io.BytesIO(b"x"), size=1)
    ok = http_response(200, {"X-Goog-Upload-URL": "https://example.test/session"})
    with gads_upload_video._status_check_with_version():
        upload.initiate(OneResponse(ok))
        module.raise_formatted_for_status(ok, gads_client.API_VERSION)
    assert upload.session_url == "https://example.test/session"
    assert module.raise_formatted_for_status is original


def test_real_transport_error_is_ads_exception_not_type_error():
    module = transport_module()
    original = module.raise_formatted_for_status
    upload = module.ResumableUpload("https://example.test/upload", io.BytesIO(b"x"), size=1)
    refused = http_response(400, {"Content-Type": "application/json"},
                            json.dumps({"error": {"code": 400, "message": "bad"}}).encode())
    with pytest.raises(GoogleAdsException), gads_upload_video._status_check_with_version():
        upload.initiate(OneResponse(refused))
    assert module.raise_formatted_for_status is original
