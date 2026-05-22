---
name: gads-creative
description: Image asset wizard. Scrapes the site, drafts grounded prompts, generates images via Vertex Imagen or DALL-E, uploads to Google Ads, and attaches to PMax asset groups or Search campaigns. Confirmation gates between every step.
user-invokable: true
argument-hint: "<customer-id> <site-url>"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-creative` subagent. The agent runs the five-step
flow:

```
python scripts/gads_creative.py brief --site <url> --output /tmp/brief.json
python scripts/gads_creative.py prompts --brief /tmp/brief.json --output /tmp/prompts.json
python scripts/gads_creative.py generate --prompt "..." --size 1200x628 --provider vertex --output /tmp/assets/hero.png
python scripts/gads_creative.py upload --customer <CID> --image /tmp/assets/hero.png --apply --json
python scripts/gads_creative.py attach --customer <CID> --asset-resource "..." --asset-group-id <AG> --field-type MARKETING_IMAGE --apply --json
```

Vertex Imagen uses gcloud ADC and a Cloud project (either
`VERTEX_PROJECT` env or the ADC quota project). OpenAI DALL-E is a
fallback when `OPENAI_API_KEY` is set.

Search image extensions use the same `attach` subcommand with
`--campaign-id` and `--field-type IMAGE`.
