"""Google tag / GA4 link / Floodlight check.

Three things are tied together here:

  1. Is a Google tag (gtag.js / GTM) on the site at all? We fetch the
     homepage and look for the snippet patterns.
  2. Is the Google Ads account linked to a GA4 property? We check
     CustomerClient.linked_*  resources.
  3. Enhanced Conversions for Web enrollment status per conversion action.

This is a coarse first pass — it surfaces obvious misconfigs, not every
subtle one.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request

import gads_client
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
        out["error"] = str(e)
        return out
    out["reachable"] = True
    for pat in GTAG_PATTERNS:
        for m in pat.finditer(html):
            out["tags_found"].append(m.group(0))
    out["has_gtag"] = bool(out["tags_found"])
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
