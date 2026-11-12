# Google Ads Agents v0.7.0

Release date: 2026-11-12

This release extends the MCP server with keyword, ad, search-term and Performance Max asset reads, and adds gated write tools a host can register.

## Included

- Four bounded MCP read tools: `keywords`, `ads`, `search_terms` and `asset_group_assets`. They return the IDs the write tools take.
- Six MCP write tools through `register_writes(server, gate, prefix, provider_factory)`: keyword and ad status, campaign start and end dates, conversion action primary or secondary, campaign placement exclusions, and Performance Max asset group links.
- MCP writes run a `validate_only` dry run that returns a single-use confirm token. The confirmed call goes through the host's gate and sends once, with a 60-second deadline and no retry. Failures return only Google Ads error codes and field paths.
- The CLI writers send `validate_only` inside the request message, which google-ads 33 requires, and a test checks the call shape against the installed service signatures.
- Brand campaign tagging in pacing and recommendations, Demand Gen and App campaign writers, YouTube and Display creative writes, and the read-only MCP tool set from the earlier unreleased entries in the [changelog](../CHANGELOG.md).

## Validation

All 1073 CLI tests and all 70 hosted sign-in tests passed. Ruff passed.

Local validation used Windows and Python 3.12.14. The repository's CI matrix provides the other supported runtime/OS checks. All MCP tests run offline against a fake transport; no live ad account was read or written.

## Downloads

Use the source archive for the complete toolkit, including scripts, skills, configuration, documentation and demo fixtures. `SHA256SUMS.txt` records the attached artifact hashes. GitHub's automatically generated source downloads are also available.

Package-registry publishing is separate from this GitHub release and remains controlled by the existing opt-in repository settings. No claim is made that this version is published on PyPI.
