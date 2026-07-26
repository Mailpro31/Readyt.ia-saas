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
