---
name: gads-gtag
description: Static website tag detection and account conversion-tracking IDs.
user-invokable: true
argument-hint: "<customer-id> --site <url>"
license: MIT
metadata:
  version: "0.1.0"
---

Routes to the `gads-gtag` subagent.

Run `python scripts/gads_gtag.py --customer <id> --site <url> --json`.

Report site_scan (reachability and snippet matches) and linked (customer
conversion-tracking IDs). The scan reads static HTML; it does not run JavaScript.
No match does not prove tracking is absent, and a match does not prove delivery.
The adapter does not query GA4 links, enhanced-conversion enrollment, consent
signals or real conversion events. Do not certify measurement health from it.

`consent_evidence` lists consent signal names mentioned in fetched HTML, including
comments. It always marks runtime verification false. A CMP may inject settings
after load; neither presence nor absence proves consent behavior or compliance.
