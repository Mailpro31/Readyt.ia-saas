"""Unit tests for core/link_tracker.py (Phase 1.3)."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import Database
from core.link_tracker import LinkTracker, generate_slug, _append_utm, _normalize_host


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(path)
    yield database
    database.close()
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


@pytest.fixture
def settings():
    return {
        "features": {"link_tracking": True},
        "link_tracking": {"track_base_url": "https://track.example.com"},
    }


NOVA_CFG = {
    "project": {
        "name": "Nova",
        "base_url": "https://novaspeak.app",
        "business_profile": {"socials": {"website": "https://novaspeak.app"}},
    }
}


def test_generate_slug_unique_and_length(db):
    slugs = {generate_slug(db) for _ in range(200)}
    assert len(slugs) == 200                       # no collisions
    assert all(len(s) == 7 for s in slugs)


def test_slug_non_collision_against_db(db):
    tracker = LinkTracker(db, {"features": {"link_tracking": True}})
    seen = set()
    for _ in range(50):
        slug, _url = tracker.create_link("Nova", "https://novaspeak.app")
        assert slug not in seen
        assert db.slug_exists(slug)
        seen.add(slug)


def test_create_link_builds_tracked_url_and_utm(db, settings):
    tracker = LinkTracker(db, settings)
    slug, tracked = tracker.create_link(
        "Nova", "https://novaspeak.app", subreddit="ADHD",
        account_username="alice",
    )
    assert tracked == f"https://track.example.com/r/{slug}"
    row = db.get_tracked_link(slug)
    assert row["project"] == "Nova"
    assert row["subreddit"] == "ADHD"
    assert row["account_username"] == "alice"
    # UTM params appended to the stored target.
    assert "utm_source=reddit" in row["target_url"]
    assert f"utm_content={slug}" in row["target_url"]


def test_rewrite_content_replaces_only_product_url(db, settings):
    tracker = LinkTracker(db, settings)
    content = (
        "I use Nova for this, see https://novaspeak.app for details. "
        "Docs are at https://example.org/help though."
    )
    out = tracker.rewrite_content(content, NOVA_CFG, "Nova", subreddit="ADHD")
    assert "https://novaspeak.app" not in out         # product link rewritten
    assert "https://example.org/help" in out          # external link untouched
    assert "https://track.example.com/r/" in out


def test_rewrite_content_noop_when_disabled(db):
    tracker = LinkTracker(db, {"features": {"link_tracking": False}})
    content = "Check https://novaspeak.app now"
    assert tracker.rewrite_content(content, NOVA_CFG, "Nova") == content


def test_rewrite_content_www_variant_matched(db, settings):
    tracker = LinkTracker(db, settings)
    content = "Try https://www.novaspeak.app/download today"
    out = tracker.rewrite_content(content, NOVA_CFG, "Nova")
    assert "novaspeak.app/download" not in out
    assert "/r/" in out


def test_append_utm_preserves_existing_query():
    url = _append_utm("https://novaspeak.app/?ref=x", "abc123")
    assert "ref=x" in url
    assert "utm_source=reddit" in url
    assert url.count("?") == 1


def test_normalize_host():
    assert _normalize_host("https://www.novaspeak.app/path?q=1") == "novaspeak.app"
    assert _normalize_host("http://NovaSpeak.App") == "novaspeak.app"


def test_relative_fallback_when_no_base_url(db):
    tracker = LinkTracker(db, {"features": {"link_tracking": True}})
    slug, tracked = tracker.create_link("Nova", "https://novaspeak.app")
    assert tracked == f"/r/{slug}"
