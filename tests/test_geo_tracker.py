"""Unit tests for core/geo_tracker.py citation detection (Phase 1.3)."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import Database
from core.geo_tracker import GeoTracker, detect_citation

BRAND = ["Nova", "novaspeak", "novaspeak.app"]


# ── True positives ─────────────────────────────────────────────────

def test_detects_plain_nova():
    cited, snippet, pos = detect_citation(
        "For Windows I'd recommend Nova, it reformats as you speak.", BRAND,
    )
    assert cited
    assert "Nova" in snippet
    assert pos == 1


def test_detects_lapp_nova_french():
    cited, _s, _p = detect_citation(
        "L'app Nova est une bonne alternative offline.", BRAND,
    )
    assert cited


def test_detects_novaspeak_domain():
    cited, snippet, _p = detect_citation(
        "You can grab it from novaspeak.app for free.", BRAND,
    )
    assert cited
    assert "novaspeak" in snippet.lower()


def test_position_estimate_second_sentence():
    text = "There are many options. Nova is one of the newer ones."
    cited, _s, pos = detect_citation(text, BRAND)
    assert cited
    assert pos == 2


# ── True negatives / false-positive guards ─────────────────────────

def test_no_mention_returns_false():
    cited, snippet, pos = detect_citation(
        "Dragon and Otter.ai are the usual picks.", BRAND,
    )
    assert not cited
    assert snippet == ""
    assert pos == -1


def test_does_not_confuse_nova_launcher():
    cited, _s, _p = detect_citation(
        "Nova Launcher is a great Android home screen replacement.", BRAND,
    )
    assert not cited


def test_does_not_confuse_nova_scotia():
    cited, _s, _p = detect_citation(
        "I visited Nova Scotia last summer, lovely coastline.", BRAND,
    )
    assert not cited


def test_nova_substring_not_matched():
    # 'innovation' contains 'nova' but not as a whole word.
    cited, _s, _p = detect_citation(
        "This tool is all about innovation and speed.", BRAND,
    )
    assert not cited


def test_empty_text():
    assert detect_citation("", BRAND) == (False, "", -1)


# ── Tracker orchestration (dry-run, no network) ────────────────────

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


def test_run_dry_run_does_not_persist(db, monkeypatch):
    cfg = {
        "geo": {
            "enabled": True,
            "providers": [{"name": "openai", "enabled": True, "model": "x",
                           "api_key": "sk-test"}],
            "projects": {"nova": ["best dictation app windows"]},
        }
    }
    tracker = GeoTracker(db, cfg)
    # Stub the network call to return a Nova-citing answer.
    monkeypatch.setattr(
        tracker, "query_provider",
        lambda provider, query: "I recommend Nova for Windows dictation.",
    )
    results = tracker.run("nova", BRAND, dry_run=True, single=True)
    assert len(results) == 1
    assert results[0].cited is True
    # Nothing persisted in dry-run.
    assert db.get_geo_citations("nova") == []


def test_run_persists_when_not_dry(db, monkeypatch):
    cfg = {
        "geo": {
            "enabled": True,
            "providers": [{"name": "openai", "enabled": True, "model": "x",
                           "api_key": "sk-test"}],
            "projects": {"nova": ["best dictation app windows"]},
        }
    }
    tracker = GeoTracker(db, cfg)
    monkeypatch.setattr(
        tracker, "query_provider",
        lambda provider, query: "Nova is a solid choice.",
    )
    tracker.run("nova", BRAND, dry_run=False, single=True)
    stored = db.get_geo_citations("nova")
    assert len(stored) == 1
    assert stored[0]["cited"] == 1
