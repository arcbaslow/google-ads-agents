import gads_accounts
import gads_audit
import gads_provider


def row(cid, manager=False, status="ENABLED"):
    return {"customer_client": {"client_customer": f"customers/{cid}",
                                "manager": manager, "status": status}}


def test_discovery_handles_nested_managers_duplicates_and_failed_root(monkeypatch):
    seen = []

    def search(cid, query):
        seen.append((cid, gads_provider.get_active_provider().get_login_customer_id()))
        if cid == "9":
            raise PermissionError("PRIVATE")
        return {"1": [row("1", True), row("2", True), row("3"), row("4", status="CANCELED")],
                "2": [row("1", True), row("3"), row("5")]}[cid]

    monkeypatch.setattr(gads_accounts.gads_client, "search_stream", search)
    result = gads_accounts.discover(["1", "9", "1"])
    assert result["targets"] == {"3": "1", "5": "1"}
    assert result["status"] == "partial"
    assert "9/9" in result["errors"]
    assert "PRIVATE" not in str(result)
    assert sorted(seen) == [("1", "1"), ("2", "1"), ("9", "9")]


def test_multi_account_dispatch_uses_correct_manager(monkeypatch):
    def read(cid, days):
        return {"login": gads_provider.get_active_provider().get_login_customer_id()}

    monkeypatch.setattr(gads_audit, "DEFAULT_AGENTS", [("read", read)])
    result = gads_audit.run_many(["3", "4"], 7, None, login_customer_ids={"3": "1", "4": "2"})
    assert result["accounts"]["3"]["agents"]["read"]["login"] == "1"
    assert result["accounts"]["4"]["agents"]["read"]["login"] == "2"
