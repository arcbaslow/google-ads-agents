"""Explicit manager-tree discovery with per-root login routing."""

from collections import deque
from dataclasses import dataclass

import gads_client
import gads_errors
import gads_provider

QUERY = """
    SELECT customer_client.client_customer, customer_client.manager,
      customer_client.level, customer_client.status
    FROM customer_client WHERE customer_client.level <= 1
"""


@dataclass(frozen=True)
class LoginProvider:
    base: gads_provider.CredentialProvider
    login: str

    def get_credentials(self):
        return self.base.get_credentials()

    def get_developer_token(self):
        return self.base.get_developer_token()

    def get_login_customer_id(self):
        return self.login


def discover(roots: list[str], max_nodes: int = 1000) -> dict:
    if max_nodes < 1:
        raise ValueError("max_nodes must be positive")
    base = gads_provider.get_active_provider()
    targets, errors, visited = {}, {}, set()
    queue = deque((root, root) for root in sorted(set(roots)))
    while queue:
        root, cid = queue.popleft()
        if (root, cid) in visited:
            continue
        if len(visited) >= max_nodes:
            raise ValueError("Hierarchy limit reached; narrow the discovery roots")
        visited.add((root, cid))
        try:
            with gads_provider.bind_provider(LoginProvider(base, root)):
                rows = gads_client.search_stream(cid, QUERY)
            for row in rows:
                child = row["customer_client"]
                name = child["client_customer"]
                if not name.startswith("customers/") or not name[10:].isdigit():
                    raise ValueError("Malformed customer resource")
                child_id = name[10:]
                if child.get("status") != "ENABLED":
                    continue
                if child.get("manager", False):
                    queue.append((root, child_id))
                else:
                    targets.setdefault(child_id, root)
        except Exception as exc:
            errors[f"{root}/{cid}"] = gads_errors.describe(exc)
    return {"targets": targets, "errors": errors, "status": "partial" if errors else "ok"}
