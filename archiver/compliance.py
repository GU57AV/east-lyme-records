#!/usr/bin/env python3
"""Posting-deadline checks and topic alerts, built from what the archive has already recorded.

Writes reports/compliance.md and reports/topics.md, and (when run on GitHub with
--open-issues) opens one issue per run for newly found deadline flags and one for new
documents mentioning watched topics. Flags are leads for a person to review, not findings.

Deadline rules checked (Connecticut FOI Act, CGS § 1-225):
  * Agendas: available at least 24 hours before the meeting.
  * Minutes: available within seven days after the meeting.

Evidence comes from two times recorded for each document found after the archive started:
  not_on_site_at_utc  the last check of the Town's listing page that did NOT show it
  first_seen_utc      the check that first showed it
The document was posted somewhere between the two. A flag is raised only when the document
was provably absent at a check made after the deadline had passed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawl import ROOT, load_json, meeting_date  # noqa: E402

ET = ZoneInfo("America/New_York")
REPO = None


def utc(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def fmt(t: dt.datetime | None) -> str:
    return t.astimezone(ET).strftime("%b %-d, %Y %-I:%M %p ET") if t else "—"


TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)", re.I)


def meeting_time(text: str) -> tuple[int, int] | None:
    """First clock time in the top of the agenda, e.g. '7:00 P.M.'"""
    head = "\n".join(text.splitlines()[:80])
    m = TIME_RE.search(head)
    if not m:
        return None
    h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
    if m.group(3).lower().startswith("p"):
        h += 12
    return (h, mi) if 0 <= h < 24 and 0 <= mi < 60 else None


def doc_text(side: Path) -> str:
    md = side.with_suffix(".md")
    if not md.exists():
        return ""
    t = md.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```text\n(.*)```", t, re.S)
    return m.group(1) if m else t


def link(side: Path) -> str:
    return side.with_suffix(".md").relative_to(ROOT).as_posix().replace(" ", "%20")


def load_docs() -> list[tuple[Path, dict]]:
    out = []
    for side in sorted((ROOT / "records").rglob("*.json")):
        if "watched" in side.parts:
            continue
        m = load_json(side, None)
        if isinstance(m, dict) and "source_url" in m:
            out.append((side, m))
    return out


def deadline_flags(docs, boards: dict, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    flags, notes = [], []
    minutes_by_meeting = set()
    for side, m in docs:
        if m.get("kind") == "minutes":
            d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
            if d:
                minutes_by_meeting.add((m["board"], bool(m.get("subcommittee")), d))
    for side, m in docs:
        if m.get("seen_in_initial_import"):
            continue
        absent, seen = utc(m.get("not_on_site_at_utc")), utc(m.get("first_seen_utc"))
        d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
        if not d or not seen:
            continue
        title = m.get("link_text") or m.get("filename")
        board = boards.get(m["board"], m["board"]) + (" (subcommittee)" if m.get("subcommittee") else "")
        base = {"board": board, "date": d.isoformat(), "title": title, "link": link(side),
                "source": m["source_url"], "absent": fmt(absent), "seen": fmt(seen), "key": m["source_url"]}
        if m.get("kind") == "agendas":
            amended = bool(re.search(r"amend|revis|cancel|addend", title, re.I))
            hm = meeting_time(doc_text(side))
            if not hm:
                notes.append({**base, "rule": "Agenda: meeting time not found in the text; not checked"})
                continue
            start = dt.datetime(d.year, d.month, d.day, *hm, tzinfo=ET).astimezone(dt.timezone.utc)
            due = start - dt.timedelta(hours=24)
            if absent and absent > due:
                item = {**base, "rule": "Agenda not on the Town site 24 hours before the meeting",
                        "detail": f"Meeting {fmt(start)}; not on the site at {fmt(absent)}, "
                                  f"{(start - absent).total_seconds() / 3600:.1f} h before the meeting."}
                (notes if amended else flags).append(
                    {**item, "rule": item["rule"] + (" (amended/cancellation notice; review)" if amended else "")})
        elif m.get("kind") == "minutes":
            due = dt.datetime(d.year, d.month, d.day, 23, 59, tzinfo=ET).astimezone(dt.timezone.utc) + dt.timedelta(days=7)
            if absent and absent > due:
                flags.append({**base, "rule": "Minutes not on the Town site within 7 days",
                              "detail": f"Due by {fmt(due)}; still not on the site at {fmt(absent)} "
                                        f"({(absent.date() - d).days} days after the meeting)."})
    # Agendas for meetings since the archive started with no minutes after 8 days.
    for side, m in docs:
        if m.get("kind") != "agendas" or m.get("seen_in_initial_import"):
            continue
        title = m.get("link_text") or m.get("filename") or ""
        if re.search(r"cancel", title, re.I):
            continue
        d = meeting_date(m.get("filename", ""), title, default_year=m.get("year"))
        if not d or (now.astimezone(ET).date() - d).days <= 8:
            continue
        if (m["board"], bool(m.get("subcommittee")), d) not in minutes_by_meeting:
            board = boards.get(m["board"], m["board"]) + (" (subcommittee)" if m.get("subcommittee") else "")
            flags.append({"board": board, "date": d.isoformat(), "title": title, "link": link(side),
                          "source": m["source_url"], "absent": "—", "seen": fmt(utc(m.get("first_seen_utc"))),
                          "key": f"missing-minutes:{m['board']}:{m.get('subcommittee')}:{d}",
                          "rule": "No minutes found more than 8 days after the meeting",
                          "detail": "An agenda was posted but no minutes for that date have appeared on the "
                                    "board's pages (the meeting may have been cancelled)."})
    # One flag per meeting and rule.
    seen_keys, uniq = set(), []
    for f in flags:
        k = (f["key"], f["rule"])
        if k not in seen_keys:
            seen_keys.add(k)
            uniq.append(f)
    return uniq, notes


def topic_hits(docs, topics: list[str]) -> dict:
    hits = {t: [] for t in topics}
    pats = {t: re.compile(r"\b" + re.escape(t).replace(r"\ ", r"[\s\-]+") + r"\b", re.I) for t in topics}
    for side, m in docs:
        text = doc_text(side)
        if not text:
            continue
        for t, pat in pats.items():
            mm = pat.search(text)
            if mm:
                a, b = max(0, mm.start() - 90), min(len(text), mm.end() + 90)
                snippet = " ".join(text[a:b].split())
                hits[t].append((side, m, snippet))
    return hits


def write_compliance(flags, notes, now) -> None:
    out = ROOT / "reports" / "compliance.md"
    out.parent.mkdir(exist_ok=True)
    lines = ["# Posting-deadline report", "",
             f"_Updated {fmt(now)}. Unofficial and automatic: each flag is a lead to review, not a finding._", "",
             "**How this works.** For documents first seen after the archive started, the archive records the "
             "last check of the Town's page that did *not* show the document and the check that first did. "
             "A flag is raised only when the document was provably missing at a check made after its deadline. "
             "Documents already online when the archive started are not checked.", "",
             "**Rules** (Connecticut FOI Act, CGS § 1-225): agendas available at least 24 hours before the "
             "meeting; minutes available within seven days after it. A meeting's time is read from its agenda.", "",
             "**Limits.** The archive sees only the board pages it watches; a document posted somewhere else, or "
             "a meeting that was cancelled, can produce a flag. Times are only as precise as the checks.", ""]
    if not flags:
        lines += ["No deadline flags so far.", ""]
    else:
        lines += [f"## Flags ({len(flags)})", "", "| Meeting date | Board | Document | Issue | Evidence |",
                  "|---|---|---|---|---|"]
        for f in sorted(flags, key=lambda x: x["date"], reverse=True):
            lines.append(f"| {f['date']} | {f['board']} | [{f['title']}](../{f['link']}) ([Town]({f['source']})) "
                         f"| {f['rule']} | {f['detail']} |")
        lines.append("")
    if notes:
        lines += [f"## For review ({len(notes)})", "",
                  "Amended agendas and cancellations posted late, and agendas whose meeting time couldn't be read.",
                  "", "| Meeting date | Board | Document | Note |", "|---|---|---|---|"]
        for n in sorted(notes, key=lambda x: x["date"], reverse=True):
            lines.append(f"| {n['date']} | {n['board']} | [{n['title']}](../{n['link']}) | {n['rule']} |")
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_topics(hits, boards, now) -> None:
    out = ROOT / "reports" / "topics.md"
    out.parent.mkdir(exist_ok=True)
    lines = ["# Topic index", "", f"_Updated {fmt(now)}. Every archived document that mentions each watched "
             "topic, newest meeting first. Edit `topics` in config.json to change the list._", ""]
    for t, items in hits.items():
        lines += [f"## {t} ({len(items)})", ""]
        def k(x):
            d = meeting_date(x[1].get("filename", ""), x[1].get("link_text", ""), default_year=x[1].get("year"))
            return d.isoformat() if d else ""
        for side, m, snip in sorted(items, key=k, reverse=True)[:300]:
            d = k((side, m, snip)) or "undated"
            lines.append(f"- {d} — {boards.get(m['board'], m['board'])}: [{m.get('link_text') or m.get('filename')}]"
                         f"(../{link(side)}) — “…{snip}…”")
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def gh(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def open_issue(title: str, body: str, label: str, color: str) -> None:
    gh("label", "create", label, "--color", color, "--force")
    r = gh("issue", "create", "--title", title, "--body", body[:60000], "--label", label)
    print(("opened issue: " + r.stdout.strip()) if r.returncode == 0 else ("issue failed: " + r.stderr.strip()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open-issues", action="store_true")
    args = ap.parse_args()
    cfg = load_json(ROOT / "config.json", {})
    boards = {b["slug"]: b["name"].replace("East Lyme ", "") for b in cfg.get("boards", [])}
    topics = cfg.get("topics", [])
    now = dt.datetime.now(dt.timezone.utc)
    docs = load_docs()
    state_path = ROOT / "state" / "alerts.json"
    state = load_json(state_path, {"flags": [], "topic_docs": {}})

    flags, notes = deadline_flags(docs, boards, now)
    write_compliance(flags, notes, now)
    hits = topic_hits(docs, topics)
    write_topics(hits, boards, now)

    new_flags = [f for f in flags if f"{f['key']}|{f['rule']}" not in set(state["flags"])]
    new_hits = []
    for t, items in hits.items():
        for side, m, snip in items:
            k = f"{t}|{m['source_url']}|{m.get('sha256')}"
            if k not in state["topic_docs"] and not m.get("seen_in_initial_import"):
                new_hits.append((t, side, m, snip))
            state["topic_docs"].setdefault(k, now.isoformat(timespec="seconds"))

    repo_url = f"https://github.com/{__import__('os').environ.get('GITHUB_REPOSITORY', 'GU57AV/east-lyme-records')}/blob/main/"
    if args.open_issues and new_flags:
        body = ["New posting-deadline flags. These are leads to review, not findings; see "
                f"[the report]({repo_url}reports/compliance.md) for how they're determined.", ""]
        for f in new_flags:
            body.append(f"- **{f['board']}, {f['date']}**: {f['rule']}. [{f['title']}]({repo_url}{f['link']}) — {f['detail']}")
        open_issue(f"Posting deadlines: {len(new_flags)} new flag{'s' if len(new_flags) != 1 else ''}",
                   "\n".join(body), "compliance", "d93f0b")
    if args.open_issues and new_hits:
        body = ["New or changed documents mention watched topics. "
                f"Full list: [topic index]({repo_url}reports/topics.md).", ""]
        for t, side, m, snip in new_hits:
            body.append(f"- **{t}** — {boards.get(m['board'], m['board'])}: "
                        f"[{m.get('link_text') or m.get('filename')}]({repo_url}{link(side)}) — “…{snip}…”")
        names = sorted({t for t, *_ in new_hits})
        open_issue(f"Topic alert: {', '.join(names)[:180]}", "\n".join(body), "topic-alert", "1d76db")

    state["flags"] = sorted(set(state["flags"]) | {f"{f['key']}|{f['rule']}" for f in flags})
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"compliance: {len(flags)} flags ({len(new_flags)} new), {len(notes)} notes; "
          f"topics: {sum(len(v) for v in hits.values())} mentions ({len(new_hits)} new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
