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

We don't bundle an image generator. Google Ads' free PMax generator
lives in the UI and isn't on the API; everything else (Imagen,
Midjourney, DALL-E) is paid and bring-your-own.

Search image extensions use the same `attach` subcommand with
`--campaign-id` and `--field-type IMAGE`.
