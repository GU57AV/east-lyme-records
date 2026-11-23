"""Public RSS feeds, rebuilt on every run and committed to feeds/.

  feeds/documents.xml  documents newly posted on the Town website (found after archiving began)
  feeds/alerts.xml     everything the archive alerts on: deadline flags, topic hits, ordinance
                       notices, documents changed or removed, new Code editions
  feeds/reminders.xml  heads-up reminders a day before a posting deadline
  feeds/calendar.xml   Town calendar changes: meetings added, rescheduled, cancelled or removed

Subscribe in any feed reader with the "raw" address, e.g.
https://raw.githubusercontent.com/GU57AV/east-lyme-records/main/feeds/documents.xml
"""
from __future__ import annotations

import datetime as dt
import json
import os
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "feeds"
REPO = os.environ.get("GITHUB_REPOSITORY", "GU57AV/east-lyme-records")
BLOB = f"https://github.com/{REPO}/blob/main/"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/feeds/"

FEEDS = {
    "documents": ("East Lyme records: new documents",
                  "Agendas, minutes, notices and other documents newly posted on the Town of East Lyme website, "
                  "as found by an unofficial resident-run archive."),
    "alerts": ("East Lyme records: alerts",
               "Possible missed posting deadlines, watched topics, ordinance notices and changed or removed "
               "documents. Automatic leads to review, not findings."),
    "reminders": ("East Lyme records: deadline reminders",
                  "Heads-up about a day before an agenda or minutes posting deadline that hasn't been met yet."),
    "calendar": ("East Lyme records: Town calendar changes",
                 "Meetings added to, changed on, or removed from the Town calendar."),
}


def rfc822(iso: str | None) -> str:
    try:
        return format_datetime(dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc))
    except (TypeError, ValueError):
        return format_datetime(dt.datetime.now(dt.timezone.utc))


def item(title: str, link: str | None, desc: str, guid: str, when: str | None) -> str:
    return ("    <item>\n"
            f"      <title>{escape(title)}</title>\n"
            + (f"      <link>{escape(link)}</link>\n" if link else "")
            + f"      <description>{escape(desc)}</description>\n"
            f"      <guid isPermaLink=\"false\">{escape(guid)}</guid>\n"
            f"      <pubDate>{rfc822(when)}</pubDate>\n"
            "    </item>\n")


def write(name: str, items: list[str]) -> None:
    title, desc = FEEDS[name]
    body = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<rss version=\"2.0\" xmlns:atom=\"http://www.w3.org/2005/Atom\">\n  <channel>\n"
            f"    <title>{escape(title)}</title>\n"
            f"    <link>https://github.com/{REPO}</link>\n"
            f"    <description>{escape(desc)} Unofficial; the Town's website is the official source.</description>\n"
            f"    <atom:link href=\"{RAW}{name}.xml\" rel=\"self\" type=\"application/rss+xml\"/>\n"
            "    <language>en-us</language>\n"
            "    <ttl>180</ttl>\n"
            + "".join(items) + "  </channel>\n</rss>\n")
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{name}.xml"
    # Rewrite only when items change, so the feed files don't churn on every run.
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old.split("<item>", 1)[-1:] != body.split("<item>", 1)[-1:] or not old:
        path.write_text(body, encoding="utf-8")


def documents_feed(limit: int = 60) -> list[str]:
    cfg = json.loads((ROOT / "config.json").read_text())
    names = {b["slug"]: b["name"].replace("East Lyme ", "") for b in cfg.get("boards", [])}
    docs = []
    for side in (ROOT / "records").rglob("*.json"):
        if "watched" in side.parts:
            continue
        try:
            m = json.loads(side.read_text())
        except ValueError:
            continue
        if not isinstance(m, dict) or "source_url" not in m or str(m.get("seen_in_initial_import")) == "True":
            continue
        docs.append((m.get("first_seen_utc") or "", side, m))
    docs.sort(key=lambda x: x[0], reverse=True)
    out = []
    for when, side, m in docs[:limit]:
        board = names.get(m.get("board"), m.get("board", ""))
        title = f"{board}: {m.get('link_text') or m.get('filename')}"
        text = BLOB + side.with_suffix(".md").relative_to(ROOT).as_posix().replace(" ", "%20")
        desc = (f"{board}, {m.get('kind', 'document')}. First seen on the Town website {when[:16].replace('T', ' ')} UTC. "
                f"Town's original: {m['source_url']}"
                + (f" Saved copy: {m['original_copy']}" if m.get("original_copy") else "")
                + (f" SHA-256: {m['sha256']}" if m.get("sha256") else ""))
        out.append(item(title, text, desc, m.get("sha256") or m["source_url"], when))
    return out


def recorded(feed: str) -> list[str]:
    try:
        items = json.loads((ROOT / "state" / "feed_items.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        items = []
    return [item(it["title"], it.get("link"), it.get("message") or it["title"], it["id"], it.get("at"))
            for it in reversed(items) if it.get("feed") == feed]


def main() -> int:
    write("documents", documents_feed())
    for name in ("alerts", "reminders", "calendar"):
        write(name, recorded(name))
    print("feeds: " + ", ".join(f"{p.name}" for p in sorted(OUT.glob("*.xml"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
