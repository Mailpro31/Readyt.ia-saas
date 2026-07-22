"""Shadowban and restriction detection."""

import logging
import random
from typing import Dict

import requests

logger = logging.getLogger(__name__)

# Diverse user agents for unauthenticated Reddit JSON API calls
_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
]


def _run_async(coro):
    """Run an async coroutine safely from any context.

    Works whether called from a thread with no loop, or inside a running loop.
    Never crashes with 'event loop already running'.
    """
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    else:
        return asyncio.run(coro)


class BanDetector:
    """Detects shadowbans and restrictions on Reddit and Twitter."""

    def check_reddit_shadowban(self, bot_or_reddit, username: str) -> Dict:
        """Check for Reddit shadowban indicators.

        Works with both RedditWebBot (cookie-based) and PRAW reddit instances.
        Uses Reddit's public JSON API so no authentication is needed.
        """
        result = {
            "is_shadowbanned": False,
            "indicators": [],
            "confidence": "low",
        }

        try:
            # 1. Check if user profile is accessible (hard ban = 404)
            about_resp = requests.get(
                f"https://www.reddit.com/user/{username}/about.json",
                headers={"User-Agent": random.choice(_UAS)},
                timeout=10,
            )
            if about_resp.status_code == 404:
                result["indicators"].append("User profile returns 404 (suspended/deleted)")
                result["is_shadowbanned"] = True
                result["confidence"] = "high"
                return result

            if about_resp.status_code != 200:
                logger.debug(f"u/{username}: profile check returned {about_resp.status_code}")
                return result  # Can't check, return inconclusive

            # 2. Fetch recent comments via public JSON API
            comments_resp = requests.get(
                f"https://www.reddit.com/user/{username}/comments.json?limit=10&sort=new",
                headers={"User-Agent": random.choice(_UAS)},
                timeout=10,
            )
            if comments_resp.status_code != 200:
                logger.debug(f"u/{username}: comments fetch returned {comments_resp.status_code}")
                return result

            children = comments_resp.json().get("data", {}).get("children", [])
            comments = [c["data"] for c in children if c.get("kind") == "t1"]

            # No comments = new/quiet account, not a shadowban
            if not comments:
                logger.debug(f"u/{username}: no comments found (new/quiet account)")
                return result

            # Need enough samples for reliable detection
            if len(comments) < 3:
                logger.debug(f"u/{username}: only {len(comments)} comments, skipping check")
                return result

            # 3. Check indicator: all comments score <= 1
            low_score_count = sum(1 for c in comments if c.get("score", 1) <= 1)
            if low_score_count == len(comments):
                result["indicators"].append(
                    "All recent comments have score <= 1"
                )

            # 4. Check indicator: comments removed/hidden
            #    If a comment body is "[removed]" or the author is "[deleted]"
            removed_count = sum(
                1 for c in comments
                if c.get("body") in ("[removed]", "[deleted]")
                or c.get("author") == "[deleted]"
            )
            if removed_count >= 2:
                result["indicators"].append(
                    f"{removed_count}/{len(comments)} comments appear removed"
                )

            # 5. Check indicator: comments not appearing in subreddit listings
            #    Pick up to 3 comments and check if they're visible in the thread
            hidden_count = 0
            for comment in comments[:3]:
                permalink = comment.get("permalink")
                if not permalink:
                    continue
                try:
                    check_resp = requests.get(
                        f"https://www.reddit.com{permalink}.json",
                        headers={"User-Agent": random.choice(_UAS)},
                        timeout=8,
                    )
                    if check_resp.status_code == 404:
                        hidden_count += 1
                except Exception:
                    pass  # Network errors are not indicators

            if hidden_count >= 2:
                result["indicators"].append(
                    f"{hidden_count}/3 comment permalinks return 404"
                )

            # Require 2+ STRONG indicators for shadowban detection
            if len(result["indicators"]) >= 2:
                result["is_shadowbanned"] = True
                result["confidence"] = "high"
            elif len(result["indicators"]) == 1:
                result["confidence"] = "low"

        except Exception as e:
            logger.error(f"Shadowban check failed for u/{username}: {e}")
            # API errors are NOT indicators — return inconclusive

        return result

    def check_twitter_restriction(self, client, username: str) -> Dict:
        """Check for Twitter account restrictions. Safe for sync/async contexts."""
        result = {
            "is_restricted": False,
            "indicators": [],
        }

        try:
            import asyncio

            async def _check():
                tweets = await client.search_tweet(
                    f"from:{username}", product="Latest"
                )
                return list(tweets) if tweets else []

            tweets = _run_async(_check())

            if not tweets:
                result["indicators"].append("No own tweets found in search")
                # Don't immediately mark restricted — could be indexing delay
                logger.debug(f"@{username}: no tweets in search (may be delay)")

        except Exception as e:
            logger.error(f"Twitter restriction check failed for @{username}: {e}")
            # API errors are NOT restriction indicators

        return result
