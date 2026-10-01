"""Collect nested adapter findings and retain their source and entity identity."""

from __future__ import annotations

import json


def collect(audit: dict) -> list[dict]:
    found = []

    def walk(node, agent, path):
        if not isinstance(node, dict):
            return
        for finding in node.get("findings") or []:
            if isinstance(finding, dict):
                item = {**finding, "agent": agent}
                if path:
                    item["source_path"] = path
                found.append(item)
        for name, value in node.items():
            if name != "findings" and isinstance(value, dict):
                walk(value, agent, f"{path}.{name}" if path else name)

    for agent, output in (audit.get("agents") or {}).items():
        walk(output, agent, "")
    return found


def identity(finding: dict) -> tuple:
    entity = finding.get("entity") or {
        key: finding[key] for key in ("campaign_id", "ad_group_id", "resource_name", "bucket")
        if key in finding
    }
    # Legacy findings have no entity metadata. Keep distinct messages instead
    # of treating every occurrence of one code as the same account issue.
    subject = json.dumps(entity, sort_keys=True) if entity else finding.get("message", "")
    return (finding.get("agent"), finding.get("source_path", ""), finding.get("code"), subject)
