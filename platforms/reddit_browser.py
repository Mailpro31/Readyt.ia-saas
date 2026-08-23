"""requests.Session-compatible adapter backed by a real Playwright/Chromium
browser context.

Background
----------
Confirmed live (2026-07-29): Reddit's old.reddit.com JSON endpoints (used
throughout reddit_web.py) return 403 for BOTH plain `requests` AND
`curl_cffi` (TLS-fingerprint impersonation) -- even with valid, freshly
captured session cookies on a residential IP. A real headless Chromium via
Playwright, with the SAME cookies, IS recognized as logged in. That means
the block isn't (just) IP or TLS fingerprint -- it needs whatever signal
only a real browser running real JS produces (Akamai-style bot detection).

What this does
---------------
`RedditBrowserSession` exposes the small slice of `requests.Session`'s API
that reddit_web.py actually uses (`.get`, `.post`, `.headers`, `.cookies`,
`.proxies`, `.mount`) so it's a drop-in replacement -- none of
reddit_web.py's ~2600 lines of call sites need to change.

Internally:
  1. On first use, launches one persistent headless Chromium context and
     does a real `page.goto("https://www.reddit.com/")` navigation (the
     exact step that was confirmed to get recognized as logged-in) to let
     any JS-driven anti-bot cookies/signals get set for real.
  2. All subsequent `.get`/`.post` calls reuse that same warmed context via
     Playwright's `context.request` (still the real Chromium network
     stack/cookie jar, just without a full page render -- fast).

One browser context per RedditWebBot instance, kept alive for the process
lifetime (closed via `.close()` if the caller wants to release it early).
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Dict, Optional
from urllib.parse import urlencode, urlparse

logger = logging.getLogger(__name__)


class _Response:
    """Minimal requests.Response-compatible wrapper around a Playwright
    APIResponse, covering exactly what reddit_web.py reads off responses."""

    def __init__(self, api_response):
        self._resp = api_response
        self.status_code = api_response.status
        self.headers = dict(api_response.headers)
        self.ok = 200 <= self.status_code < 400
        try:
            self._text = api_response.text()
        except Exception:
            self._text = ""

    @property
    def text(self) -> str:
        return self._text

    @property
    def content(self) -> bytes:
        try:
            return self._resp.body()
        except Exception:
            return self._text.encode("utf-8", errors="replace")

    def json(self):
        return json.loads(self._text)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code} for {self._resp.url}")


class _CookieJar:
    """Dict-like view over the Playwright context's cookies, compatible
    with the .update()/.set()/.get()/dict()/.items() usage in reddit_web.py.
    """

    def __init__(self, session: "RedditBrowserSession"):
        self._session = session

    def _snapshot(self) -> Dict[str, str]:
        ctx = self._session._ensure_context()
        return {c["name"]: c["value"] for c in ctx.cookies()}

    def update(self, cookies: Dict[str, str]):
        ctx = self._session._ensure_context()
        ctx.add_cookies([
            {"name": k, "value": v, "domain": ".reddit.com", "path": "/"}
            for k, v in cookies.items()
        ])
        # A fresh cookie set means the old warm-up is stale -- re-warm on
        # next request so the new session is the one that gets recognized.
        self._session._warmed = False

    def set(self, name: str, value: str):
        self.update({name: value})

    def get(self, name: str, default=None):
        return self._snapshot().get(name, default)

    def items(self):
        return self._snapshot().items()

    def keys(self):
        return self._snapshot().keys()

    def __iter__(self):
        return iter(self._snapshot())

    def __getitem__(self, name):
        return self._snapshot()[name]

    def __contains__(self, name):
        return name in self._snapshot()


class RedditBrowserSession:
    """Drop-in replacement for requests.Session, backed by a real browser."""

    WARM_URL = "https://www.reddit.com/"

    def __init__(self, user_agent: Optional[str] = None, proxy_url: Optional[str] = None):
        self.headers: Dict[str, str] = {}
        if user_agent:
            self.headers["User-Agent"] = user_agent
        self.proxies: Dict[str, str] = {}
        self.cookies = _CookieJar(self)

        self._proxy_url = proxy_url
        self._lock = threading.Lock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._warmed = False

    # requests.Session compatibility no-op (curl_cffi/requests fallback
    # paths call this to configure connection pooling; nothing to do here).
    def mount(self, *args, **kwargs):
        pass

    def _launch_kwargs(self) -> dict:
        kwargs = {"headless": True}
        if self._proxy_url:
            parsed = urlparse(self._proxy_url)
            kwargs["proxy"] = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                "username": parsed.username or "",
                "password": parsed.password or "",
            }
        return kwargs

    def _ensure_context(self):
        with self._lock:
            if self._context is not None:
                return self._context
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(**self._launch_kwargs())
            self._context = self._browser.new_context(
                user_agent=self.headers.get("User-Agent") or (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )
            )
            return self._context

    def _warm_up(self):
        """Real JS-executing navigation once per (re-)cookie-set, so any
        anti-bot signals a JS challenge sets are established for real
        before we start making fast context.request JSON calls."""
        if self._warmed:
            return
        ctx = self._ensure_context()
        page = ctx.new_page()
        try:
            page.goto(self.WARM_URL, timeout=30000)
            page.wait_for_timeout(2000)
            self._warmed = True
            logger.debug("RedditBrowserSession: warm-up navigation complete")
        except Exception as e:
            logger.warning(f"RedditBrowserSession: warm-up navigation failed: {e}")
        finally:
            page.close()

    def _merged_headers(self, extra: Optional[dict]) -> dict:
        merged = dict(self.headers)
        if extra:
            merged.update(extra)
        return merged

    def get(self, url, params=None, headers=None, timeout=10, **kwargs) -> _Response:
        ctx = self._ensure_context()
        self._warm_up()
        if params:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode(params)}"
        resp = ctx.request.get(
            url, headers=self._merged_headers(headers), timeout=timeout * 1000,
        )
        return _Response(resp)

    def post(self, url, data=None, json_body=None, headers=None, timeout=10, **kwargs) -> _Response:
        ctx = self._ensure_context()
        self._warm_up()
        req_kwargs = {"headers": self._merged_headers(headers), "timeout": timeout * 1000}
        if json_body is not None:
            req_kwargs["data"] = json_body
        elif data is not None:
            req_kwargs["form"] = data
        resp = ctx.request.post(url, **req_kwargs)
        return _Response(resp)

    def close(self):
        with self._lock:
            try:
                if self._context:
                    self._context.close()
                if self._browser:
                    self._browser.close()
                if self._playwright:
                    self._playwright.stop()
            except Exception:
                pass
            finally:
                self._context = None
                self._browser = None
                self._playwright = None
