#!/usr/bin/env python3
"""Diagnostic script to debug low action counts."""

import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import Database
from core.orchestrator import Orchestrator
from safety.rate_limiter import RateLimiter

def main():
    db_path = "data/miloagent.db"
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return 1

    try:
        db = Database(db_path)

        print("=" * 80)
        print("ACTION COUNT DIAGNOSTIC REPORT")
        print("=" * 80)
        print(f"Report time: {datetime.now()}")
        print(f"Database: {db_path}")
        print()

        # Check last 24 hours of actions
        print("ACTIONS IN LAST 24 HOURS:")
        print("-" * 80)

        stats = db.get_stats_summary(hours=24)
        if stats:
            total = stats.get("total_actions", 0)
            by_platform = stats.get("by_platform", {})
            by_type = stats.get("by_type", {})

            print(f"Total actions: {total}")
            print(f"By platform: {by_platform}")
            print(f"By type: {by_type}")
        else:
            print("No stats available")
        print()

        # Check pending opportunities
        print("PENDING OPPORTUNITIES:")
        print("-" * 80)
        reddit_pending = db.get_pending_opportunities(platform="reddit", limit=50)
        twitter_pending = db.get_pending_opportunities(platform="twitter", limit=50)
        telegram_pending = db.get_pending_opportunities(platform="telegram", limit=50)

        print(f"Reddit: {len(reddit_pending)} pending opportunities")
        if reddit_pending:
            print(f"  Top 3 by score:")
            for opp in sorted(reddit_pending, key=lambda x: x.get("score", 0), reverse=True)[:3]:
                print(f"    - {opp.get('title', 'N/A')[:50]} (score: {opp.get('score', 'N/A')})")
        print()

        print(f"Twitter: {len(twitter_pending)} pending opportunities")
        if twitter_pending:
            print(f"  Top 3 by score:")
            for opp in sorted(twitter_pending, key=lambda x: x.get("score", 0), reverse=True)[:3]:
                print(f"    - {opp.get('title', 'N/A')[:50]} (score: {opp.get('score', 'N/A')})")
        print()

        print(f"Telegram: {len(telegram_pending)} pending opportunities")
        if telegram_pending:
            print(f"  Top 3 by score:")
            for opp in sorted(telegram_pending, key=lambda x: x.get("score", 0), reverse=True)[:3]:
                print(f"    - {opp.get('title', 'N/A')[:50]} (score: {opp.get('score', 'N/A')})")
        print()

        # Check active hours
        print("ACTIVE HOURS CHECK:")
        print("-" * 80)
        settings_path = "config/settings.yaml"
        if os.path.exists(settings_path):
            import yaml
            with open(settings_path) as f:
                settings = yaml.safe_load(f) or {}

            active_hours = settings.get("bot", {}).get("active_hours", [8, 23])
            print(f"Configured active hours: {active_hours[0]:02d}:00 - {active_hours[1]:02d}:00")

            # Check timezone
            tz = os.environ.get("TZ", "Not set (using system default)")
            print(f"Container TZ environment: {tz}")

            # Check current time
            now = datetime.now()
            utc_now = datetime.utcnow()
            print(f"Current local time: {now.strftime('%H:%M:%S %Z')}")
            print(f"Current UTC time: {utc_now.strftime('%H:%M:%S')}")

            # Check if within active hours
            hour = now.hour
            start, end = active_hours
            if start <= end:
                is_active = start <= hour < end
            else:
                is_active = hour >= start or hour < end

            print(f"Currently within active hours: {is_active}")
        print()

        # Check last action times
        print("LAST ACTIONS:")
        print("-" * 80)
        recent = db.db.execute(
            """SELECT timestamp, platform, type, project
               FROM actions
               ORDER BY timestamp DESC
               LIMIT 10"""
        ).fetchall()

        if recent:
            for row in recent:
                ts, platform, action_type, project = row
                print(f"  [{ts}] {platform:10} {action_type:15} {project}")
        else:
            print("  No recent actions found!")
        print()

        # Check scan status
        print("RECENT SCANS:")
        print("-" * 80)
        scans = db.db.execute(
            """SELECT timestamp, platform, count
               FROM scans
               ORDER BY timestamp DESC
               LIMIT 10"""
        ).fetchall()

        if scans:
            for row in scans:
                ts, platform, count = row
                print(f"  [{ts}] {platform:10} found {count} opportunities")
        else:
            print("  No scan records found!")
        print()

        # Check if any accounts exist
        print("CONFIGURED ACCOUNTS:")
        print("-" * 80)
        accounts_query = "SELECT COUNT(*) FROM accounts WHERE platform = ?"
        reddit_count = db.db.execute(accounts_query, ("reddit",)).fetchone()[0]
        twitter_count = db.db.execute(accounts_query, ("twitter",)).fetchone()[0]

        print(f"Reddit accounts: {reddit_count}")
        print(f"Twitter accounts: {twitter_count}")

        if reddit_count == 0:
            print("  WARNING: No Reddit accounts configured!")
        if twitter_count == 0:
            print("  WARNING: No Twitter accounts configured!")
        print()

        # Summary
        print("SUMMARY:")
        print("-" * 80)
        if total == 0:
            print("PROBLEM IDENTIFIED: Zero actions in last 24 hours!")
            print()
            if not reddit_pending and not twitter_pending and not telegram_pending:
                print("Likely causes:")
                print("  1. Scans are not finding opportunities (check scan logs)")
                print("  2. Opportunity scoring is too strict (score threshold too high)")
                print("  3. No accounts configured for the platforms")
                print("  4. Bot is outside active hours (check TZ environment variable)")
            else:
                print("Likely causes:")
                print("  1. Actions are blocked by rate limiting")
                print("  2. No suitable accounts for opportunities found")
                print("  3. Score threshold for actions is too high")
                print("  4. Account warmup status preventing actions")
        else:
            print(f"Actions found ({total} in 24h) - checking for issues...")
            if total < 3:
                print("WARNING: Very few actions (<3 per day) - consider:")
                print("  1. Increasing max_actions_per_hour in settings")
                print("  2. Lowering score threshold for pending opportunities")
                print("  3. Checking if accounts have proper permissions")

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
