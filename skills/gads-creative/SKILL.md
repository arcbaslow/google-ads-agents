---
name: gads-creative
description: Image asset wizard. Scrapes the site, drafts grounded prompts, hands them to the user to generate however they like, then uploads PNGs and attaches them to PMax asset groups or Search campaigns. Confirmation gates between every step.
user-invokable: true
argument-hint: "<customer-id> <site-url>"
license: MIT
metadata:
  version: "0.2.0"
---

Routes to the `gads-creative` subagent. The agent runs the four-step
flow:

```
python scripts/gads_creative.py brief --site <url> --output /tmp/brief.json
python scripts/gads_creative.py prompts --brief /tmp/brief.json --output /tmp/prompts.json
# user generates images off-platform (Ads UI, Midjourney, designer, etc.)
python scripts/gads_creative.py upload --customer <CID> --image /tmp/hero.png --apply --json
python scripts/gads_creative.py attach --customer <CID> --asset-resource "..." --asset-group-id <AG> --field-type MARKETING_IMAGE --apply --json
```

We do not bundle an image generator. Supply images from a tool or designer
you choose; this adapter handles upload and attachment only.

Search image extensions use the same `attach` subcommand with
`--campaign-id` and `--field-type AD_IMAGE`.

The supported write adapters display the exact operation JSON and prompt for
`y/N` in Python, including for validation. `--apply` validates before sending
the same operations. Let the operator review and answer the prompt; do not
pipe approval or substitute a direct API call. stdout remains the JSON result.

Structured failure output uses `error_code`, a safe `error` message and a
`retryable` hint. No automatic retries are performed. For a failed write,
check account state before retrying; a timeout does not prove it was unapplied.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.
