#!/usr/bin/env python3
"""Diagnostic: can a real headless Chromium (via Playwright) reach Reddit
from this machine, using the already-saved cookies, where plain HTTP
(requests/curl) gets blocked?

Usage:
    python3 scripts/test_playwright_reddit.py [cookies_file] [proxy_url]

Prints PASS/FAIL plus a short snippet of what the page actually shows,
and saves a screenshot to data/playwright_test.png for visual proof.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright

cookies_file = sys.argv[1] if len(sys.argv) > 1 else "data/cookies/reddit_ArchiTekte_.json"
proxy_url = sys.argv[2] if len(sys.argv) > 2 else None

if not os.path.exists(cookies_file):
    print(f"FAIL: cookies file not found: {cookies_file}")
    sys.exit(1)

with open(cookies_file) as f:
    raw_cookies = json.load(f)

pw_cookies = [
    {"name": name, "value": value, "domain": ".reddit.com", "path": "/"}
    for name, value in raw_cookies.items()
]

launch_kwargs = {"headless": True}
context_kwargs = {}
if proxy_url:
    # Playwright wants {"server": "http://host:port", "username":..., "password":...}
    from urllib.parse import urlparse
    parsed = urlparse(proxy_url)
    launch_kwargs["proxy"] = {
        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
        "username": parsed.username or "",
        "password": parsed.password or "",
    }

with sync_playwright() as p:
    browser = p.chromium.launch(**launch_kwargs)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    )
    context.add_cookies(pw_cookies)
    page = context.new_page()
    try:
        # www.reddit.com (modern site) wasn't blocked in the previous run,
        # unlike old.reddit.com. Load the homepage and look for the logged-in
        # username to confirm the session/cookies are actually recognized.
        page.goto("https://www.reddit.com/", timeout=30000)
        page.wait_for_timeout(3000)  # let the React app hydrate
        content = page.content()
        title = page.title()
    except Exception as e:
        print(f"FAIL: navigation error: {e}")
        browser.close()
        sys.exit(1)

    os.makedirs("data", exist_ok=True)
    page.screenshot(path="data/playwright_test.png")

    print(f"Page title: {title!r}")
    print(f"Content snippet: {content[:300]!r}")

    if "Blocked" in title or "Blocked" in content[:500]:
        print("FAIL: still blocked, even via real Chromium")
    elif "ArchiTekte" in content:
        print("PASS: logged-in username found on page — session recognized!")
    elif "log in" in content.lower() or "se connecter" in content.lower():
        print("PARTIAL: page loaded (not blocked) but appears logged OUT")
    else:
        print("UNCLEAR: neither a clear block nor clear success — check the screenshot")

    browser.close()
