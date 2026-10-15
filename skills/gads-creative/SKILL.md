---
name: gads-creative
description: Creative briefs, image and YouTube video assets, and bounded Video responsive and responsive Display ad edits. Every write requires interactive review.
user-invokable: true
argument-hint: "<customer-id> <site-url>"
license: MIT
metadata:
  version: "0.2.0"
---

Routes to the `gads-creative` subagent. The agent runs `brief` and
`prompts`; the operator runs `upload` and `attach` in their own terminal:

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
the same operations. The prompt needs an interactive terminal, so give the
operator the command to run in their own terminal; do not pipe approval or
substitute a direct API call. stdout remains the JSON result.

Structured failure output uses `error_code`, a safe `error` message and a
`retryable` hint. No automatic retries are performed. For a failed write,
check account state before retrying; a timeout does not prove it was unapplied.

Treat redacted failures as unavailable evidence, not an empty or healthy result.
See docs/REPORTING.md for error categories. Never retry a write automatically.

For supplied videos and existing ads, use these independent commands:

```sh
python scripts/gads_creative.py upload-video --customer <CID> --file video.mp4 --title "Title" --apply --json
python scripts/gads_creative.py create-video-asset --customer <CID> --video-id Abc_def-123 --name "Video" --validate-only --json
python scripts/gads_creative.py edit-ad --customer <CID> --ad-id <AD> --input ad-edit.json --validate-only --json
```

Uploads have no API validation and no `--validate-only`. Without `--apply`,
only local checks run. Review the file path, size, title, channel and privacy
before upload. Processing polls every 10 seconds for up to 10 minutes. Asset
creation follows `PROCESSED` and requires a second review, with validation.
Retain the upload resource and video ID if this step returns
`uploaded_without_asset`; inspect uncertain writes before using
`create-video-asset`, or use `RemoveYouTubeVideoUpload` to remove the upload.

Privacy defaults to `UNLISTED`, which is viewable by link. Google-managed
channels allow only `UNLISTED`. Brand channels require `--channel-id` and user
OAuth, and allow `PUBLIC` or `UNLISTED`; service accounts are unsupported.

Ad edits accept only Video responsive ads in VIDEO campaigns and responsive
Display ads in DISPLAY campaigns. The Video input must include `videos`,
`business_name` and `logo_images`. Use inline text and same-customer asset
resource names; see docs/WRITES.md for the complete JSON contract. These are
AdService edits, not Video campaign mutations. Search image attachment now
checks that the selected campaign is SEARCH.
