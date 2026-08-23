#!/usr/bin/env python3
"""Diagnostic: can we discover X's CURRENT GraphQL queryId for SearchTimeline
(and other operations) from its live JS bundles?

Run this on a host that can reach x.com (e.g. the VPS). It exercises the same
discovery logic as platforms/twikit_patch.py's self-healing gql patch, and
prints exactly what it found — so if the adaptive patch still fails, this
tells us precisely what to adjust (bundle URLs found, operations discovered,
and the SearchTimeline ID it would use).

Usage:
    python3 scripts/twitter_gql_id_debug.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import yaml

from platforms.twikit_patch import _BUNDLE_URL_RE, _OPID_PATTERNS

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _load_account_cookies() -> dict:
    """Best-effort: load the first configured X account's cookies.

    An ANONYMOUS request to x.com gets a stripped-down logged-out landing
    page that doesn't reference the full app bundle set (confirmed live: 0
    bundle URLs found that way) — so discovery needs to look like a logged-in
    browser. This is a READ-ONLY copy used to seed a disposable httpx client;
    it never touches the account's real session.
    """
    try:
        with open("config/twitter_accounts.yaml") as f:
            accounts = (yaml.safe_load(f) or {}).get("accounts", [])
        for acc in accounts:
            cf = acc.get("cookies_file", "")
            if cf and os.path.exists(cf):
                with open(cf) as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    return {c["name"]: c["value"] for c in raw if "name" in c}
                if isinstance(raw, dict):
                    return raw
    except Exception as e:
        print(f"(couldn't load account cookies, continuing anonymously: {e})")
    return {}


async def main():
    seed_cookies = _load_account_cookies()
    print(f"Seeding request with {len(seed_cookies)} account cookie(s) "
          f"(read-only copy — real session untouched)\n")
    async with httpx.AsyncClient(cookies=seed_cookies) as http:
        print("== Fetching https://x.com/ ==")
        headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
        try:
            home = await http.get("https://x.com/", headers=headers, timeout=30)
        except Exception as e:
            print(f"FAIL: {e}")
            sys.exit(1)
        page = home.text
        print(f"status={home.status_code} bytes={len(page)}")

        bundle_urls = list(dict.fromkeys(_BUNDLE_URL_RE.findall(page)))
        print(f"\n== Found {len(bundle_urls)} JS bundle URL(s) ==")
        for u in bundle_urls[:20]:
            print(" ", u)
        if not bundle_urls:
            print("No bundle URLs matched — the regex in twikit_patch.py "
                  "(_BUNDLE_URL_RE) needs updating. Dumping <script src=...> "
                  "tags found on the page instead:")
            import re
            for m in re.finditer(r'<script[^>]+src="([^"]+)"', page):
                print(" ", m.group(1))
            sys.exit(0)

        found = {}
        total_bytes = 0
        for url in bundle_urls[:20]:
            try:
                resp = await http.get(url, headers=headers, timeout=30)
                text = resp.text
                total_bytes += len(text)
            except Exception as e:
                print(f"  (failed to fetch {url}: {e})")
                continue
            for pattern in _OPID_PATTERNS:
                for m in pattern.finditer(text):
                    g1, g2 = m.group(1), m.group(2)
                    if len(g1) > len(g2) and not g1.isalpha():
                        query_id, op_name = g1, g2
                    else:
                        op_name, query_id = g1, g2
                    found.setdefault(op_name, (query_id, url))

        print(f"\n== Scanned {total_bytes} bytes across bundles ==")
        print(f"== Discovered {len(found)} operation(s) ==")
        for op, (qid, src) in list(found.items())[:30]:
            print(f"  {op}: {qid}  (from {src.rsplit('/', 1)[-1]})")

        print("\n== SearchTimeline specifically ==")
        if "SearchTimeline" in found:
            qid, src = found["SearchTimeline"]
            print(f"FOUND: SearchTimeline -> {qid}")
            print(f"Hardcoded in twikit 2.3.3: flaR-PUMshxFWZWPNpq4zA")
            print("MATCH" if qid == "flaR-PUMshxFWZWPNpq4zA" else "DIFFERENT (this is the fix!)")
        else:
            print("NOT FOUND. Showing raw context around 'SearchTimeline' in "
                  "each bundle so we can fix the regex:")
            for url in bundle_urls[:20]:
                try:
                    resp = await http.get(url, headers=headers, timeout=30)
                    text = resp.text
                except Exception:
                    continue
                i = text.find("SearchTimeline")
                if i != -1:
                    print(f"\n  In {url.rsplit('/', 1)[-1]}:")
                    print("   ", repr(text[max(0, i - 150): i + 150]))


if __name__ == "__main__":
    asyncio.run(main())
