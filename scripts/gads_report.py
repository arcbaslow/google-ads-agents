"""Render the audit-merge JSON to markdown or HTML."""

from __future__ import annotations

import argparse
import html
import json
import sys


def render_markdown(audit: dict) -> str:
    parts: list[str] = []
    parts.append(f"# Google Ads audit — customer {audit.get('customer_id', '?')}")
    parts.append("")
    parts.append(
        f"Window: {audit.get('date_range', {}).get('start', '?')} "
        f"to {audit.get('date_range', {}).get('end', '?')}"
    )
    parts.append("")
    parts.append("## Summary")
    parts.append("")
    for agent, out in audit.get("agents", {}).items():
        if out.get("status") == "failed":
            summary = f"failed: {out.get('error', '?')}"
        else:
            summary = out.get("summary") or out.get("status") or "no summary"
        parts.append(f"- **{agent}**: {summary}")
    parts.append("")

    findings = _collect_findings(audit)
    if findings:
        parts.append("## Findings")
        parts.append("")
        by_sev: dict[str, list[dict]] = {"critical": [], "high": [], "medium": [], "low": []}
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


def render_html(audit: dict) -> str:
    md = render_markdown(audit)
    body = (
        html.escape(md)
        .replace("\n## ", "\n</section>\n<section><h2>")
        .replace("\n# ", "\n<h1>")
        .replace("\n### ", "\n<h3>")
        .replace("\n- ", "\n<li>")
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Google Ads audit</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:48rem;margin:2rem auto;padding:0 1rem;line-height:1.5}"
        "h1{font-size:1.5rem;margin-top:0}"
        "h2{font-size:1.2rem;border-bottom:1px solid #ddd;padding-bottom:.25rem}"
        "section{margin-top:1.5rem}"
        "li{margin-left:1rem}"
        "code,pre{background:#f6f6f6;padding:.1rem .3rem;border-radius:.2rem}"
        "</style></head><body><pre>"
        + body +
        "</pre></body></html>"
    )


def _collect_findings(audit: dict) -> list[dict]:
    findings: list[dict] = []
    for agent, out in audit.get("agents", {}).items():
        for f in out.get("findings", []) or []:
            findings.append({"agent": agent, **f})
    return findings


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="audit JSON file")
    p.add_argument("--output", help="output path (default: stdout)")
    p.add_argument("--format", choices=["md", "html"], default="md")
    args = p.parse_args()
    with open(args.input) as f:
        audit = json.load(f)
    text = render_markdown(audit) if args.format == "md" else render_html(audit)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
