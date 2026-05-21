"""Markdown report renderer for the audit fan-out output."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import gads_utils


def render_markdown(audit: dict) -> str:
    parts: list[str] = []
    parts.append(f"# Google Ads audit — customer {audit.get('customer_id', '?')}")
    parts.append("")
    parts.append(f"Window: {audit.get('date_range', {}).get('start', '?')} to {audit.get('date_range', {}).get('end', '?')}")
    parts.append("")
    parts.append("## Summary")
    parts.append("")
    for agent, out in audit.get("agents", {}).items():
        summary = out.get("summary") or out.get("status") or "no summary"
        parts.append(f"- **{agent}**: {summary}")
    parts.append("")
    findings = []
    for agent, out in audit.get("agents", {}).items():
        for f in out.get("findings", []) or []:
            findings.append({"agent": agent, **f})
    if findings:
        parts.append("## Findings")
        parts.append("")
        by_sev = {"critical": [], "high": [], "medium": [], "low": []}
        for f in findings:
            by_sev.setdefault(f.get("severity", "low"), []).append(f)
        for sev in ["critical", "high", "medium", "low"]:
            if not by_sev.get(sev):
                continue
            parts.append(f"### {sev}")
            parts.append("")
            for f in by_sev[sev]:
                parts.append(f"- [{f['agent']}] {f.get('message', '')}")
            parts.append("")
    return "\n".join(parts)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="audit JSON file")
    p.add_argument("--output", help="output md path (default: stdout)")
    args = p.parse_args()
    with open(args.input) as f:
        audit = json.load(f)
    md = render_markdown(audit)
    if args.output:
        with open(args.output, "w") as f:
            f.write(md)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
