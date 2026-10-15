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


def ad_policy_findings(rows: list[dict]) -> list[dict]:
    findings = []
    seen = set()
    for row in rows:
        campaign = row.get("campaign", {})
        ad = row.get("ad_group_ad", {})
        approval = ad.get("policy_summary", {}).get("approval_status")
        if (campaign.get("status") not in {"ENABLED", "PAUSED"}
                or ad.get("status") != "ENABLED"
                or approval not in {"DISAPPROVED", "APPROVED_LIMITED"}):
            continue
        entity = {"campaign_id": campaign.get("id"),
                  "ad_group_id": row.get("ad_group", {}).get("id"),
                  "ad_id": ad.get("ad", {}).get("id")}
        identity_key = tuple(entity.values())
        if identity_key in seen:
            continue
        seen.add(identity_key)
        findings.append({
            "severity": "high" if approval == "DISAPPROVED" else "medium",
            "code": "ad_" + approval.lower(),
            "entity": entity,
            "message": f"Enabled ad {entity['ad_id']} has policy approval status {approval}.",
        })
    return findings


def identity(finding: dict) -> tuple:
    entity = finding.get("entity") or {
        key: finding[key] for key in ("campaign_id", "ad_group_id", "resource_name", "bucket")
        if key in finding
    }
    # Legacy findings have no entity metadata. Keep distinct messages instead
    # of treating every occurrence of one code as the same account issue.
    subject = json.dumps(entity, sort_keys=True) if entity else finding.get("message", "")
    return (finding.get("agent"), finding.get("source_path", ""), finding.get("code"), subject)
