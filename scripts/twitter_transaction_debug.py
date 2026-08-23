#!/usr/bin/env python3
"""Dump X's current ondemand.s format so we can fix twikit's KEY_BYTE regexes.

Run this on a host that can reach x.com (e.g. the VPS). It fetches the X home
page and the ondemand.s JS bundle and prints the raw fragments twikit needs to
parse, so the exact current format is visible. Send the output back.

Usage:
    python3 scripts/twitter_transaction_debug.py
"""
import re
import sys

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def main():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

    print("== Fetching https://x.com/ ==")
    try:
        r = s.get("https://x.com/", timeout=30)
    except Exception as e:
        print(f"FAIL fetching home page: {e}")
        sys.exit(1)
    page = r.text
    print(f"status={r.status_code} bytes={len(page)}")

    # Show every occurrence of 'ondemand' with surrounding context
    print("\n== 'ondemand' occurrences in home page (±90 chars) ==")
    found = False
    for mobj in re.finditer(r".{0,90}ondemand[^\"']*.{0,90}", page):
        found = True
        print(repr(mobj.group(0)))
    if not found:
        print("(none found — page may be a migration/JS-redirect shell)")

    # Try to resolve the ondemand file hash (old + new heuristics)
    file_hash = None
    m = re.search(r"""['"]ondemand\.s['"]\s*:\s*['"]([\w]+)['"]""", page)
    if m:
        file_hash = m.group(1)
        print(f"\nOLD-format hash: {file_hash}")
    else:
        mi = re.search(r"""[,{]\s*(\w+)\s*:\s*['"]ondemand\.s['"]""", page)
        if mi:
            idx = mi.group(1)
            print(f"\nNEW-format chunk index for ondemand.s: {idx}")
            mh = re.search(r"""[,{]\s*""" + re.escape(idx) +
                           r"""\s*:\s*['"]([0-9a-fA-F]{6,})['"]""", page)
            if mh:
                file_hash = mh.group(1)
                print(f"NEW-format resolved hash: {file_hash}")
            else:
                print("Could NOT resolve idx -> hash. Fragments with that idx:")
                for mm in re.finditer(re.escape(idx) + r"""\s*:\s*['"][^'"]+['"]""", page):
                    print("  ", repr(mm.group(0)))

    if not file_hash:
        print("\nNo ondemand hash resolved — cannot fetch the JS. "
              "Copy the 'ondemand' fragments above and send them.")
        sys.exit(0)

    url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{file_hash}a.js"
    print(f"\n== Fetching ondemand JS ==\n{url}")
    try:
        jr = s.get(url, timeout=30)
    except Exception as e:
        print(f"FAIL fetching ondemand JS: {e}")
        sys.exit(1)
    js = jr.text
    print(f"status={jr.status_code} bytes={len(js)}")

    # Show candidate KEY_BYTE index patterns
    print("\n== KEY_BYTE index candidates in ondemand JS ==")
    old_hits = re.findall(r"\(\w\[(\d{1,3})\]\s*,\s*16\)", js)
    new_hits = re.findall(r"\[(\d{1,3})\]\s*,\s*16", js)
    print(f"OLD pattern '(x[NN],16)': {old_hits[:12]} (total {len(old_hits)})")
    print(f"NEW pattern '[NN],16'   : {new_hits[:12]} (total {len(new_hits)})")

    # Raw context around the first ',16' to see the real surrounding syntax
    j = js.find(",16")
    if j != -1:
        print("\nRaw context around first ',16':")
        print(repr(js[max(0, j - 60): j + 10]))


if __name__ == "__main__":
    main()
