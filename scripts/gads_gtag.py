"""Static HTML tag detection and account conversion-tracking IDs.

Does not verify GA4 links, consent, enhanced conversions or event delivery.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request

import gads_client
import gads_errors
import gads_utils

GTAG_PATTERNS = [
    re.compile(r"gtag\(\s*['\"]config['\"]\s*,\s*['\"]AW-\d+['\"]"),
    re.compile(r"gtag\(\s*['\"]config['\"]\s*,\s*['\"]G-[A-Z0-9]+['\"]"),
    re.compile(r"googletagmanager\.com/gtag/js"),
    re.compile(r"googletagmanager\.com/gtm\.js"),
    re.compile(r"GTM-[A-Z0-9]+"),
]


def scan_site(url: str) -> dict:
    if not url.startswith("http"):
        url = "https://" + url
    out = {"url": url, "reachable": False, "tags_found": []}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gads-agents/0.1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read(500_000).decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        out.update(gads_errors.describe(e))
        return out
    out["reachable"] = True
    for pat in GTAG_PATTERNS:
        for m in pat.finditer(html):
            out["tags_found"].append(m.group(0))
    out["has_gtag"] = bool(out["tags_found"])
    out["consent_evidence"] = {
        "mentioned_in_html": [signal for signal in (
            "ad_storage", "analytics_storage", "ad_user_data", "ad_personalization",
        ) if re.search(r"\b" + signal + r"\b", html)],
        "runtime_verified": False,
        "limitations": "Text presence only, including comments. A CMP may inject settings at runtime; absence is inconclusive.",
    }
    return out


def linked_accounts(customer_id: str) -> dict:
    q = """
        SELECT
          customer.id,
          customer.descriptive_name,
          customer.conversion_tracking_setting.conversion_tracking_id,
          customer.conversion_tracking_setting.cross_account_conversion_tracking_id
        FROM customer
    """
    rows = gads_client.search_stream(customer_id, q)
    return {"customer": rows[0] if rows else {}}


@gads_errors.cli
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--customer", required=True)
    p.add_argument("--site", help="Site URL to scan for gtag/GTM presence")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    cid = gads_utils.normalize_customer_id(args.customer)

    data = {"customer_id": cid, "linked": linked_accounts(cid)}
    if args.site:
        data["site_scan"] = scan_site(args.site)
    gads_utils.emit(data, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
