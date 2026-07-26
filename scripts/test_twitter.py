#!/usr/bin/env python3
"""Diagnostic: does the configured X/Twitter account actually connect?

Runs the same authentication path the orchestrator uses (twikit cookies /
login), from inside the container, and prints a clear verdict so you don't
have to wait for the scan cycle.

Usage:
    python3 scripts/test_twitter.py [username]

If no username is given, the first enabled non-placeholder account in
config/twitter_accounts.yaml is used.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from core.database import Database
from platforms.twitter_bot import TwitterBot


def _load_yaml(path: str) -> dict:
    """Load YAML, preferring a .local.yaml override if present."""
    if path.endswith(".yaml"):
        local = path[:-5] + ".local.yaml"
        if os.path.exists(local):
            path = local
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _pick_account(accounts, wanted=None):
    for a in accounts:
        if not a.get("enabled", True):
            continue
        name = a.get("username", "")
        if name.startswith("your_") or name.startswith("YOUR_"):
            continue
        if wanted and name != wanted:
            continue
        return a
    return None


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else None

    settings = _load_yaml("config/settings.yaml")
    accounts_cfg = _load_yaml("config/twitter_accounts.yaml")
    accounts = accounts_cfg.get("accounts", [])

    account = _pick_account(accounts, wanted)
    if not account:
        print("FAIL: no usable X account found in config/twitter_accounts.yaml")
        print("      (add one via Telegram: /addtwitter user email pass nova)")
        sys.exit(1)

    username = account.get("username", "unknown")
    cookies_file = account.get("cookies_file", "")
    print(f"Testing X account: @{username}")
    print(f"Cookies file: {cookies_file} "
          f"({'exists' if os.path.exists(cookies_file) else 'MISSING'})")

    # Resolve proxy the same way the orchestrator does.
    http_cfg = settings.get("http", {})
    proxy = (
        account.get("proxy")
        or http_cfg.get("twitter_proxy")
        or http_cfg.get("proxy")
    )
    print(f"Proxy: {'yes' if proxy else 'none (direct)'}")

    db = Database(settings["database"]["path"])
    # content_gen is not needed for a pure connection test.
    bot = TwitterBot(db, None, account, proxy=proxy)

    print("\nConnecting to X ...")
    try:
        ok = bot.test_connection()
    except Exception as e:
        msg = str(e).lower()
        print(f"\nFAIL: {type(e).__name__}: {e}")
        if "226" in msg or "automated" in msg or "denied" in msg:
            print("→ X is blocking this IP (code 226 = 'automated behaviour').")
            print("  This is the datacenter/VPS IP problem — a residential IP")
            print("  (e.g. home Raspberry Pi) is the reliable fix.")
        elif "2fa" in msg or "totp" in msg or "confirmation" in msg or "code" in msg:
            print("→ X wants 2FA. Add `totp_secret` to config/twitter_accounts.yaml.")
        sys.exit(1)

    if ok:
        print("\nPASS: connected to X — the account is usable.")
        print("The bot will scan + reply on its next scan cycle (~10 min).")
        sys.exit(0)
    else:
        print("\nFAIL: could not authenticate (see the error log line above).")
        print("Common causes: expired cookies, wrong password, 2FA required,")
        print("or X blocking this IP (code 226 on VPS/datacenter ranges).")
        sys.exit(1)


if __name__ == "__main__":
    main()
