"""Local audit exports and bounded, session-gated GAQL reads."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

import gads_client
import gads_errors
import gads_findings
import gads_utils


def query_rows(customer_id: str, query: str, limit: int = 1000) -> dict:
    cid = gads_utils.normalize_customer_id(customer_id)
    if not re.fullmatch(r"[0-9]+", cid) or type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError("Numeric customer and a limit of 1–10000 are required")
    query = query.strip()
    # This is a conservative input contract, not a GAQL semantic validator.
    masked = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", query)
    if any(c in masked.replace("''", "") for c in "'\";") or any(c in masked for c in ("--", "/*", "*/", "#")):
        raise ValueError("Use a single query without comments or statement separators")
    field = r"[a-z_][a-z_0-9]*(?:\.[a-z_][a-z_0-9]*)+"
    match = re.match(rf"SELECT\s+{field}(?:\s*,\s*{field})*\s+FROM\s+[a-z_]+\b", masked, re.I)
    if not match:
        raise ValueError("Specify selected fields and a resource using SELECT and FROM")
    tail = masked[match.end():].strip()
    if (tail and not re.match(r"(?:WHERE|ORDER\s+BY)\b", tail, re.I)) or re.search(
        r"\b(?:SELECT|FROM|LIMIT|PARAMETERS)\b", tail, re.I
    ):
        raise ValueError("Use WHERE or ORDER BY; supply the row limit through --limit")
    executed = query + f" LIMIT {limit + 1}"
    # This helper constructs the client through the active provider and session gate.
    rows = gads_client.search_stream(cid, executed)
    return {"customer_id": cid, "status": "ok", "limit": limit,
            "truncated": len(rows) > limit, "rows": rows[:limit]}


def audit_rows(document: dict) -> list[dict]:
    if not isinstance(document, dict):
        raise ValueError("Expected an audit object")
    accounts = document.get("accounts")
    if accounts is None:
        accounts = {document.get("customer_id", "unknown"): document}
    if not isinstance(accounts, dict):
        raise ValueError("Expected accounts keyed by customer ID")
    rows = []
    for cid, audit in sorted(accounts.items()):
        if not isinstance(audit, dict) or not isinstance(audit.get("agents"), dict):
            raise ValueError("Each account must contain an agents object")
        common = {"customer_id": str(cid), "date_range": audit.get("date_range", {})}
        rows.append({**common, "kind": "account", "status": "ok"})
        for agent, result in sorted(audit["agents"].items()):
            if not isinstance(result, dict):
                raise ValueError("Each adapter result must be an object")
            # Retain failures without re-exporting raw legacy provider messages.
            rows.append({**common, "kind": "adapter", "agent": agent,
                         "status": result.get("status", "ok"),
                         "error_code": result.get("error_code", "")})
        for finding in gads_findings.collect(audit):
            rows.append({**finding, **common, "kind": "finding"})
    discovery = document.get("discovery")
    if isinstance(discovery, dict) and discovery.get("status") != "ok":
        rows.append({"kind": "discovery", "status": discovery.get("status", "unknown")})
    return rows


def _flatten(data: dict, prefix: str = "") -> dict:
    result = {}
    for key, value in sorted(data.items()):
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            result.update(_flatten(value, name))
        else:
            result[name] = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
    return result


def _csv_cell(value):
    # Quoting a CSV field alone does not prevent spreadsheet formula evaluation.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_text(rows: list[dict]) -> str:
    flat = [_flatten(row) for row in rows]
    columns = sorted({key for row in flat for key in row})
    if not columns:
        return ""
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow([_csv_cell(c) for c in columns])
    for row in flat:
        writer.writerow([_csv_cell(row.get(c, "")) for c in columns])
    return out.getvalue()


def prometheus_text(rows: list[dict]) -> str:
    counts = Counter()
    statuses = {}
    for row in rows:
        cid = row.get("customer_id")
        if row["kind"] == "account":
            statuses[cid] = 0
            for severity in ("critical", "high", "medium", "low", "info", "unknown"):
                counts[cid, severity] += 0
        elif row["kind"] == "adapter" and row.get("status") != "ok":
            statuses[cid] = statuses.get(cid, 0) + 1
        elif row["kind"] == "finding":
            severity = row.get("severity")
            if severity not in {"critical", "high", "medium", "low", "info"}:
                severity = "unknown"
            counts[cid, severity] += 1

    def label(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    lines = ["# TYPE gads_findings gauge", "# TYPE gads_failed_adapters gauge",
             "# TYPE gads_discovery_incomplete gauge"]
    for (cid, severity), count in sorted(counts.items()):
        lines.append(f'gads_findings{{customer_id="{label(cid)}",severity="{severity}"}} {count}')
    for cid, count in sorted(statuses.items()):
        lines.append(f'gads_failed_adapters{{customer_id="{label(cid)}"}} {count}')
    incomplete = any(r["kind"] == "discovery" for r in rows)
    lines.append(f"gads_discovery_incomplete {int(incomplete)}")
    return "\n".join(lines) + "\n"


@gads_errors.cli
def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--audit-file")
    source.add_argument("--query-file")
    parser.add_argument("--customer")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--format", choices=["json", "csv", "prometheus"], default="json")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.query_file:
        if not args.customer or args.format == "prometheus":
            parser.error("Queries require --customer and JSON or CSV output")
        result = query_rows(args.customer, Path(args.query_file).read_text(encoding="utf-8"), args.limit)
        rows = result["rows"]
        if result["truncated"]:
            print("Row limit reached; export is truncated.", file=sys.stderr)
    else:
        rows = audit_rows(json.loads(Path(args.audit_file).read_text(encoding="utf-8")))
        result = {"rows": rows, "source": "saved_audit"}
    if args.format == "json":
        output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    elif args.format == "csv":
        output = csv_text(rows)
    else:
        output = prometheus_text(rows)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8", newline="")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
