from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import gads_audit
import gads_provider


def test_audit_workers_inherit_bound_provider(monkeypatch):
    provider = object()
    original = gads_provider.get_active_provider()

    def read(customer_id, days):
        assert gads_provider.get_active_provider() is provider
        return {"customer_id": customer_id, "days": days}

    monkeypatch.setattr(gads_audit, "DEFAULT_AGENTS", [("read", read)])
    with gads_provider.bind_provider(provider):
        result = gads_audit.run("123-456-7890", days=7)
        assert gads_provider.get_active_provider() is provider

    assert result["agents"]["read"] == {
        "customer_id": "1234567890", "days": 7, "status": "ok",
    }
    assert gads_provider.get_active_provider() is original


def test_concurrent_multi_account_audits_keep_providers_isolated(monkeypatch):
    # Two callers, each with two accounts and two simultaneous adapter reads.
    barrier = Barrier(8, timeout=10)
    providers = {"a": object(), "b": object()}
    original = gads_provider.get_active_provider()

    def read(customer_id, days):
        before = gads_provider.get_active_provider()
        barrier.wait()
        assert gads_provider.get_active_provider() is before
        return {"tenant": next((k for k, v in providers.items() if v is before), None)}

    monkeypatch.setattr(gads_audit, "DEFAULT_AGENTS", [("one", read), ("two", read)])

    def audit(tenant):
        with gads_provider.bind_provider(providers[tenant]):
            return gads_audit.run_many(
                ["1111111111", "2222222222"], 7, None,
                account_workers=2, agent_workers=2,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {tenant: pool.submit(audit, tenant) for tenant in providers}
        results = {tenant: future.result() for tenant, future in futures.items()}

    for tenant, result in results.items():
        assert len(result["accounts"]) == 2
        for account in result["accounts"].values():
            assert account["agents"] == {
                name: {"tenant": tenant, "status": "ok"} for name in ("one", "two")
            }
    assert gads_provider.get_active_provider() is original


def test_empty_customer_list_does_not_run_adapters(monkeypatch):
    def unexpected(*args):
        raise AssertionError("no accounts to audit")

    monkeypatch.setattr(gads_audit, "run", unexpected)
    assert gads_audit.run_many([], 7, None) == {
        "accounts": {}, "summary": "audited 0 accounts",
    }
