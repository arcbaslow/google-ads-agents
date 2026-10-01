# Read-only interoperability

This repository keeps its flat adapters and local session boundary. No MCP
server is included. The bounded interoperability path is a reviewed GAQL
query executed here, followed by a saved JSON or CSV export for another tool.

## Map the workflow

| Need | Toolkit path | Boundary |
| --- | --- | --- |
| Discover directly accessible customers | `gads_auth.py --customers` | Current signed-in identity; not a complete manager tree |
| Audit a manager tree | `gads_audit.py --all-customers --include-managed` | Explicit expansion, per-root login routing and partial-discovery errors |
| Inspect field definitions | Official reference for the selected API version | Metadata does not prove field combinations or account eligibility |
| Run a custom read | `gads_export.py --customer <id> --query-file report.gaql --limit 1000 --output report.json` | Session-gated SearchStream only; truncation is explicit |
| Share audit findings locally | `gads_export.py --audit-file audit.json --format csv --output findings.csv` | Saved evidence; no new account access |
| Feed existing monitoring | Saved-audit `--format prometheus` | Snapshot counts and failures; check freshness separately |

Review selected fields and date ranges, run the command during an authorised
session, check its exit code and truncation flag, then inspect the output
before sharing it. Campaign names, search terms and account IDs can be private
even when no credentials are included. Failed adapters are missing evidence;
keep their status when importing the export into another report.

## Upstream comparison

Google's [Google Ads MCP](https://github.com/googleads/google-ads-mcp) documents
`search`, `get_resource_metadata` and `list_accessible_customers` tools, plus
API metadata resources. These are useful reference workflows. Its own
authentication and deployment are separate from this repository: running
that server does not invoke `gads_auth.enforce_session()` or this session hook.
It is therefore not a drop-in route around a blocked local session. This pass
did not install it, connect credentials or verify its runtime safety.

[cohnen/mcp-google-ads](https://github.com/cohnen/mcp-google-ads) documents GAQL
and export workflows. The local exporter addresses that occasional reporting
need without introducing a server. Verify all query fields against the
[selected version's reference](https://developers.google.com/google-ads/api/fields/v25/overview),
including examples copied from other repositories.

If a native interface is proposed later, its acceptance conditions include
the existing provider and session gate on every account read, explicit
customer scope, bounded result sizes, redacted errors and mocked expired-session
tests. Writes remain outside this read-only interface. A new hosted service,
autonomous renewal and background account access remain rejected for this pass.
