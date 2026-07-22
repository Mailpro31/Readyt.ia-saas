"""Recurring content templates for owned subreddit hubs.

Provides a weekly schedule of content types so hubs stay active
with varied, community-building posts.
"""

# Day of week → content template (Monday=0, Sunday=6)
HUB_CONTENT_SCHEDULE = {
    0: {  # Monday
        "type": "discussion",
        "template_key": "weekly_discussion",
        "prompt_hint": "Start a weekly discussion thread. Ask an open-ended question "
                       "about a challenge or trend in the niche. Encourage community "
                       "members to share their experiences.",
    },
    2: {  # Wednesday
        "type": "guide",
        "template_key": "tip_of_week",
        "prompt_hint": "Share a practical tip or mini-guide about the niche. "
                       "Focus on something actionable that readers can try today. "
                       "Write from personal experience, keep it concise.",
    },
    4: {  # Friday
        "type": "question",
        "template_key": "ask_community",
        "prompt_hint": "Post a 'Friday Ask' thread — invite the community to ask "
                       "questions, share wins from the week, or request feedback. "
                       "Keep the tone casual and welcoming.",
    },
}

# Fallback content types for days not in the schedule
FALLBACK_TYPES = ["news", "resource", "showcase"]
