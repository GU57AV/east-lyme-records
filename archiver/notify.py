"""Optional push notifications through ntfy (https://ntfy.sh).

Set these as GitHub Actions secrets to turn them on (nothing is sent if NTFY_TOPIC is missing):
  NTFY_TOPIC   the topic to publish to; on the public ntfy.sh server, pick a long, unguessable name,
               since anyone who knows it can read the messages
  NTFY_SERVER  optional, defaults to https://ntfy.sh (use your own server if you run one)
  NTFY_TOKEN   optional access token, for servers or topics that require one
  NTFY_REMINDER_TOPIC  optional, a separate topic for "deadline coming up" reminders (off unless set)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
FEED_ITEMS = ROOT / "state" / "feed_items.json"
FEED_KEEP = 200  # newest items kept per feed

PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


def record(title: str, message: str, click: str | None = None, feed: str = "alerts") -> None:
    """Add an item to a public RSS feed (rendered into feeds/ by feeds.py). Unlike ntfy pushes,
    this always happens, so anyone can follow the archive's alerts without any setup."""
    try:
        items = json.loads(FEED_ITEMS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    uid = hashlib.sha1(f"{feed}|{title}|{message}|{at}".encode()).hexdigest()[:16]
    items.append({"id": uid, "feed": feed, "title": title, "message": message, "link": click, "at": at})
    keep, counts = [], {}
    for it in reversed(items):
        counts[it["feed"]] = counts.get(it["feed"], 0) + 1
        if counts[it["feed"]] <= FEED_KEEP:
            keep.append(it)
    FEED_ITEMS.parent.mkdir(parents=True, exist_ok=True)
    FEED_ITEMS.write_text(json.dumps(list(reversed(keep)), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def notify(title: str, message: str, priority: str = "default", tags: list[str] | None = None,
           click: str | None = None, topic_env: str = "NTFY_TOPIC") -> bool:
    record(title, message, click, feed="reminders" if topic_env == "NTFY_REMINDER_TOPIC" else "alerts")
    topic = os.environ.get(topic_env, "").strip()
    if not topic:
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    payload = {"topic": topic, "title": title[:250], "message": message[:3900] or title,
               "priority": PRIORITY.get(priority, 3), "tags": tags or []}
    if click:
        payload["click"] = click
    headers = {}
    if os.environ.get("NTFY_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['NTFY_TOKEN']}"
    try:
        r = requests.post(server, json=payload, headers=headers, timeout=30)
        print(f"ntfy: {r.status_code} {title}")
        return r.ok
    except requests.RequestException as e:
        print(f"ntfy failed: {e}")
        return False


def repo_url(path: str = "") -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "GU57AV/east-lyme-records")
    return f"https://github.com/{repo}" + (f"/blob/main/{path}" if path else "")
