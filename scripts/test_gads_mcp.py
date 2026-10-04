"""MCP tool-set contract: offline, fake transport, real Google Ads response types."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import gads_audit
import gads_auth
import gads_history
import gads_mcp
import gads_provider
import gads_utils
import grpc
import pytest
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.ads.googleads.v25.errors.types.errors import GoogleAdsFailure
from google.api_core import exceptions as api_errors
from google.auth.credentials import AnonymousCredentials
from google.auth.exceptions import DefaultCredentialsError, RefreshError
from mcp.server.fastmcp import FastMCP

SCRIPTS = Path(__file__).resolve().parent
TYPES = GoogleAdsClient(credentials=AnonymousCredentials(), version="v25", use_proto_plus=True)
FIELD = type(TYPES.get_type("GoogleAdsField"))

NAMES = {"list_accounts", "run_gaql", "resource_metadata", "account_audit",
         "anomalies_and_pacing", "change_history"}
ALLOWED = {
    ("GoogleAdsService", "search_stream"),
    ("GoogleAdsService", "search"),
    ("CustomerService", "list_accessible_customers"),
    ("GoogleAdsFieldService", "search_google_ads_fields"),
    ("GoogleAdsFieldService", "get_google_ads_field"),
}
CATEGORIES = {"auth_required", "permission_denied", "quota_exceeded", "invalid_argument",
              "not_found", "upstream_error"}
MANAGER = "9990001111"
CUSTOMER = "1234567890"
GAQL = "SELECT ad_group.id, ad_group.name FROM ad_group WHERE ad_group.status = 'ENABLED'"
SECRETS = ("ya29.SENTINEL-access-token-0001", "1//0SENTINEL-refresh-token-0002",
           "GOCSPX-SENTINEL-client-secret-0003", "SENTINELdevTOKEN0123456789")

CALLS = [
    ("list_accounts", {}),
    ("run_gaql", {"customer_id": CUSTOMER, "query": GAQL}),
    ("resource_metadata", {"name": "campaign.status", "detail": True}),
    ("account_audit", {"customer_id": CUSTOMER}),
    ("anomalies_and_pacing", {"customer_id": CUSTOMER}),
    ("change_history", {"customer_id": CUSTOMER}),
]


# ---------- fake transport ----------

class FakeCredentials:
    token, refresh_token, client_secret = SECRETS[:3]


class FakeProvider:
    def __init__(self, login: str | None = MANAGER):
        self.login = login

    def get_credentials(self):
        return FakeCredentials()

    def get_developer_token(self):
        return SECRETS[3]

    def get_login_customer_id(self):
        return self.login


class FakeService:
    def __init__(self, recorder, name):
        self._recorder, self._name = recorder, name

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self._recorder.requests.append((self._name, method, kwargs))
            return self._recorder.respond(self._name, method, kwargs)
        return call


class Recorder:
    """Stands in for GoogleAdsClient and records every service method and type requested."""

    def __init__(self, respond):
        self.respond = respond
        self.requests: list[tuple[str, str, dict]] = []
        self.types: list[str] = []
        self.clients: list[dict] = []
        recorder = self

        class FakeGoogleAdsClient:
            def __init__(self, **kwargs):
                recorder.clients.append(kwargs)

            def get_service(self, name, version=None):
                return FakeService(recorder, name)

            def get_type(self, name, version=None):
                recorder.types.append(name)
                return TYPES.get_type(name)

        self.client_class = FakeGoogleAdsClient

    def calls(self) -> set[tuple[str, str]]:
        return {(service, method) for service, method, _ in self.requests}

    def queries(self) -> list[str]:
        return [kwargs.get("query") or kwargs["request"]["query"] for _, _, kwargs in self.requests
                if "query" in kwargs or "request" in kwargs]


class FakePager:
    def __init__(self, fields):
        self.fields = fields
        self.total_results_count = len(fields)

    def __iter__(self):
        return iter(self.fields)


class FakeRpcError(grpc.RpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "fake detail"

    def trailing_metadata(self):
        return None


def stream(rows):
    batch = TYPES.get_type("SearchGoogleAdsStreamResponse")
    for fields in rows:
        row = TYPES.get_type("GoogleAdsRow")
        for key, value in fields.items():
            setattr(row, key, value)
        batch.results.append(row)
    return [batch]


ACCOUNTS = [
    {"customer_client": {"id": int(MANAGER), "descriptive_name": "Example Manager", "level": 0,
                         "manager": True, "currency_code": "USD", "time_zone": "UTC",
                         "status": "ENABLED"}},
    {"customer_client": {"id": int(CUSTOMER), "descriptive_name": "Example Client", "level": 1,
                         "manager": False, "currency_code": "USD", "time_zone": "UTC",
                         "status": "ENABLED"}},
]
CHANGES = [
    {"change_event": {"change_date_time": "2026-10-02 10:00:00", "user_email": "first@agency.example",
                      "client_type": "GOOGLE_ADS_WEB_CLIENT", "change_resource_type": "CAMPAIGN",
                      "resource_change_operation": "UPDATE", "changed_fields": {"paths": ["status"]},
                      "campaign": f"customers/{CUSTOMER}/campaigns/111"}},
    {"change_event": {"change_date_time": "2026-10-01 09:00:00", "user_email": "second@agency.example",
                      "client_type": "GOOGLE_ADS_API", "change_resource_type": "AD_GROUP",
                      "resource_change_operation": "CREATE"}},
    {"change_event": {"change_date_time": "2026-09-30 08:00:00",
                      "client_type": "GOOGLE_ADS_RECOMMENDATIONS",
                      "change_resource_type": "CAMPAIGN_BUDGET",
                      "resource_change_operation": "UPDATE"}},
]
PACING = [
    {"campaign": {"id": 111, "name": "Example Search", "status": "ENABLED"},
     "campaign_budget": {"amount_micros": 10_000_000, "period": "DAILY"},
     "metrics": {"cost_micros": 90_000_000}, "segments": {"date": "2026-10-01"}},
    {"campaign": {"id": 222, "name": "Example Display", "status": "ENABLED"},
     "campaign_budget": {"amount_micros": 10_000_000, "period": "DAILY"},
     "metrics": {"cost_micros": 1_000_000}, "segments": {"date": "2026-10-01"}},
]
AD_GROUPS = [{"ad_group": {"id": n, "name": f"Example group {n}"}} for n in range(1, 8)]


def anomaly_rows():
    start = date(2026, 9, 1)
    rows = []
    for day in range(20):
        cost = 9_000_000 if day == 19 else 1_000_000 + (day % 2) * 200_000
        rows.append({"campaign": {"id": 111, "name": "Example Search"},
                     "segments": {"date": (start + timedelta(day)).isoformat()},
                     "metrics": {"cost_micros": cost, "clicks": 10 + day % 2,
                                 "impressions": 100, "conversions": 1.0}})
    return rows


def field_pager(query):
    if "category = 'RESOURCE'" in query:
        fields = [FIELD(name="ad_group", category="RESOURCE"),
                  FIELD(name="campaign", category="RESOURCE")]
    elif "LIKE 'campaign.%'" in query:
        fields = [FIELD(name=f"campaign.{n}", category="ATTRIBUTE", data_type=t, selectable=True,
                        filterable=True, sortable=n != "status")
                  for n, t in (("id", "INT64"), ("name", "STRING"), ("status", "ENUM"))]
    elif "name = 'campaign.status'" in query:
        fields = [FIELD(name="campaign.status", category="ATTRIBUTE", data_type="ENUM",
                        selectable=True, filterable=True, sortable=True,
                        enum_values=["ENABLED", "PAUSED", "REMOVED"],
                        selectable_with=["segments.date", "segments.device", "metrics.clicks"])]
    else:
        fields = []
    return FakePager(fields)


def respond(service, method, kwargs):
    if service == "CustomerService":
        response = TYPES.get_type("ListAccessibleCustomersResponse")
        response.resource_names.extend(["customers/2222222222", "customers/1111111111",
                                        "customers/3333333333"])
        return response
    if service == "GoogleAdsFieldService":
        return field_pager(kwargs["request"]["query"])
    query = kwargs["query"]
    if "FROM customer_client" in query:
        return stream(ACCOUNTS)
    if "FROM change_event" in query:
        return stream(CHANGES)
    if "ORDER BY campaign.id, segments.date" in query:
        return stream(anomaly_rows())
    if "campaign_budget.period" in query:
        return stream(PACING)
    if query.startswith("SELECT ad_group.id, ad_group.name FROM ad_group"):
        return stream(AD_GROUPS)
    return []


def raising(exc, marker=""):
    def respond_or_raise(service, method, kwargs):
        if marker in (kwargs.get("query") or ""):
            raise exc
        return respond(service, method, kwargs)
    return respond_or_raise


def ads_error(kind, value, message="private detail"):
    failure = GoogleAdsFailure(errors=[{"error_code": {kind: value}, "message": message}])
    return GoogleAdsException(None, None, failure, "request-0001")


def install(set_attribute, responder=respond) -> Recorder:
    import google.ads.googleads.client as client_module

    recorder = Recorder(responder)
    set_attribute(client_module, "GoogleAdsClient", recorder.client_class)
    return recorder


def build(provider_factory=lambda profile: FakeProvider(), prefix=""):
    server = FastMCP("test")
    gads_mcp.register(server, prefix=prefix, provider_factory=provider_factory)
    return server


def call(server, tool, /, **arguments):
    content, structured = asyncio.run(server.call_tool(tool, arguments))
    assert json.loads(content[0].text) == structured
    return structured


def exercise_all_tools(set_attribute=setattr) -> list[dict]:
    """Every tool on its success path, on failing transports, and on the local provider."""
    outputs = []
    server = build()
    install(set_attribute)
    outputs += [call(server, name, **args) for name, args in CALLS]
    outputs += [call(server, "resource_metadata"),
                call(server, "resource_metadata", name="campaign"),
                call(server, "list_accounts", profile="other"),
                call(build(lambda profile: FakeProvider(login=None)), "list_accounts"),
                call(server, "resource_metadata", name="missing.field", detail=True),
                call(server, "run_gaql", customer_id=CUSTOMER, query="DELETE FROM campaign")]
    for exc in (api_errors.PermissionDenied("x"), ads_error("query_error", "UNRECOGNIZED_FIELD"),
                FakeRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED), ValueError("x"), RuntimeError("x")):
        install(set_attribute, raising(exc))
        outputs += [call(server, name, **args) for name, args in CALLS]
    install(set_attribute)
    local = FastMCP("local")
    gads_mcp.register(local)
    outputs += [call(local, name, **args) for name, args in CALLS]
    return outputs


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    for name in ("GOOGLE_APPLICATION_CREDENTIALS", "CLOUDSDK_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gads_utils, "CACHE_DIR", home / ".claude" / "gads-cache")
    monkeypatch.setattr(gads_history, "HISTORY_ROOT", home / ".claude" / "gads-audit-history")
    return home


@pytest.fixture
def ads(monkeypatch):
    return install(monkeypatch.setattr)


# ---------- inventory ----------

@pytest.mark.parametrize("prefix", ["", "ads_"])
def test_inventory(prefix):
    server = FastMCP("test")
    assert gads_mcp.register(server, prefix=prefix) == len(gads_mcp.TOOLS)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {prefix + name for name in NAMES}
    assert [name for name, _, _ in gads_mcp.TOOLS] == [name for name, _ in CALLS]
    assert len(tools) <= 6
    for tool in tools:
        assert tool.title and tool.description
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is True
        assert "profile" in tool.inputSchema["properties"]
        if "limit" in tool.inputSchema["properties"]:
            assert tool.inputSchema["properties"]["limit"]["default"] >= 1


def test_main_builds_its_own_server(monkeypatch):
    served = []
    monkeypatch.setattr(FastMCP, "run", lambda self, *args, **kwargs: served.append(self))
    gads_mcp.main()
    assert served[0].name == "google-ads-agents"
    assert {tool.name for tool in asyncio.run(served[0].list_tools())} == NAMES


# ---------- read-only boundary ----------

def test_every_tool_reads_only_allowed_methods(ads):
    server = build()
    outputs = [call(server, name, **args) for name, args in CALLS]
    outputs += [call(server, "resource_metadata"),
                call(build(lambda profile: FakeProvider(login=None)), "list_accounts")]
    assert all("error" not in out for out in outputs), outputs
    assert ads.calls() <= ALLOWED
    assert {"GoogleAdsService", "CustomerService", "GoogleAdsFieldService"} == {
        service for service, _ in ads.calls()}
    assert not any(method.startswith("mutate") for _, method in ads.calls())
    assert not any(name.endswith(("Operation", "Request")) for name in ads.types)
    assert all(query.lstrip().upper().startswith("SELECT") for query in ads.queries())


def test_write_modules_never_load(tmp_path):
    probe = (
        "import json, sys\n"
        "WRITES = ('gads_mutate', 'gads_apply', 'gads_creation')\n"
        "HEAVY = ('google.ads', 'google.auth', 'google.api_core', 'grpc', 'mcp')\n"
        "loaded = lambda names: sorted(n for n in names if n in sys.modules)\n"
        "import gads_mcp\n"
        "report = {'import': loaded(WRITES + HEAVY)}\n"
        "from mcp.server.fastmcp import FastMCP\n"
        "gads_mcp.register(FastMCP('probe'))\n"
        "report['register'] = loaded(WRITES)\n"
        "import test_gads_mcp\n"
        "outputs = test_gads_mcp.exercise_all_tools()\n"
        "report['tools'] = loaded(WRITES)\n"
        "report['errors'] = sorted({o['error'] for o in outputs if 'error' in o})\n"
        "print(json.dumps(report))\n"
    )
    probe_home = tmp_path / "probe"
    probe_home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_", "CLOUDSDK_"))}
    env.update(HOME=str(probe_home), USERPROFILE=str(probe_home), APPDATA=str(probe_home))
    proc = subprocess.run([sys.executable, "-c", probe], cwd=SCRIPTS, env=env,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout.splitlines()[-1])
    assert report["import"] == []
    assert report["register"] == []
    assert report["tools"] == []
    assert set(report["errors"]) == CATEGORIES
    assert list(probe_home.iterdir()) == []


def test_tools_write_nothing_locally(tmp_path, monkeypatch):
    before = snapshot(tmp_path)
    outputs = exercise_all_tools(monkeypatch.setattr)
    assert outputs
    assert snapshot(tmp_path) == before


def test_stdio_handshake(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_", "CLOUDSDK_"))}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), APPDATA=str(tmp_path))
    params = StdioServerParameters(command=sys.executable, cwd=str(SCRIPTS), env=env,
                                   args=["-c", "import gads_mcp; gads_mcp.main()"])

    async def session():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                init = await client.initialize()
                tools = await client.list_tools()
                result = await client.call_tool("run_gaql", {"customer_id": "1", "query": "x"})
                return init, tools, result

    init, tools, result = asyncio.run(asyncio.wait_for(session(), 120))
    assert init.serverInfo.name == "google-ads-agents"
    assert {tool.name for tool in tools.tools} == NAMES
    assert result.structuredContent["error"] == "invalid_argument"


# ---------- errors ----------

FAILURES = [
    (gads_auth.AuthRequiredError("Run: python scripts/gads_auth.py --check"), "auth_required"),
    (gads_auth.SessionExpiredError("Session expired (24h cap reached)."), "auth_required"),
    (RefreshError("invalid_grant"), "auth_required"),
    (DefaultCredentialsError("missing"), "auth_required"),
    (api_errors.Unauthenticated("x"), "auth_required"),
    (api_errors.ServiceUnavailable("Getting metadata from plugin failed with error: "
                                   "Reauthentication is needed."), "auth_required"),
    (ads_error("authentication_error", "OAUTH_TOKEN_EXPIRED"), "auth_required"),
    (api_errors.PermissionDenied("x"), "permission_denied"),
    (FakeRpcError(grpc.StatusCode.PERMISSION_DENIED), "permission_denied"),
    (ads_error("authorization_error", "USER_PERMISSION_DENIED"), "permission_denied"),
    (api_errors.ResourceExhausted("x"), "quota_exceeded"),
    (FakeRpcError(grpc.StatusCode.RESOURCE_EXHAUSTED), "quota_exceeded"),
    (ads_error("quota_error", "RESOURCE_EXHAUSTED"), "quota_exceeded"),
    (api_errors.InvalidArgument("x"), "invalid_argument"),
    (ads_error("query_error", "UNRECOGNIZED_FIELD"), "invalid_argument"),
    (ValueError("x"), "invalid_argument"),
    (api_errors.NotFound("x"), "not_found"),
    (ads_error("request_error", "RESOURCE_NOT_FOUND"), "not_found"),
    (RefreshError("temporary", retryable=True), "upstream_error"),
    (api_errors.ServiceUnavailable("x"), "upstream_error"),
    (FakeRpcError(grpc.StatusCode.UNAVAILABLE), "upstream_error"),
    (ads_error("internal_error", "INTERNAL_ERROR"), "upstream_error"),
    (TimeoutError("x"), "upstream_error"),
    (RuntimeError("x"), "upstream_error"),
]


@pytest.mark.parametrize("exc,category", FAILURES, ids=[f"{type(e).__name__}-{c}" for e, c in FAILURES])
def test_upstream_failures_map_to_categories(monkeypatch, exc, category):
    install(monkeypatch.setattr, raising(exc))
    out = call(build(), "change_history", customer_id=CUSTOMER)
    assert out == {"error": category, "hint": out["hint"]}
    assert out["hint"]
    assert "private detail" not in out["hint"]


def test_every_category_is_covered():
    assert {category for _, category in FAILURES} == CATEGORIES


@pytest.mark.parametrize("name,args", CALLS, ids=[name for name, _ in CALLS])
def test_no_exception_escapes_any_tool(ads, name, args):
    class Broken(FakeProvider):
        def get_credentials(self):
            raise RuntimeError("private detail")

    assert call(build(lambda profile: Broken()), name, **args)["error"] == "upstream_error"
    out = call(build(lambda profile: 1 / 0), name, **args)
    assert out["error"] == "upstream_error"
    assert ads.requests == []


@pytest.mark.parametrize("args,hint", [
    ({"customer_id": "123"}, "10-digit"),
    ({"customer_id": "abc-def-ghij"}, "10-digit"),
    ({"customer_id": CUSTOMER, "days": 31}, "days"),
    ({"customer_id": CUSTOMER, "limit": 0}, "limit"),
    ({"customer_id": CUSTOMER, "limit": 201}, "limit"),
])
def test_argument_bounds_are_invalid_argument(ads, args, hint):
    out = call(build(), "change_history", **args)
    assert out["error"] == "invalid_argument" and hint in out["hint"]
    assert ads.requests == []


def test_no_secret_reaches_output_or_logs(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    leak = " ".join(SECRETS) + " owner@private.example"
    server = build()
    install(monkeypatch.setattr)
    outputs = [call(server, name, **args) for name, args in CALLS]
    for exc in (gads_auth.AuthRequiredError(leak), gads_auth.SessionExpiredError(leak),
                RefreshError(leak), api_errors.PermissionDenied(leak), ValueError(leak),
                RuntimeError(leak), ads_error("query_error", "UNRECOGNIZED_FIELD", leak)):
        install(monkeypatch.setattr, raising(exc))
        outputs += [call(server, name, **args) for name, args in CALLS]

    class Leaky(FakeProvider):
        def get_credentials(self):
            raise gads_auth.AuthRequiredError(leak)

    outputs += [call(build(lambda profile: Leaky()), name, **args) for name, args in CALLS]
    text = json.dumps(outputs) + caplog.text
    assert "SENTINEL" not in text and "owner@private.example" not in text
    assert any(out.get("error") == "auth_required" for out in outputs)


# ---------- credentials ----------

def test_provider_factory_gets_profile_and_binding_is_scoped(ads):
    seen = []

    def factory(profile):
        seen.append(profile)
        return FakeProvider(login="1112223333" if profile == "second" else MANAGER)

    server = build(factory)
    out = call(server, "list_accounts", profile="second")
    call(server, "change_history", customer_id=CUSTOMER)
    assert seen == ["second", None]
    assert out["profile"] == "second" and out["manager"] == "1112223333"
    assert ads.clients[0]["login_customer_id"] == "1112223333"
    assert ads.requests[0][2]["customer_id"] == "1112223333"
    assert ads.clients[0]["developer_token"] == SECRETS[3]
    assert isinstance(gads_provider.get_active_provider(), gads_provider.FileCredentialProvider)


def test_provider_factory_returning_none_is_refused(ads):
    out = call(build(lambda profile: None), "list_accounts", profile="missing")
    assert out["error"] == "invalid_argument"
    assert ads.clients == []


def test_audit_workers_use_the_bound_provider(ads):
    call(build(lambda profile: FakeProvider(login="5556667777")), "account_audit",
         customer_id=CUSTOMER)
    assert len(ads.clients) > len(gads_audit.DEFAULT_AGENTS)
    assert {client["login_customer_id"] for client in ads.clients} == {"5556667777"}


def write_profiles(data):
    gads_auth.CREDENTIALS_PATH.write_text(json.dumps(data))
    return gads_auth.CREDENTIALS_PATH.read_bytes()


def test_local_provider_does_not_switch_profiles(ads):
    before = write_profiles({"active": "alpha", "profiles": {
        "alpha": {"login_customer_id": MANAGER}, "beta": {"login_customer_id": "1112223333"}}})
    server = FastMCP("local")
    gads_mcp.register(server)
    out = call(server, "list_accounts", profile="beta")
    assert out["error"] == "invalid_argument" and "--use-profile beta" in out["hint"]
    assert call(server, "list_accounts", profile="gamma")["error"] == "invalid_argument"
    assert gads_auth.CREDENTIALS_PATH.read_bytes() == before
    assert not gads_auth.SESSION_PATH.exists()
    assert ads.clients == [] and ads.requests == []


def test_local_provider_leaves_legacy_layout_unmigrated(ads):
    before = write_profiles({"developer_token": "legacy", "login_customer_id": MANAGER})
    server = FastMCP("local")
    gads_mcp.register(server)
    out = call(server, "list_accounts")
    assert out["error"] == "auth_required" and "--check" in out["hint"]
    assert gads_auth.CREDENTIALS_PATH.read_bytes() == before


def test_local_provider_without_session_asks_for_sign_in(ads):
    server = FastMCP("local")
    gads_mcp.register(server)
    out = call(server, "list_accounts")
    assert out["error"] == "auth_required"
    assert "gcloud auth application-default login" in out["hint"]
    assert not gads_auth.CREDENTIALS_PATH.exists()


def test_local_provider_serves_active_profile_without_developer_token(ads, monkeypatch, tmp_path):
    write_profiles({"active": "alpha", "profiles": {"alpha": {"login_customer_id": MANAGER}}})
    gads_auth.session_start()
    monkeypatch.setattr("google.auth.default", lambda scopes=None: (FakeCredentials(), None))
    before = snapshot(tmp_path)
    server = FastMCP("local")
    gads_mcp.register(server)
    out = call(server, "list_accounts", profile="alpha")
    assert out["manager"] == MANAGER and out["rows_returned"] == 2
    assert ads.clients[0]["developer_token"] is None
    assert ads.clients[0]["login_customer_id"] == MANAGER
    assert snapshot(tmp_path) == before


def test_credentials_present_without_any_file():
    assert gads_mcp.credentials_present() is False


def test_credentials_present_with_toolkit_file(home, monkeypatch):
    (home / ".claude").mkdir()
    (home / ".claude" / "gads-credentials.json").write_text("{}")

    def no_open(*args, **kwargs):
        raise AssertionError("credentials_present must not open files")

    monkeypatch.setattr("builtins.open", no_open)
    monkeypatch.setattr("io.open", no_open)
    assert gads_mcp.credentials_present() is True


def test_credentials_present_with_explicit_credentials(tmp_path, monkeypatch):
    path = tmp_path / "service.json"
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))
    assert gads_mcp.credentials_present() is False
    path.write_text("{}")
    assert gads_mcp.credentials_present() is True


def test_credentials_present_with_gcloud_adc(home, tmp_path, monkeypatch):
    if os.name == "nt":
        default = tmp_path / "appdata" / "gcloud"
    else:
        default = home / ".config" / "gcloud"
    default.mkdir(parents=True)
    (default / "application_default_credentials.json").write_text("{}")
    assert gads_mcp.credentials_present() is True
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path / "elsewhere"))
    assert gads_mcp.credentials_present() is False
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "application_default_credentials.json").write_text("{}")
    assert gads_mcp.credentials_present() is True


def test_credentials_present_never_raises(monkeypatch):
    def no_home(cls):
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr(Path, "home", classmethod(no_home))
    assert gads_mcp.credentials_present() is False


# ---------- tools ----------

def test_list_accounts_under_manager(ads):
    out = call(build(), "list_accounts", limit=1)
    assert ads.requests[0][2]["customer_id"] == MANAGER
    assert "LIMIT 2" in ads.requests[0][2]["query"]
    assert out["accounts"] == [{"id": MANAGER, "name": "Example Manager", "level": 0,
                                "manager": True, "currency": "USD", "time_zone": "UTC",
                                "status": "ENABLED"}]
    assert out["rows_returned"] == 1 and out["complete"] is False


def test_list_accounts_without_manager_lists_accessible_customers(ads):
    out = call(build(lambda profile: FakeProvider(login=None)), "list_accounts", limit=2)
    assert ads.calls() == {("CustomerService", "list_accessible_customers")}
    assert out["manager"] is None
    assert out["accounts"] == [{"id": "1111111111"}, {"id": "2222222222"}]
    assert out["complete"] is False


def test_run_gaql_bounds_rows(ads):
    out = call(build(), "run_gaql", customer_id="123-456-7890", query=GAQL, limit=5)
    assert ads.requests[0][2]["customer_id"] == CUSTOMER
    assert ads.requests[0][2]["query"].endswith("LIMIT 6")
    assert out["rows_returned"] == 5 and out["complete"] is False
    assert out["rows"][0]["ad_group"]["name"] == "Example group 1"
    assert call(build(), "run_gaql", customer_id=CUSTOMER, query=GAQL, limit=7)["complete"] is True


def test_run_gaql_accepts_separators_inside_string_literals(ads):
    query = "SELECT campaign.id FROM campaign WHERE campaign.name = 'a; LIMIT 5 -- b'"
    out = call(build(), "run_gaql", customer_id=CUSTOMER, query=query)
    assert "error" not in out and len(ads.requests) == 1


@pytest.mark.parametrize("query", [
    "",
    "DELETE FROM campaign",
    "UPDATE campaign SET campaign.status = 'PAUSED'",
    "SELECT * FROM campaign",
    "SELECT campaign.id FROM campaign; SELECT ad_group.id FROM ad_group",
    "SELECT campaign.id FROM campaign WHERE campaign.id = 1 SELECT ad_group.id FROM ad_group",
    "SELECT campaign.id FROM campaign -- comment",
    "SELECT campaign.id FROM campaign /* comment */",
    "SELECT campaign.id FROM campaign LIMIT 5",
    "SELECT campaign.id FROM campaign PARAMETERS include_drafts=true",
    "SELECT campaign.id FROM campaign WHERE campaign.name = 'unterminated",
    "SELECT campaign.id FROM campaign WHERE campaign.id = 1 {",
    "  mutate campaign",
])
def test_run_gaql_rejects_anything_but_one_select(ads, query):
    out = call(build(), "run_gaql", customer_id=CUSTOMER, query=query)
    assert out["error"] == "invalid_argument" and "SELECT" in out["hint"]
    assert ads.requests == []


def test_resource_metadata_lists_resources_and_fields(ads):
    resources = call(build(), "resource_metadata")
    assert [f["name"] for f in resources["fields"]] == ["ad_group", "campaign"]
    assert "category = 'RESOURCE'" in ads.queries()[0]
    assert ads.requests[0][2]["request"]["page_size"] == 200
    fields = call(build(), "resource_metadata", name="campaign", limit=2)
    assert "LIKE 'campaign.%'" in ads.queries()[1]
    assert fields["fields"][0] == {"name": "campaign.id", "category": "ATTRIBUTE",
                                   "data_type": "INT64", "selectable": True, "filterable": True,
                                   "sortable": True, "is_repeated": False}
    assert fields["rows_returned"] == 2 and fields["complete"] is False


def test_resource_metadata_detail_is_bounded(ads):
    out = call(build(), "resource_metadata", name="campaign.status", detail=True, limit=2)
    field = out["fields"][0]
    assert field["enum_values"] == ["ENABLED", "PAUSED"] and field["enum_values_total"] == 3
    assert field["selectable_with"] == ["segments.date", "segments.device"]
    assert out["complete"] is False
    assert call(build(), "resource_metadata", name="campaign.status", detail=True)["complete"]


@pytest.mark.parametrize("args,category", [
    ({"name": "missing.field", "detail": True}, "not_found"),
    ({"detail": True}, "invalid_argument"),
    ({"name": "campaign' OR name LIKE '%"}, "invalid_argument"),
    ({"limit": 501}, "invalid_argument"),
])
def test_resource_metadata_refusals(ads, args, category):
    assert call(build(), "resource_metadata", **args)["error"] == category


def test_account_audit_returns_a_bounded_summary(ads):
    out = call(build(), "account_audit", customer_id=CUSTOMER, limit=1)
    assert set(out["agents"]) == {name for name, _ in gads_audit.DEFAULT_AGENTS}
    assert all(set(agent) <= {"status", "summary", "findings"} for agent in out["agents"].values())
    assert out["failed_agents"] == []
    assert out["total_findings"] >= 2
    assert out["findings"][0]["severity"] == "critical"
    assert out["rows_returned"] == 1 and out["complete"] is False
    full = call(build(), "account_audit", customer_id=CUSTOMER, limit=200)
    ranks = [gads_mcp._SEVERITY.get(f.get("severity"), 9) for f in full["findings"]]
    assert ranks == sorted(ranks) and full["complete"] is True


def test_account_audit_reports_failed_agents(monkeypatch):
    install(monkeypatch.setattr, raising(api_errors.PermissionDenied("x"), "FROM conversion_action"))
    out = call(build(), "account_audit", customer_id=CUSTOMER)
    assert out["agents"]["gads-conversions"] == {"status": "failed", "error": "permission_denied"}
    assert out["failed_agents"] == ["gads-conversions"]
    assert out["complete"] is False


def test_account_audit_stops_once_on_auth_failure(ads):
    class SignedOut(FakeProvider):
        def get_credentials(self):
            raise gads_auth.AuthRequiredError("Run: python scripts/gads_auth.py --check")

    out = call(build(lambda profile: SignedOut()), "account_audit", customer_id=CUSTOMER)
    assert out == {"error": "auth_required", "hint": "Run: python scripts/gads_auth.py --check"}
    assert ads.requests == []


def test_anomalies_and_pacing(ads):
    out = call(build(), "anomalies_and_pacing", customer_id=CUSTOMER)
    assert out["anomalies"]["total"] == 1
    assert out["anomalies"]["items"][0]["metric"] == "cost_micros"
    campaigns = out["pacing"]["campaigns"]
    assert {c["campaign_id"] for c in campaigns} == {"111", "222"}
    deltas = [abs(c["delta_pct"]) for c in campaigns]
    assert deltas == sorted(deltas, reverse=True)
    assert out["rows_returned"] == 3 and out["complete"] is True
    paced = call(build(), "anomalies_and_pacing", customer_id=CUSTOMER, check="pacing", limit=1)
    assert "anomalies" not in paced and paced["complete"] is False
    assert len(paced["pacing"]["campaigns"]) == 1


def test_anomalies_need_a_longer_window_than_the_baseline(ads):
    out = call(build(), "anomalies_and_pacing", customer_id=CUSTOMER, days=10, baseline_days=10)
    assert out["error"] == "invalid_argument" and "baseline_days" in out["hint"]


def test_change_history_reduces_actors_to_domains(ads):
    out = call(build(), "change_history", customer_id=CUSTOMER, limit=2)
    assert "@" not in json.dumps(out)
    assert out["by_actor"] == {"agency.example": 2, "GOOGLE_ADS_RECOMMENDATIONS": 1}
    assert out["events"][0]["user_domain"] == "agency.example"
    assert out["events"][0]["changed_fields"] == "status"
    assert out["total"] == 3 and out["rows_returned"] == 2 and out["complete"] is False
    assert "LIMIT 500" in ads.queries()[0]
