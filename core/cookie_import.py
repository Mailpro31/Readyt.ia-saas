"""Shared cookie-import helpers (used by the web dashboard and Telegram bot).

Parses cookies pasted from a browser in any of three formats and writes them
to disk in the layout each platform's bot expects.
"""
from __future__ import annotations

import os
import json
from typing import Dict

# Cookies that must be present for a session to actually work, per platform.
KEY_COOKIES = {
    "reddit": ["reddit_session", "token_v2"],
    "twitter": ["auth_token", "ct0", "twid"],
}


def parse_cookie_blob(raw: str) -> Dict[str, str]:
    """Parse cookies from any supported paste format into a {name: value} dict.

    Supports:
      1. JSON array export (Cookie-Editor / browser extensions):
         [{"name": "...", "value": "...", ...}, ...]  (or a flat {name: value})
      2. document.cookie:  "name=value; name2=value2"
      3. Netscape/curl cookie file (tab-separated).
    """
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')):
        raw = raw[1:-1]

    cookie_dict: Dict[str, str] = {}

    # 1) JSON export from a browser cookie extension.
    if raw.startswith(("[", "{")):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for c in parsed:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        cookie_dict[str(c["name"])] = str(c["value"])
            elif isinstance(parsed, dict) and "name" not in parsed:
                for k, v in parsed.items():
                    if isinstance(v, str):
                        cookie_dict[k] = v
        except (ValueError, TypeError):
            pass

    lines = raw.splitlines()

    # 2) Netscape/curl tab-separated file.
    if not cookie_dict:
        is_netscape = any(
            line.strip().startswith(".") or "\t" in line
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        )
        if is_netscape:
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookie_dict[parts[5].strip()] = parts[6].strip()

    # 3) document.cookie "name=value; name2=value2".
    if not cookie_dict:
        flat = raw.replace("\n", " ").replace("\r", " ")
        for pair in flat.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, value = pair.split("=", 1)
                cookie_dict[name.strip()] = value.strip()

    return cookie_dict


def write_cookie_file(cookies_file: str, platform: str, cookie_dict: Dict[str, str]) -> None:
    """Write cookies to disk in the format the platform's bot expects.

    Twitter (twikit) wants a list of cookie objects; Reddit wants a flat dict.
    """
    os.makedirs(os.path.dirname(cookies_file) or ".", exist_ok=True)
    if platform == "twitter":
        data = [
            {"name": k, "value": v, "domain": ".x.com", "path": "/"}
            for k, v in cookie_dict.items()
        ]
    else:
        data = cookie_dict
    with open(cookies_file, "w") as f:
        json.dump(data, f, indent=2)
