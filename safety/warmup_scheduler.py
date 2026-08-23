"""Active account warm-up scheduler (Phase 1.0).

Cold Reddit accounts cannot safely be used for product promotion. This module
drives a progressive multi-day warm-up: for every account below the actionable
karma tier it schedules *neutral* actions (generic upvotes / bland comments on
product-unrelated subreddits) and, once both the karma and day-count thresholds
are met, graduates the account to ``ready`` — automatically, with no manual
step.

The scheduler is intentionally decoupled from Reddit auth: the orchestrator
supplies a factory that returns an authenticated ``RedditBot`` for a given
account config (see ``core/orchestrator.py``). This keeps all live-auth logic
in the platform layer and makes the scheduler unit-testable.

State lives in the ``warmup_progress`` SQLite table (see ``core/database.py``).
"""

import logging
import random
from datetime import datetime
from typing import Callable, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = {
    "enabled": True,
    "actions_per_day": [2, 2, 3, 3, 4, 4, 5, 6, 7, 8],
    "target_day_count": 10,
    "min_karma": 25,
    "upvote_ratio": 0.7,
    "max_actions_per_cycle": 4,
    "neutral_subreddits": ["AskReddit", "todayilearned", "NoStupidQuestions"],
    "neutral_comments": ["Thanks for sharing, this is interesting."],
}


class WarmupScheduler:
    """Plans, executes and graduates account warm-ups."""

    PLATFORM = "reddit"

    def __init__(
        self,
        db,
        account_mgr,
        config_path: str = "config/warmup.yaml",
        bot_factory: Optional[Callable[[Dict], object]] = None,
        alert_cb: Optional[Callable[[str], None]] = None,
        platform: str = "reddit",
        config_key: str = "warmup",
    ):
        self.db = db
        self.account_mgr = account_mgr
        self.config_path = config_path
        self.bot_factory = bot_factory
        self.alert_cb = alert_cb
        self.PLATFORM = platform
        self.config_key = config_key
        self.config = self._load_config()
        # Reddit graduates on karma; platforms without a karma signal (X)
        # graduate purely on days of warm-up. Overridable via config.
        self.require_karma = bool(
            self.config.get("require_karma", platform == "reddit")
        )
        # Human-readable name of the graduation metric, for dashboards.
        self.metric_name = "karma" if self.require_karma else "followers"

    # ── Config ─────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f) or {}
            cfg = {**_DEFAULT_CONFIG, **(data.get(self.config_key, {}))}
            return cfg
        except FileNotFoundError:
            logger.warning(
                "warmup config not found at %s — using defaults", self.config_path
            )
            return dict(_DEFAULT_CONFIG)

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", True))

    def _actions_target_for_day(self, day: int) -> int:
        ramp: List[int] = self.config.get("actions_per_day", [2])
        if not ramp:
            return 2
        return ramp[min(day, len(ramp) - 1)]

    # ── Registration ───────────────────────────────────────────────

    def register_account(self, username: str) -> None:
        """Insert a warming row for a new account (idempotent)."""
        self.db.upsert_warmup(
            username, self.PLATFORM,
            target_day_count=int(self.config.get("target_day_count", 10)),
        )
        logger.info("Warm-up registered for @%s (status=warming)", username)

    def sync_accounts(self) -> None:
        """Ensure every configured Reddit account below the actionable tier has
        a warm-up row. Accounts already at/above the tier are graduated at once.
        """
        accounts = self.account_mgr.load_accounts(self.PLATFORM)
        for acc in accounts:
            username = acc.get("username", "")
            if not username:
                continue
            existing = self.db.get_warmup(username, self.PLATFORM)
            if existing is not None:
                continue
            # Reddit: an already-established account (enough karma) skips warm-up.
            # Platforms without a karma signal (X) always warm up from scratch.
            if self.require_karma:
                karma = self.account_mgr.get_cached_karma(username)
                if karma is not None and karma >= self.config.get("min_karma", 25):
                    self.db.upsert_warmup(username, self.PLATFORM)
                    self.db.set_warmup_status(username, self.PLATFORM, "ready")
                    logger.info(
                        "@%s already warm (karma=%s) — marked ready", username, karma
                    )
                    continue
            self.register_account(username)

    # ── Graduation ─────────────────────────────────────────────────

    def _maybe_graduate(self, row: dict) -> bool:
        """Promote a warming account to ready when thresholds are met."""
        if row.get("status") != "warming":
            return False
        username = row["account_username"]
        min_days = self.config.get("target_day_count", 10)
        day = row.get("day_number", 0)
        day_ok = day >= min_days

        if self.require_karma:
            karma = self.account_mgr.get_cached_karma(username)
            metric_val = karma if karma is not None else row.get("karma_at_day", 0)
            metric_ok = metric_val >= self.config.get("min_karma", 25)
        else:
            # No karma signal (X): graduate on days of warm-up alone.
            metric_val = row.get("karma_at_day", 0)
            metric_ok = True

        if day_ok and metric_ok:
            self.db.set_warmup_status(username, self.PLATFORM, "ready")
            plat = "Reddit" if self.PLATFORM == "reddit" else "X"
            detail = (
                f"{self.metric_name}={metric_val}, day {day}"
                if self.require_karma else f"day {day}/{min_days}"
            )
            logger.info(
                "🎓 @%s (%s) graduated to READY (%s)", username, self.PLATFORM, detail
            )
            if self.alert_cb:
                try:
                    self.alert_cb(
                        f"🎓 {plat} account @{username} finished warm-up "
                        f"({detail}) — now cleared to promote Nova."
                    )
                except Exception:
                    pass
            return True
        return False

    def estimate_ready_day(self, row: dict) -> Optional[int]:
        """Rough estimate of the warm-up day on which the account graduates."""
        min_days = self.config.get("target_day_count", 10)
        return max(min_days, row.get("day_number", 0))

    # ── Execution ──────────────────────────────────────────────────

    def run_cycle(self) -> Dict[str, int]:
        """Run one warm-up cycle across all warming accounts.

        Returns a small stats dict for logging/observability.
        """
        stats = {"executed": 0, "graduated": 0, "skipped": 0}
        if not self.enabled:
            return stats

        self.sync_accounts()
        rows = [
            r for r in self.db.get_all_warmup(self.PLATFORM)
            if r.get("status") == "warming"
        ]
        if not rows:
            return stats

        budget = int(self.config.get("max_actions_per_cycle", 4))
        # Graduate first (cheap, no live calls needed).
        for row in rows:
            if self._maybe_graduate(row):
                stats["graduated"] += 1

        if self.bot_factory is None:
            # Bookkeeping-only mode (e.g. tests / no live auth).
            return stats

        # Refresh working rows after graduations.
        rows = [
            r for r in self.db.get_all_warmup(self.PLATFORM)
            if r.get("status") == "warming"
        ]
        random.shuffle(rows)
        today = datetime.utcnow().date().isoformat()

        for row in rows:
            if budget <= 0:
                break
            username = row["account_username"]
            done_today = (
                row["actions_today"] if row.get("last_action_date") == today else 0
            )
            target = self._actions_target_for_day(row.get("day_number", 0))
            if done_today >= target:
                stats["skipped"] += 1
                continue

            acc = self.account_mgr.get_account_by_username(self.PLATFORM, username)
            if not acc:
                continue
            if not self._execute_one(acc, username):
                continue
            budget -= 1
            stats["executed"] += 1

        return stats

    def _execute_one(self, acc: dict, username: str) -> bool:
        """Perform a single neutral action for one account."""
        try:
            bot = self.bot_factory(acc)
        except Exception as e:
            logger.warning("Could not build bot for @%s: %s", username, e)
            return False

        if not hasattr(bot, "neutral_warmup_action"):
            logger.debug(
                "Bot for @%s has no neutral_warmup_action — skipping", username
            )
            return False

        if self.PLATFORM == "reddit":
            subs = self.config.get("neutral_subreddits", []) or ["AskReddit"]
            subreddit = random.choice(subs)
            is_upvote = random.random() < float(self.config.get("upvote_ratio", 0.7))
            comment_text = None
            if not is_upvote:
                comments = self.config.get("neutral_comments", []) or [
                    "Thanks for sharing."
                ]
                comment_text = random.choice(comments)
            result = bot.neutral_warmup_action(subreddit, comment_text=comment_text)
            where = f"r/{subreddit}"
        else:
            # X: like a niche tweet, occasionally follow the author.
            kws = self.config.get("neutral_keywords", []) or None
            follow_prob = float(self.config.get("follow_prob", 0.3))
            result = bot.neutral_warmup_action(keywords=kws, follow_prob=follow_prob)
            where = "X"

        if not result.get("ok"):
            return False

        # Refresh the graduation metric (karma for reddit, followers for X).
        if self.require_karma:
            metric = self.account_mgr.get_cached_karma(username)
            try:
                info = bot.get_account_info()
                if info and info.get("karma") is not None:
                    metric = int(info["karma"])
                    self.account_mgr.update_karma_cache(username, metric)
            except Exception:
                pass
            metric = metric if metric is not None else 0
        else:
            metric = 0
            try:
                info = bot.get_account_info()
                if info and info.get("followers") is not None:
                    metric = int(info["followers"])
            except Exception:
                pass

        self.db.record_warmup_action(username, self.PLATFORM, metric)
        logger.info(
            "Warm-up action for @%s on %s (%s), %s=%s",
            username, where, result.get("action"), self.metric_name, metric,
        )
        # A freshly-updated row may now satisfy graduation.
        updated = self.db.get_warmup(username, self.PLATFORM)
        if updated:
            self._maybe_graduate(updated)
        return True

    # ── Dashboard helpers ──────────────────────────────────────────

    def progress_view(self) -> List[Dict]:
        """Return a dashboard-friendly progress list for every warm-up row."""
        out = []
        target = int(self.config.get("target_day_count", 10))
        for row in self.db.get_all_warmup(self.PLATFORM):
            username = row["account_username"]
            if self.require_karma:
                karma = self.account_mgr.get_cached_karma(username)
                metric_val = karma if karma is not None else row.get("karma_at_day", 0)
                min_metric = self.config.get("min_karma", 25)
            else:
                metric_val = row.get("karma_at_day", 0)
                min_metric = 0
            day = row.get("day_number", 0)
            out.append({
                "platform": self.PLATFORM,
                "username": username,
                "status": row.get("status"),
                "day_number": day,
                "target_day_count": row.get("target_day_count", target),
                "progress_label": f"Jour {min(day, target)}/{target}",
                "progress_pct": round(min(day, target) / max(target, 1) * 100, 1),
                "metric_name": self.metric_name,
                "metric": metric_val,
                "min_metric": min_metric,
                # Backward-compat keys (reddit web dashboard).
                "karma": metric_val,
                "min_karma": self.config.get("min_karma", 25),
                "actions_today": row.get("actions_today", 0),
                "estimated_ready_day": self.estimate_ready_day(row),
            })
        return out
