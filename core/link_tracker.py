"""Link attribution for organic promotion (Phase 1.1).

Whenever generated content contains a link to the promoted product, this module
mints a short unique slug, stores the mapping (which project / subreddit /
account / thread produced it), and rewrites the raw product URL in the content
to a tracked redirect URL served by the dashboard (``GET /r/{slug}``).

Clicks are logged by the redirect endpoint (see ``dashboard/web.py``) so the
dashboard can show which threads / accounts / subreddits actually convert.

Design notes
------------
- Zero-cost: pure Python + SQLite, no external service.
- The public redirect base (``track_base_url``) MUST point at the running
  dashboard from the public internet. Documented as an infra dependency in the
  README — it is NOT assumed to already exist.
- Slugs are short (7 chars, base62) and collision-checked against the DB.
"""

import logging
import re
import secrets
from typing import List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger(__name__)

_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_SLUG_LEN = 7
_MAX_SLUG_ATTEMPTS = 12

# Matches http/https URLs inside generated text.
_URL_RE = re.compile(r"https?://[^\s\)\]\}>,\"']+", re.IGNORECASE)


def generate_slug(db, length: int = _SLUG_LEN) -> str:
    """Return a short, DB-unique base62 slug.

    Raises RuntimeError only in the astronomically unlikely event that every
    attempt collides.
    """
    for _ in range(_MAX_SLUG_ATTEMPTS):
        slug = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if not db.slug_exists(slug):
            return slug
    # Extremely unlikely — widen the space and try once more.
    slug = "".join(secrets.choice(_ALPHABET) for _ in range(length + 3))
    if not db.slug_exists(slug):
        return slug
    raise RuntimeError("Could not generate a unique slug")


class LinkTracker:
    """Mint and resolve tracked links for product URLs in generated content."""

    def __init__(self, db, settings: Optional[dict] = None):
        self.db = db
        self.settings = settings or {}

    # ── Config helpers ─────────────────────────────────────────────

    def _feature_enabled(self) -> bool:
        return bool(
            self.settings.get("features", {}).get("link_tracking", False)
        )

    def _track_base_url(self) -> str:
        """Public base URL of the redirect service, e.g. https://track.x.com.

        Falls back to a relative path so slugs are still stored and testable
        even before the infra is wired up.
        """
        base = (
            self.settings.get("link_tracking", {}).get("track_base_url", "")
            or ""
        ).rstrip("/")
        return base

    def build_tracked_url(self, slug: str) -> str:
        base = self._track_base_url()
        if base:
            return f"{base}/r/{slug}"
        # Relative fallback (works when dashboard is the public host).
        return f"/r/{slug}"

    @staticmethod
    def _project_base_urls(project: dict) -> List[str]:
        """Extract product base URL(s) from a project config.

        Reads ``project.base_url`` (Nova extension) and falls back to
        ``project.url`` and the socials website.
        """
        proj = project.get("project", project) if project else {}
        urls: List[str] = []
        for key in ("base_url", "url"):
            val = proj.get(key)
            if val:
                urls.append(str(val).rstrip("/"))
        website = (
            proj.get("business_profile", {})
            .get("socials", {})
            .get("website", "")
        )
        if website:
            urls.append(str(website).rstrip("/"))
        # De-dup preserving order.
        seen, out = set(), []
        for u in urls:
            norm = _normalize_host(u)
            if norm and norm not in seen:
                seen.add(norm)
                out.append(u)
        return out

    # ── Core API ───────────────────────────────────────────────────

    def create_link(
        self, project: str, target_url: str, subreddit: str = "",
        thread_url: str = "", account_username: str = "",
        persona: str = "", content_type: str = "",
    ) -> Tuple[str, str]:
        """Create a tracked link. Returns ``(slug, tracked_url)``.

        The ``target_url`` gets a ``utm_source=reddit&utm_content={slug}`` query
        appended so it can be cross-referenced with site analytics.
        """
        slug = generate_slug(self.db)
        final_target = _append_utm(target_url, slug)
        self.db.insert_tracked_link(
            project=project, slug=slug, target_url=final_target,
            subreddit=subreddit, thread_url=thread_url,
            account_username=account_username, persona=persona,
            content_type=content_type,
        )
        tracked = self.build_tracked_url(slug)
        logger.info(
            "Tracked link created: slug=%s project=%s subreddit=%s account=%s "
            "-> %s", slug, project, subreddit or "-",
            account_username or "-", final_target,
        )
        return slug, tracked

    def rewrite_content(
        self, content: str, project_cfg: dict, project_name: str,
        subreddit: str = "", thread_url: str = "",
        account_username: str = "", persona: str = "",
        content_type: str = "",
    ) -> str:
        """Replace any raw product URL in ``content`` with a tracked redirect.

        Only URLs whose host matches one of the project's base URLs are
        rewritten — external links (docs, unrelated sites) are left untouched.
        No-op (returns content unchanged) when link tracking is disabled or no
        product base URL is configured.
        """
        if not self._feature_enabled():
            return content
        bases = self._project_base_urls(project_cfg)
        if not bases:
            return content
        base_hosts = {_normalize_host(b) for b in bases}

        def _replace(match: "re.Match") -> str:
            raw = match.group(0)
            host = _normalize_host(raw)
            if host not in base_hosts:
                return raw  # not our product link
            try:
                _slug, tracked = self.create_link(
                    project=project_name, target_url=raw,
                    subreddit=subreddit, thread_url=thread_url,
                    account_username=account_username, persona=persona,
                    content_type=content_type,
                )
                return tracked
            except Exception as e:  # never break posting over a tracking error
                logger.error("Link rewrite failed, keeping raw URL: %s", e)
                return raw

        return _URL_RE.sub(_replace, content)


def _normalize_host(url: str) -> str:
    """Return a comparable host (lowercased, no scheme, no www, no path)."""
    if not url:
        return ""
    u = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    u = u.split("/")[0].split("?")[0].lower()
    if u.startswith("www."):
        u = u[4:]
    return u


def _append_utm(url: str, slug: str) -> str:
    """Append reddit UTM parameters, preserving any existing query string."""
    utm = f"utm_source=reddit&utm_content={quote(slug)}"
    if "#" in url:
        base, frag = url.split("#", 1)
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}{utm}#{frag}"
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{utm}"
