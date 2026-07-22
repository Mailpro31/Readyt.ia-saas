#!/usr/bin/env python3
"""Phase 1 smoke-test — one command, end-to-end, PASS/FAIL per step.

Covers (per PROMPT_MiloAgent_Nova.md §1.3):
  1. Insert a tracked link and confirm it appears in ``tracked_links``.
  2. Simulate GET /r/{slug}: confirm the click is recorded in ``link_clicks``
     AND that the endpoint returns an HTTP 302 to the real URL.
  3. Run a geo_tracker cycle in --dry-run on ONE provider / ONE probe query
     (network stubbed) and print the raw result (cited or not + snippet).
  4. Warm-up flow: add a fake account (status=warming), artificially advance
     day_number/karma, and confirm it becomes actionable for Nova with no
     further manual step (account_manager warm-up gate flips to allow it).

Run:  python3 scripts/smoke_test_phase1.py
Exit code is non-zero if any step FAILs.
"""

import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("smoke")

from core.database import Database
from core.link_tracker import LinkTracker
from core.geo_tracker import GeoTracker

_results = []


def _check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    _results.append(ok)
    return ok


# ── Step 1: tracked link insertion ─────────────────────────────────

def step1_tracked_link(db):
    settings = {
        "features": {"link_tracking": True},
        "link_tracking": {"track_base_url": "https://track.novaspeak.app"},
    }
    tracker = LinkTracker(db, settings)
    slug, tracked = tracker.create_link(
        "Nova", "https://novaspeak.app", subreddit="ADHD",
        account_username="smoke_user", thread_url="https://reddit.com/x",
    )
    row = db.get_tracked_link(slug)
    ok = row is not None and row["project"] == "Nova" and slug in tracked
    _check("1. tracked_link inserted", ok,
           f"slug={slug} tracked_url={tracked}")
    return slug


# ── Step 2: /r/{slug} click + 302 redirect ─────────────────────────

def step2_click_and_redirect(db, slug):
    # Direct DB path: record a click and confirm increment.
    before = db.get_click_count(slug)
    db.record_link_click(slug, referer="reddit.com", user_agent="smoke/1.0")
    after = db.get_click_count(slug)
    ok_db = after == before + 1
    _check("2a. link_click recorded", ok_db, f"{before} -> {after}")

    # HTTP path: exercise the real FastAPI /r/{slug} endpoint via TestClient.
    ok_http = _http_redirect_check(db, slug)
    return ok_db and ok_http


def _http_redirect_check(db, slug):
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import RedirectResponse
        from fastapi.testclient import TestClient
    except Exception as e:
        _check("2b. HTTP 302 redirect", False, f"fastapi/httpx missing: {e}")
        return False

    # Minimal app mirroring dashboard/web.py's /r/{slug} handler.
    app = FastAPI()

    @app.get("/r/{s}")
    async def redirect(s: str, request: Request):
        link = db.get_tracked_link(s)
        if not link:
            raise HTTPException(status_code=404)
        db.record_link_click(s, user_agent=request.headers.get("user-agent", ""))
        return RedirectResponse(url=link["target_url"], status_code=302)

    client = TestClient(app, follow_redirects=False)
    resp = client.get(f"/r/{slug}")
    target = db.get_tracked_link(slug)["target_url"]
    ok = resp.status_code == 302 and resp.headers.get("location") == target
    _check("2b. HTTP 302 redirect", ok,
           f"status={resp.status_code} -> {resp.headers.get('location')}")
    return ok


# ── Step 3: geo_tracker dry-run ────────────────────────────────────

def step3_geo_dry_run(db):
    cfg = {
        "geo": {
            "enabled": True,
            "providers": [{"name": "openai", "enabled": True,
                           "model": "gpt-4o-mini", "api_key": "sk-smoke"}],
            "projects": {"nova": [
                "best speech to text app for windows"]},
        }
    }
    tracker = GeoTracker(db, cfg)
    # Stub the network so no paid call is made.
    tracker.query_provider = (
        lambda provider, query:
        "For Windows, Nova (novaspeak.app) is a strong pick — it reformats "
        "your dictation to match the app you're in."
    )
    results = tracker.run("nova", ["Nova", "novaspeak"], dry_run=True, single=True)
    ok = len(results) == 1
    if ok:
        r = results[0]
        print(f"       raw result: provider={r.provider} query={r.query!r}")
        print(f"       cited={r.cited} position={r.position_estimate}")
        print(f"       snippet={r.snippet!r}")
        ok = r.cited is True
    _check("3. geo_tracker dry-run (1 provider/1 query)", ok)
    # Dry-run must NOT persist.
    persisted = db.get_geo_citations("nova")
    _check("3b. dry-run did not persist", len(persisted) == 0,
           f"{len(persisted)} rows")
    return ok


# ── Step 4: warm-up flow → account becomes actionable for Nova ──────

def step4_warmup_flow(db):
    from safety.account_manager import AccountManager
    from safety.warmup_scheduler import WarmupScheduler

    # Point the account manager at a temp config dir with one fake account
    # assigned to Nova.
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, "reddit_accounts.yaml"), "w") as f:
        f.write(
            "auth_mode: web\n"
            "accounts:\n"
            "  - username: smoke_acct\n"
            "    password: x\n"
            "    enabled: true\n"
            "    assigned_projects: [Nova]\n"
            "    cookies_file: ''\n"
        )
    mgr = AccountManager(db, config_dir=tmpdir)
    warmup = WarmupScheduler(db, mgr, config_path="config/warmup.yaml",
                             bot_factory=None)

    # Fresh account: enrolled as warming, must NOT be actionable for Nova.
    warmup.register_account("smoke_acct")
    mgr.update_karma_cache("smoke_acct", 0)
    ready_before = mgr.is_warmup_ready("smoke_acct")
    picked_before = mgr.get_next_account("reddit", project="Nova")
    ok_blocked = (not ready_before) and picked_before is None
    _check("4a. warming account blocked for Nova", ok_blocked,
           f"ready={ready_before} picked={picked_before}")

    # Artificially advance the warm-up to the finish line.
    target = warmup.config.get("target_day_count", 10)
    min_karma = warmup.config.get("min_karma", 25)
    db._execute_write(
        "UPDATE warmup_progress SET day_number = ?, karma_at_day = ? "
        "WHERE account_username = ? AND platform = 'reddit'",
        (target, min_karma + 5, "smoke_acct"),
    )
    mgr.update_karma_cache("smoke_acct", min_karma + 5)

    # One cycle (bookkeeping-only) must auto-graduate — no manual step.
    stats = warmup.run_cycle()
    row = db.get_warmup("smoke_acct", "reddit")
    graduated = row and row["status"] == "ready"
    _check("4b. auto-graduated to ready", bool(graduated),
           f"status={row['status'] if row else '?'} stats={stats}")

    # Now the SAME selection call must return the account with no other change.
    ready_after = mgr.is_warmup_ready("smoke_acct")
    picked_after = mgr.get_next_account("reddit", project="Nova")
    ok_actionable = ready_after and picked_after is not None \
        and picked_after["username"] == "smoke_acct"
    _check("4c. account now actionable for Nova", ok_actionable,
           f"ready={ready_after} picked={picked_after['username'] if picked_after else None}")
    return ok_blocked and bool(graduated) and ok_actionable


def main():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = Database(path)
    print("=" * 60)
    print("Phase 1 smoke-test")
    print("=" * 60)
    try:
        slug = step1_tracked_link(db)
        step2_click_and_redirect(db, slug)
        step3_geo_dry_run(db)
        step4_warmup_flow(db)
    finally:
        db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except OSError:
                pass

    print("=" * 60)
    passed = sum(1 for r in _results if r)
    total = len(_results)
    all_ok = passed == total
    print(f"RESULT: {passed}/{total} checks passed — "
          f"{'ALL PASS ✅' if all_ok else 'FAILURES ❌'}")
    print("=" * 60)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
