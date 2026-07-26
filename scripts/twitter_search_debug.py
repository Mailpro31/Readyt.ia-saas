#!/usr/bin/env python3
"""Diagnostic: search succeeds with no error but returns 0 tweets — why?

Calls X's raw SearchTimeline GraphQL response (bypassing twikit's
higher-level Tweet parsing) and dumps its structure, so we can see whether:
  a) X genuinely returned no results, or
  b) X returned results but in a JSON shape twikit's parser doesn't expect
     (a silent breakage, distinct from the 404/transaction-id issues already
     patched).

Usage:
    python3 scripts/twitter_search_debug.py ["search query"]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from core.database import Database
from platforms.twitter_bot import TwitterBot, _run_async_safe


def _load_yaml(path: str) -> dict:
    if path.endswith(".yaml"):
        local = path[:-5] + ".local.yaml"
        if os.path.exists(local):
            path = local
    with open(path) as f:
        return yaml.safe_load(f) or {}


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "a"

    settings = _load_yaml("config/settings.yaml")
    accounts_cfg = _load_yaml("config/twitter_accounts.yaml")
    accounts = accounts_cfg.get("accounts", [])
    account = next(
        (a for a in accounts if a.get("enabled", True)
         and not a.get("username", "").startswith(("your_", "YOUR_"))),
        None,
    )
    if not account:
        print("FAIL: no usable X account in config/twitter_accounts.yaml")
        sys.exit(1)

    db = Database(settings["database"]["path"])
    bot = TwitterBot(db, None, account)

    print(f"Authenticating as @{account.get('username')} ...")
    _run_async_safe(bot.authenticate())
    print("OK. Now calling the RAW SearchTimeline GraphQL endpoint "
          f"for query={query!r}, product=Latest ...\n")

    async def _raw_search():
        response, resp_obj = await bot.client.gql.search_timeline(
            query, "Latest", 20, None
        )
        return response, resp_obj

    response, resp_obj = _run_async_safe(_raw_search())

    print(f"HTTP status: {resp_obj.status_code}")
    if isinstance(response, dict):
        print(f"Top-level keys: {list(response.keys())}")
        # Walk down to find 'instructions' the way twikit does.
        from twikit.utils import find_dict
        instructions = find_dict(response, "instructions", find_one=True)
        print(f"\n'instructions' found: {bool(instructions)}")
        if instructions:
            instr = instructions[0]
            print(f"  {len(instr)} instruction(s) at top level")
            entries = find_dict(instr, "entries", find_one=True)
            print(f"  'entries' found: {bool(entries)}")
            if entries:
                items = entries[0]
                print(f"  {len(items)} entr(y/ies)")
                entry_ids = [it.get("entryId", "?") for it in items[:10]]
                print(f"  Sample entryIds: {entry_ids}")
                tweet_like = [
                    it for it in items
                    if it.get("entryId", "").startswith(("tweet", "search-grid"))
                ]
                print(f"  Of those, {len(tweet_like)} look like actual tweets "
                      f"(entryId starts with 'tweet'/'search-grid')")

                # Deep-dive into ONE real entry with our own patch's exact
                # extraction logic, so we see PRECISELY why it does/doesn't
                # resolve a valid tweet — instead of guessing.
                if tweet_like:
                    entry = tweet_like[0]
                    print(f"\n  == Deep dive on entry {entry.get('entryId')} ==")
                    content = entry.get("content", {})
                    print(f"  entry['content'] keys: {list(content.keys())}")
                    item_content = content.get("itemContent", {})
                    print(f"  content['itemContent'] keys: {list(item_content.keys())}")

                    from platforms.twikit_patch import _extract_tweet_data
                    tweet_data, how = _extract_tweet_data(entry)
                    print(f"  _extract_tweet_data() resolved via: {how}")
                    if tweet_data:
                        print(f"  resolved dict keys: {list(tweet_data.keys())}")
                        print(f"  has 'core': {'core' in tweet_data}")
                        print(f"  has 'legacy': {'legacy' in tweet_data}")
                        print(f"  has 'tweet' (visibility wrapper): {'tweet' in tweet_data}")
                        if "tweet" in tweet_data:
                            inner = tweet_data["tweet"]
                            print(f"  inner tweet dict keys: {list(inner.keys()) if isinstance(inner, dict) else inner}")
                        if "core" not in tweet_data and "core" not in tweet_data.get("tweet", {}):
                            print("\n  'core' missing everywhere — dumping the full "
                                  "resolved dict (first 4000 chars) for ground truth:")
                            print(json.dumps(tweet_data, indent=2)[:4000])
                    else:
                        print("  resolved to: None (nothing found at all)")
                        print("\n  Dumping the FULL raw entry (first 4000 chars) "
                              "for ground truth:")
                        print(json.dumps(entry, indent=2)[:4000])
            else:
                print("  → No 'entries' key anywhere in the instructions. "
                      "This means X's response used a different key/shape "
                      "than twikit expects.")
        else:
            print("→ No 'instructions' key anywhere in the response. "
                  "Dumping the full response (or first 3000 chars) below "
                  "so we can see the real shape:")
            dumped = json.dumps(response, indent=2)[:3000]
            print(dumped)
    else:
        print(f"Response is not a dict: {type(response)}")
        print(str(response)[:2000])

    # Also show what the high-level parsed API returns, for comparison.
    print("\n--- For comparison: twikit's parsed result ---")
    parsed = _run_async_safe(bot.client.search_tweet(query, "Latest"))
    print(f"Parsed tweet count: {len(parsed) if parsed else 0}")


if __name__ == "__main__":
    main()
