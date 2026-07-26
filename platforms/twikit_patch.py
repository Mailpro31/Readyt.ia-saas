"""Runtime patch for twikit 2.3.3's broken x-client-transaction-id generation.

Background
----------
Around 2026-03-18 X changed its webpack ``ondemand.s`` bundle so that:

  * the home page no longer embeds the ondemand file hash directly
    (old: ``"ondemand.s":"<hash>"``); it now maps a numeric *chunk index* to
    the name ``ondemand.s`` and, separately, that index to the hash, and
  * the KEY_BYTE indices inside the ondemand JS changed from ``(a[N], 16)``
    to a bare ``[N], 16``.

twikit 2.3.3 (the latest release) still uses the old regexes, so
``ClientTransaction.get_indices`` raises ``Couldn't get KEY_BYTE indices``
and every authenticated request fails. This affects ALL twikit users
regardless of IP/cookies. Upstream fix (d60/twikit#411) is not released yet.

What this does
--------------
Monkeypatches ``ClientTransaction.get_indices`` with a version that tries the
OLD format first (backward compatible) and falls back to the NEW format, so it
keeps working whichever X currently serves. On total failure it raises an
exception that *embeds a diagnostic snippet* of what it actually found around
"ondemand" in the page — so a single real run against X tells us the exact
current format if further tuning is needed.

Idempotent: safe to call multiple times. Never raises at import/apply time —
if twikit's internals moved, it logs and no-ops so the rest of the app is fine.
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_applied = False
_applied_gql = False

# ── OLD format (twikit 2.3.3 default) ────────────────────────────────────
# home page:  "ondemand.s":"<hash>"      →  hash
_OLD_ONDEMAND_HASH = re.compile(
    r"""['"]ondemand\.s['"]\s*:\s*['"]([\w]+)['"]"""
)
# ondemand JS: (a[NN], 16)               →  NN
_OLD_INDICES = re.compile(r"""\(\w\[(\d{1,3})\]\s*,\s*16\)""")

# ── NEW format (X, ~2026-03-18, per d60/twikit#411) ──────────────────────
# home page:  ,<idx>:"ondemand.s"        →  idx   (chunk-id → name map)
_NEW_ONDEMAND_IDX = re.compile(
    r"""[,{]\s*(\w+)\s*:\s*['"]ondemand\.s['"]"""
)
# home page:  ,<idx>:"<hash>"            →  hash  (chunk-id → contenthash map)
def _new_hash_pattern(idx: str) -> "re.Pattern":
    return re.compile(
        r"""[,{]\s*""" + re.escape(idx) + r"""\s*:\s*['"]([0-9a-fA-F]{6,})['"]"""
    )
# ondemand JS: [NN], 16                  →  NN
_NEW_INDICES = re.compile(r"""\[(\d{1,3})\]\s*,\s*16""")

_ONDEMAND_URL = "https://abs.twimg.com/responsive-web/client-web/ondemand.s.{}a.js"


def _find_ondemand_hash(page: str):
    """Return (hash, how) resolving the ondemand file hash from the home page,
    trying the old direct format first, then the new indexed format."""
    m = _OLD_ONDEMAND_HASH.search(page)
    if m:
        return m.group(1), "old-direct"

    m = _NEW_ONDEMAND_IDX.search(page)
    if m:
        idx = m.group(1)
        hm = _new_hash_pattern(idx).search(page)
        if hm:
            return hm.group(1), f"new-indexed(idx={idx})"
    return None, None


def _extract_indices(js_text: str):
    """Return list of KEY_BYTE indices from the ondemand JS, trying new then old."""
    idx = [int(x) for x in _NEW_INDICES.findall(js_text)]
    if idx:
        return idx, "new"
    idx = [int(x) for x in _OLD_INDICES.findall(js_text)]
    if idx:
        return idx, "old"
    return [], None


def _diag_snippet(page: str) -> str:
    """A short snippet of the page around 'ondemand' to aid debugging."""
    i = page.find("ondemand")
    if i == -1:
        return "(no 'ondemand' substring found in page)"
    return page[max(0, i - 80): i + 80].replace("\n", " ")


async def _patched_get_indices(self, home_page_response, session, headers):
    """Drop-in replacement for ClientTransaction.get_indices (old + new format)."""
    response = self.validate_response(home_page_response) or self.home_page_response
    page = str(response)

    file_hash, how = _find_ondemand_hash(page)
    if not file_hash:
        raise Exception(
            "Couldn't locate ondemand.s hash in home page "
            f"(old+new patterns failed). Snippet: …{_diag_snippet(page)}…"
        )

    url = _ONDEMAND_URL.format(file_hash)
    js_resp = await session.request(method="GET", url=url, headers=headers)
    js_text = getattr(js_resp, "text", "") or ""

    indices, kind = _extract_indices(js_text)
    if not indices:
        raise Exception(
            "Couldn't get KEY_BYTE indices from ondemand JS "
            f"(resolved via {how}, url={url}, {len(js_text)} bytes; "
            "old+new index patterns failed)."
        )

    logger.debug(
        "twikit_patch: KEY_BYTE indices OK via %s / %s-indices (%d indices)",
        how, kind, len(indices),
    )
    return indices[0], indices[1:]


def apply_twikit_patch() -> bool:
    """Monkeypatch twikit's ClientTransaction.get_indices. Returns True if applied.

    Safe and idempotent; never raises.
    """
    global _applied
    if _applied:
        return True
    try:
        from twikit.x_client_transaction import transaction as _tx
        _tx.ClientTransaction.get_indices = _patched_get_indices
        _applied = True
        logger.info(
            "Applied twikit x-client-transaction-id patch "
            "(handles X's post-2026-03-18 ondemand format)"
        )
        return True
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not apply twikit transaction patch: %s", e)
        return False


# =============================================================================
# GraphQL query-ID resolution patch
# =============================================================================
"""
Background
----------
Every twikit GraphQL call (search, reply/CreateTweet, like, follow, retweet,
...) hits a URL of the form
    https://x.com/i/api/graphql/<queryId>/<OperationName>
where <queryId> is a hash X assigns per operation and rotates on frontend
deploys — independently of the ondemand.s/transaction-id issue above. twikit
2.3.3 hardcodes one ID per operation (see twikit/client/gql.py Endpoint.*). If
X rotated an ID and twikit's copy is stale, X returns a plain 404 for that
call — confirmed live: ALL 8 search terms failed with
"NotFound: status: 404, message: \"\"" even though authentication itself
succeeded (a *different* symptom than the transaction-id break, which fails
at login, not per-operation).

What this does
---------------
Wraps GQLClient.gql_get / gql_post so that, on a 404 NotFound, it:
  1. Discovers the CURRENT queryId for that operation by fetching X's live
     webpack bundles (linked from the home page) and scanning them for
     "<queryId>"/"<OperationName>" pairs (several known minified encodings).
  2. Retries the call once with the fresh ID.
  3. Caches discovered IDs (process lifetime) so later calls to the same or
     other operations reuse the map instead of re-fetching bundles each time.
If discovery fails, the original error is raised unchanged — no worse than
before the patch.
"""
import asyncio
import time

_gql_id_cache: dict = {}
_gql_discovery_lock = None  # created lazily (needs a running loop)
_gql_last_discovery = 0.0
_GQL_DISCOVERY_MIN_INTERVAL = 300  # don't re-scan bundles more than every 5min

# Bare-URL match (no assumption about surrounding <script>/<link> markup or
# quote style) — X's bundle references may appear in <script src>, <link
# href> (modulepreload), or inline JSON/JS. This just looks for the URL
# string itself, which is far more robust to markup changes.
_BUNDLE_URL_RE = re.compile(
    r"""https://abs\.twimg\.com/responsive-web/[^\s"'<>\\]+?\.js"""
)
# "queryId":"XXXX","operationName":"Foo"  (or reversed order)
_OPID_PATTERNS = [
    re.compile(r'"queryId"\s*:\s*"([\w-]{15,})"\s*,\s*"operationName"\s*:\s*"(\w+)"'),
    re.compile(r'"operationName"\s*:\s*"(\w+)"\s*,\s*"queryId"\s*:\s*"([\w-]{15,})"'),
    # webpack object-literal form: OperationName:{queryId:"XXXX"
    re.compile(r'(\w+)\s*:\s*\{\s*queryId\s*:\s*"([\w-]{15,})"'),
    re.compile(r'queryId\s*:\s*"([\w-]{15,})"\s*,\s*operationName\s*:\s*"(\w+)"'),
]


def _get_lock() -> "asyncio.Lock":
    global _gql_discovery_lock
    if _gql_discovery_lock is None:
        _gql_discovery_lock = asyncio.Lock()
    return _gql_discovery_lock


_DISCOVERY_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def _discover_gql_query_ids(*_args, **_kwargs) -> dict:
    """Fetch X's live JS bundles and extract operationName -> queryId pairs.

    Uses a dedicated, cookie-free HTTP client (never the account's
    authenticated session): reusing the logged-in session to fetch the public
    home page can make X set a second guest cookie alongside the real one
    (e.g. a duplicate 'twid'), corrupting the account's cookie jar
    (httpx.CookieConflict on the next real request). Discovery only reads
    public JS, so it doesn't need — and must not touch — the account's cookies.
    """
    found: dict = {}
    try:
        import httpx
    except Exception as e:  # pragma: no cover - httpx is a twikit dependency
        logger.warning("twikit_patch: httpx unavailable for gql discovery: %s", e)
        return found

    headers = {"User-Agent": _DISCOVERY_UA, "Accept-Language": "en-US,en;q=0.9"}
    try:
        async with httpx.AsyncClient() as disco:
            home = await disco.get("https://x.com/", headers=headers, timeout=30)
            page = home.text

            bundle_urls = list(dict.fromkeys(_BUNDLE_URL_RE.findall(page)))[:20]
            if not bundle_urls:
                logger.warning("twikit_patch: no JS bundle URLs found on x.com home page")
                return found

            total_bytes = 0
            for url in bundle_urls:
                if total_bytes > 25_000_000:  # safety cap ~25MB total
                    break
                try:
                    resp = await disco.get(url, headers=headers, timeout=30)
                    text = resp.text
                    total_bytes += len(text)
                except Exception as e:
                    logger.debug("twikit_patch: bundle fetch failed for %s: %s", url, e)
                    continue

                for pattern in _OPID_PATTERNS:
                    for m in pattern.finditer(text):
                        g1, g2 = m.group(1), m.group(2)
                        # Two possible group orders depending on pattern; the
                        # queryId is the long hash-like token, operationName
                        # is a plain word.
                        if len(g1) > len(g2) and not g1.isalpha():
                            query_id, op_name = g1, g2
                        else:
                            op_name, query_id = g1, g2
                        found.setdefault(op_name, query_id)
    except Exception as e:
        logger.warning("twikit_patch: gql discovery failed: %s", e)
        return found

    logger.info(
        "twikit_patch: gql discovery scanned %d bundle(s), found %d operation IDs",
        len(bundle_urls), len(found),
    )
    return found


async def _resolve_query_id(gql_client, operation_name: str, hardcoded_id: str,
                             force: bool = False) -> str:
    """Return the best-known queryId for an operation, discovering if needed."""
    global _gql_last_discovery
    if not force and operation_name in _gql_id_cache:
        return _gql_id_cache[operation_name]

    now = time.time()
    async with _get_lock():
        # Re-check after acquiring the lock (another call may have just discovered).
        if not force and operation_name in _gql_id_cache:
            return _gql_id_cache[operation_name]
        if not force and (now - _gql_last_discovery) < _GQL_DISCOVERY_MIN_INTERVAL:
            return hardcoded_id
        _gql_last_discovery = now
        discovered = await _discover_gql_query_ids()
        _gql_id_cache.update(discovered)

    return _gql_id_cache.get(operation_name, hardcoded_id)


def _split_gql_url(url: str):
    """Return (prefix, hardcoded_query_id, operation_name) from a twikit gql URL."""
    parts = url.rsplit("/", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


async def _fresh_url(gql_client, url: str, force: bool = False) -> str:
    split = _split_gql_url(url)
    if not split:
        return url
    prefix, hardcoded_id, op_name = split
    fresh_id = await _resolve_query_id(gql_client, op_name, hardcoded_id, force=force)
    if fresh_id and fresh_id != hardcoded_id:
        return f"{prefix}/{fresh_id}/{op_name}"
    return url


def apply_twikit_gql_patch() -> bool:
    """Monkeypatch GQLClient.gql_get/gql_post to self-heal stale query IDs.

    Safe and idempotent; never raises. Covers search AND write operations
    (reply/CreateTweet, like, follow, retweet, ...) since they all go through
    the same two low-level methods.
    """
    global _applied_gql
    if _applied_gql:
        return True
    try:
        from twikit.client.gql import GQLClient
        orig_get = GQLClient.gql_get
        orig_post = GQLClient.gql_post

        async def _patched_get(self, url, variables, features=None, headers=None,
                                extra_params=None, **kwargs):
            fresh = await _fresh_url(self, url)
            try:
                return await orig_get(self, fresh, variables, features, headers, extra_params, **kwargs)
            except Exception as e:
                if type(e).__name__ != "NotFound":
                    raise
                logger.warning(
                    "twikit_patch: gql GET %s got 404, rediscovering query "
                    "IDs and retrying once", url.rsplit("/", 1)[-1],
                )
                retry_url = await _fresh_url(self, url, force=True)
                return await orig_get(self, retry_url, variables, features, headers, extra_params, **kwargs)

        async def _patched_post(self, url, variables, features=None, headers=None,
                                 extra_data=None, **kwargs):
            fresh = await _fresh_url(self, url)
            try:
                return await orig_post(self, fresh, variables, features, headers, extra_data, **kwargs)
            except Exception as e:
                if type(e).__name__ != "NotFound":
                    raise
                logger.warning(
                    "twikit_patch: gql POST %s got 404, rediscovering query "
                    "IDs and retrying once", url.rsplit("/", 1)[-1],
                )
                retry_url = await _fresh_url(self, url, force=True)
                return await orig_post(self, retry_url, variables, features, headers, extra_data, **kwargs)

        GQLClient.gql_get = _patched_get
        GQLClient.gql_post = _patched_post
        _applied_gql = True
        logger.info(
            "Applied twikit GraphQL query-ID self-healing patch "
            "(auto-discovers fresh operation IDs on 404, covers search + writes)"
        )
        return True
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not apply twikit gql-id patch: %s", e)
        return False


# =============================================================================
# Tweet-entry parsing patch
# =============================================================================
"""
Background
----------
Live diagnostic (scripts/twitter_search_debug.py) showed the RAW
SearchTimeline response is fine — 22 entries, 10 of them real tweets — but
twikit's parsed result was 0. twikit.tweet.tweet_from_data() locates each
tweet's data with a generic recursive search: "the first dict anywhere in
this entry that has a key called 'result'" (utils.find_dict(data, 'result',
find_one=True)). That is fragile: if X added ANY new sibling field to a
timeline entry that also happens to contain a 'result' key (common in
GraphQL — e.g. ad/metadata wrappers) and it appears earlier in iteration
order than the real tweet_results.result, find_dict grabs the wrong object,
the following 'core'/'legacy' checks fail, and the function silently returns
None for every tweet — no exception, no error, just an empty scan.

What this does
---------------
Monkeypatches tweet_from_data with a version that first navigates the KNOWN,
explicit path for a modern timeline entry
(content.itemContent.tweet_results.result) instead of the generic search,
falling back to the original generic search if that explicit path isn't
present (older/alternate entry shapes, e.g. quote tweets or profile timelines
still handled the old way). On total failure it logs a one-time diagnostic
of the entry's top-level keys so the real shape is visible if this guess
also needs tuning.

Must patch `twikit.client.client.tweet_from_data` (NOT `twikit.tweet.
tweet_from_data`): client.py does `from ..tweet import tweet_from_data`,
which binds its own local name — patching the original module has no effect
on calls made from client.py.
"""
_applied_parse = False
_parse_diag_logged = False


def _extract_tweet_data(data: dict):
    """Locate a tweet's result dict within a timeline entry.

    Tries the explicit modern path first, falls back to the original
    generic recursive search (twikit's default behaviour).
    """
    tweet_data = None
    try:
        tweet_data = (
            (data.get("content") or {})
            .get("itemContent", {})
            .get("tweet_results", {})
            .get("result")
        )
    except AttributeError:
        tweet_data = None

    how = "explicit-path"
    if not tweet_data:
        try:
            from twikit.utils import find_dict
            found = find_dict(data, "result", find_one=True)
            tweet_data = found[0] if found else None
            how = "generic-search"
        except Exception:
            tweet_data = None
            how = "none"

    return tweet_data, how


def _make_patched_tweet_from_data():
    from twikit.tweet import Tweet
    from twikit.user import User

    def _diag(reason: str, **ctx):
        global _parse_diag_logged
        if _parse_diag_logged:
            return
        _parse_diag_logged = True
        logger.warning(
            "twikit_patch: tweet parse failed (%s). Context: %s",
            reason, {k: (v if not isinstance(v, dict) else list(v.keys())[:15])
                     for k, v in ctx.items()},
        )

    def _patched(client, data):
        tweet_data, how = _extract_tweet_data(data)
        if not tweet_data:
            _diag("no tweet_data resolved at all")
            return None

        if tweet_data.get("__typename") == "TweetTombstone":
            return None
        if "tweet" in tweet_data:
            tweet_data = tweet_data["tweet"]

        if "core" not in tweet_data or "legacy" not in tweet_data:
            _diag(
                "missing core/legacy after resolution",
                how=how, resolved_keys=tweet_data,
            )
            return None

        core = tweet_data.get("core") or {}
        user_results = core.get("user_results") or {}
        if "result" not in user_results:
            _diag(
                "core.user_results.result missing",
                how=how, core_keys=core, user_results_keys=user_results,
            )
            return None

        user_data = user_results["result"]
        try:
            return Tweet(client, tweet_data, User(client, user_data))
        except Exception as e:
            # Don't let this vanish into client.py's broad `except KeyError:
            # tweet = None` — log exactly what failed, once, with a traceback.
            if not _parse_diag_logged:
                _parse_diag_logged = True
                logger.warning(
                    "twikit_patch: Tweet/User construction failed: %s: %s "
                    "(legacy_keys=%s, user_data_keys=%s)",
                    type(e).__name__, e,
                    list((tweet_data.get("legacy") or {}).keys())[:20],
                    list(user_data.keys())[:20] if isinstance(user_data, dict) else user_data,
                    exc_info=True,
                )
            raise

    return _patched


def apply_twikit_tweet_parse_patch() -> bool:
    """Monkeypatch tweet_from_data (as imported into client.py) to fix
    silent 0-results parsing. Safe and idempotent; never raises.
    """
    global _applied_parse
    if _applied_parse:
        return True
    try:
        from twikit.client import client as _client_mod
        patched = _make_patched_tweet_from_data()
        _client_mod.tweet_from_data = patched
        _applied_parse = True
        logger.info(
            "Applied twikit tweet-entry parsing patch "
            "(fixes silent 0-results when X adds new entry fields)"
        )
        return True
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not apply twikit tweet-parse patch: %s", e)
        return False
