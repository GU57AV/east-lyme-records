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
from notify import notify, repo_url  # noqa: E402

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


def mtype(m: dict) -> str:
    """Public hearings get their own notice and minutes, separate from the meeting's."""
    t = f"{m.get('link_text') or ''} {m.get('filename') or ''}"
    return "hearing" if re.search(r"hearing", t, re.I) else "meeting"


def deadline_flags(docs, boards: dict, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    flags, notes = [], []
    minutes_by_meeting = set()
    for side, m in docs:
        if m.get("kind") == "minutes":
            d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
            if d:
                minutes_by_meeting.add((m["board"], bool(m.get("subcommittee")), d, mtype(m)))
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
        if (m["board"], bool(m.get("subcommittee")), d, mtype(m)) not in minutes_by_meeting:
            board = boards.get(m["board"], m["board"]) + (" (subcommittee)" if m.get("subcommittee") else "")
            flags.append({"board": board, "date": d.isoformat(), "title": title, "link": link(side),
                          "source": m["source_url"], "absent": "—", "seen": fmt(utc(m.get("first_seen_utc"))),
                          "key": f"missing-minutes:{m['board']}:{m.get('subcommittee')}:{d}:{mtype(m)}",
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


OCR_DIGITS = str.maketrans({"T": "7", "S": "5", "s": "5", "l": "1", "I": "1", "i": "1", "O": "0", "o": "0", "B": "8"})
SCHED_RE = re.compile(r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
                      r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s*"
                      r"([0-9TSsIlOoB][0-9TSsIlOoB.]{0,2})\s*(?:st|nd|rd|th|'d|'t|'s)?\b", re.I)
MONTH_NO = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun",
                                        "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def schedule_dates(text: str, year: int) -> list[dt.date]:
    """Meeting dates listed in an annual schedule of meetings. Tolerates common OCR slips
    (e.g. 'AprilTth', 'May Sth'), then keeps dates on the schedule's usual weekday."""
    found = set()
    for m in SCHED_RE.finditer(text):
        day = m.group(2).replace(".", "").translate(OCR_DIGITS)
        if not day.isdigit():
            continue
        try:
            found.add(dt.date(year, MONTH_NO[m.group(1)[:3].lower()], int(day)))
        except ValueError:
            pass
    if len(found) >= 4:
        counts = {}
        for d in found:
            counts[d.weekday()] = counts.get(d.weekday(), 0) + 1
        wd, n = max(counts.items(), key=lambda kv: kv[1])
        if n >= 0.6 * len(found):
            found = {d for d in found if d.weekday() == wd}
    return sorted(found)


def upcoming(docs, boards: dict, now: dt.datetime) -> list[dict]:
    """Deadlines in the next week: agendas for scheduled regular meetings (24 hours ahead) and
    minutes for meetings that have an agenda (seven days after)."""
    today = now.astimezone(ET).date()
    agendas, minutes, out = set(), set(), []
    for side, m in docs:
        d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
        if not d:
            continue
        k = (m["board"], bool(m.get("subcommittee")), d, mtype(m))
        if m.get("kind") == "agendas":
            agendas.add(k)
        elif m.get("kind") == "minutes":
            minutes.add(k)
    name = lambda b, sub: boards.get(b, b) + (" (subcommittee)" if sub else "")
    # Minutes for meetings that had an agenda and haven't been posted yet.
    for side, m in docs:
        title = m.get("link_text") or m.get("filename") or ""
        if m.get("kind") != "agendas" or re.search(r"cancel|schedule", title, re.I):
            continue
        d = meeting_date(m.get("filename", ""), title, default_year=m.get("year"))
        if not d:
            continue
        due = d + dt.timedelta(days=7)
        k = (m["board"], bool(m.get("subcommittee")), d, mtype(m))
        if today <= due <= today + dt.timedelta(days=7) and k not in minutes:
            label = "Public hearing minutes" if k[3] == "hearing" else "Minutes"
            out.append({"key": f"minutes:{k[0]}:{k[1]}:{d}:{k[3]}", "kind": label, "board": name(*k[:2]),
                        "meeting": d, "due": due, "due_text": f"by the end of {due.strftime('%a %b %-d')}",
                        "status": "not posted yet"})
    # Agendas for upcoming regular meetings listed in each board's schedule of meetings.
    for side, m in docs:
        title = (m.get("link_text") or "") + " " + (m.get("filename") or "")
        if not re.search(r"schedule", title, re.I) or not re.search(r"meeting", title, re.I):
            continue
        ym = re.search(r"(20\d{2})", title)
        if not ym or int(ym.group(1)) not in (today.year, today.year + 1):
            continue
        text = doc_text(side)
        hm = meeting_time(text)
        for d in schedule_dates(text, int(ym.group(1))):
            if not (today <= d <= today + dt.timedelta(days=7)):
                continue
            k = (m["board"], bool(m.get("subcommittee")), d, "meeting")
            when = (dt.datetime(d.year, d.month, d.day, *hm) - dt.timedelta(hours=24)).strftime("%a %b %-d, %-I:%M %p") if hm else None
            out.append({"key": f"agenda:{k[0]}:{k[1]}:{d}", "kind": "Agenda", "board": name(*k[:2]), "meeting": d,
                        "due": d - dt.timedelta(days=1),
                        "due_text": f"by {when}" if when else "at least 24 hours before the meeting",
                        "status": "posted" if k in agendas else "not posted yet"})
    seen, uniq = set(), []
    for r in sorted(out, key=lambda r: (r["due"], r["board"])):
        if r["key"] not in seen:
            seen.add(r["key"])
            uniq.append(r)
    return uniq


def write_upcoming(items, now) -> None:
    out = ROOT / "reports" / "upcoming.md"
    out.parent.mkdir(exist_ok=True)
    lines = ["# Upcoming posting deadlines", "",
             f"_Updated {fmt(now)}. Unofficial and automatic._", "",
             "Meetings come from the Town calendar (including special meetings, once they are on it) and from each "
             "board's published schedule of meetings. Agendas and special-meeting notices are due at "
             "least 24 hours before the meeting; minutes are due within seven days after a meeting "
             "(Connecticut FOI Act, CGS § 1-225). A special meeting not yet on the calendar can't be predicted, "
             "and a scheduled meeting may be cancelled. Schedules are often scanned, so a date can occasionally be misread or missed.", ""]
    if not items:
        lines.append("Nothing due in the next seven days that the archive knows of.")
    else:
        lines += ["| Due | What | Board | Meeting | Status |", "|---|---|---|---|---|"]
        for r in items:
            lines.append(f"| {r['due_text']} | {r['kind']} | {r['board']} | {r['meeting'].strftime('%a %b %-d, %Y')} "
                         f"| {r['status']} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def covered_boards(cfg: dict) -> set:
    """Boards whose full history the archive has imported; checks only make sense for these."""
    st = load_json(ROOT / "state" / "state.json", {})
    got = set(st.get("boards_imported", []))
    if not got and st.get("initial_import_complete"):
        got = {"board-of-selectmen"}
    return got


def calendar_entries(cfg: dict, by_file: dict):
    """Every current Town calendar meeting entry, matched to a board.

    by_file maps lowercase archived file names to (sidecar, metadata), so an entry that links an
    agenda the archive holds is assigned to that document's board. Shared by the calendar
    cross-check and the scorecard so both count meetings the same way."""
    import towncal
    c = cfg.get("calendar") or {}
    if not c:
        return
    aliases = c.get("aliases", [])
    excl = re.compile(c.get("exclude", r"$^"), re.I)
    cats = set(c.get("categories") or [])
    for e in towncal.all_entries():
        if e.get("removed_utc") or not e.get("begin"):
            continue
        title = e.get("title", "")
        if (cats and e.get("category") not in cats) or excl.search(title):
            continue
        try:
            begin = dt.datetime.strptime(e["begin"], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        except ValueError:
            continue
        try:
            added = dt.datetime.strptime(e["added"], "%Y-%m-%d %H:%M").replace(tzinfo=ET) if e.get("added") else None
        except ValueError:
            added = None
        linkbase = (e.get("link") or "").rsplit("/", 1)[-1].lower()
        linked = by_file.get(linkbase) if linkbase else None
        slug, level = None, "flag"
        for a in aliases:
            if re.search(a[0], title, re.I):
                slug, level = a[1], (a[2] if len(a) > 2 else "flag")
                break
        if linked:
            slug = linked[1]["board"]
        d = begin.date()
        yield {"e": e, "title": title, "begin": begin, "added": added, "d": d, "linkbase": linkbase,
               "linked": linked, "slug": slug, "level": level,
               "cancelled": bool(re.search(r"cancel", title + " " + linkbase, re.I)),
               "special": bool(re.search(r"special|emergency", title, re.I)),
               "retro": bool(added and added.date() > d),
               "hearing": bool(re.search(r"hearing", title, re.I)
                               and not re.search(r"immed|follow|regular meeting|&", title, re.I)),
               "link_only": bool(linkbase) and not linked and linkbase.endswith((".pdf", ".doc", ".docx"))}


def calendar_checks(docs, boards: dict, cfg: dict, now: dt.datetime):
    """Cross-check the Town calendar against posted agendas and minutes.

    Returns (flags, notes, upcoming_items, summary). A calendar entry is matched to a posted
    agenda first by the agenda file it links to, then by board and date. Entries created after
    their own meeting date are ignored (they are corrections or mistakes, not notice)."""
    c = cfg.get("calendar") or {}
    if not c:
        return [], [], [], {}
    covered = covered_boards(cfg)
    since = dt.date.fromisoformat(c.get("flag_since", "2024-01-01"))
    today = now.astimezone(ET).date()
    name = lambda b: boards.get(b, b)
    by_file, agendas, minutes, cal_posted = {}, {}, set(), set()
    for side, m in docs:
        fn = (m.get("filename") or "").lower()
        if fn:
            by_file[fn] = (side, m)
        title = (m.get("link_text") or "") + " " + (m.get("filename") or "")
        d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
        if not d:
            continue
        if m.get("kind") == "agendas" and not re.search(r"schedule", title, re.I):
            agendas.setdefault((m["board"], d), []).append((side, m))
        elif m.get("kind") == "minutes":
            minutes.add((m["board"], d, mtype(m)))
    flags, notes, soon = [], [], []
    summary = {"entries": 0, "matched": 0, "unmatched": {}, "not_covered": {}, "retroactive": 0, "rows": []}
    for ce in calendar_entries(cfg, by_file):
        e, title, begin, added, d = ce["e"], ce["title"], ce["begin"], ce["added"], ce["d"]
        linkbase, linked, cancelled, special = ce["linkbase"], ce["linked"], ce["cancelled"], ce["special"]
        slug, level, retro = ce["slug"], ce["level"], ce["retro"]
        summary["entries"] += 1
        if not slug:
            summary["unmatched"][title] = summary["unmatched"].get(title, 0) + 1
            continue
        if slug not in covered:
            summary["not_covered"][name(slug)] = summary["not_covered"].get(name(slug), 0) + 1
            continue
        posted = linked or (agendas.get((slug, d)) or [None])[0]
        link_only = bool(linkbase) and not posted and linkbase.endswith((".pdf", ".doc", ".docx"))
        if posted or link_only:
            summary["matched"] += 1
            cal_posted.add((slug, d))
        base = {"board": name(slug), "date": d.isoformat(), "title": f"Calendar: {title}",
                "link": e["_file"], "source": e.get("link") or c.get("page", ""), "source_kind": "calendar",
                "absent": "—", "seen": "—"}
        # Public hearings have their own minutes; an entry for a hearing followed by a meeting counts as a meeting.
        mt = "hearing" if re.search(r"hearing", title, re.I) and not re.search(
            r"immed|follow|regular meeting|&", title, re.I) else "meeting"
        has_min = ((slug, d, mt) in minutes if mt == "meeting"
                   else any((slug, d, x) in minutes for x in ("hearing", "meeting")))
        if abs((d - today).days) <= 30:
            summary["rows"].append({"begin": begin, "title": title, "board": name(slug), "cancelled": cancelled,
                                    "agenda": ("posted" if posted else "linked on calendar" if link_only
                                               else "not found"), "agenda_link": (link(posted[0]) if posted else None),
                                    "minutes": has_min, "special": special})
        if cancelled or retro:
            summary["retroactive"] += int(retro and not cancelled)
            continue
        if begin > now:
            if begin - now <= dt.timedelta(days=7):
                due = begin - dt.timedelta(hours=24)
                soon.append({"key": f"agenda:{slug}:False:{d}", "kind": "Special meeting notice" if special else "Agenda",
                             "board": name(slug), "meeting": d, "due": due.date(),
                             "due_text": f"by {due.strftime('%a %b %-d, %-I:%M %p')}",
                             "status": "posted" if posted else ("linked on calendar" if link_only else "not posted yet")})
            continue
        if d < since:
            continue
        lvl = notes if level == "note" else flags
        if not posted and not link_only:
            lvl.append({**base, "key": f"cal-noagenda:{slug}:{d}:{e['occur_id']}",
                        "rule": "Meeting on the Town calendar; no agenda found",
                        "detail": f"The calendar lists “{title}” on {begin.strftime('%b %-d, %Y %-I:%M %p')}"
                                  + (f" (entry created {added.strftime('%b %-d, %Y')})" if added else "")
                                  + ". No agenda or notice for that date was found on the board's pages, and the "
                                    "calendar entry links none."})
        elif link_only:
            notes.append({**base, "key": f"cal-linkonly:{slug}:{d}:{e['occur_id']}",
                          "rule": "Agenda linked from the calendar but not on the board's page"})
        if special and added and begin - added < dt.timedelta(hours=24):
            notes.append({**base, "key": f"cal-late:{slug}:{d}:{e['occur_id']}",
                          "rule": f"Special meeting added to the calendar {(begin - added).total_seconds() / 3600:.0f} "
                                  "hours before it began (the calendar is not the legal notice; check the Clerk's filing)"})
        if (today - d).days > 8 and not has_min:
            lvl.append({**base, "key": f"missing-minutes:{slug}:False:{d}:{mt}",
                        "rule": "No minutes found more than 8 days after the "
                                + ("public hearing" if mt == "hearing" else "meeting"),
                        "detail": f"The Town calendar lists “{title}” on {begin.strftime('%b %-d, %Y')}, and no "
                                  "minutes for that date have appeared on the board's pages "
                                  "(the meeting may not have been held)."})
    # Minutes with no agenda anywhere: the after-the-fact check for meetings never on the calendar.
    for side, m in docs:
        if m.get("kind") != "minutes" or m["board"] not in covered:
            continue
        title = m.get("link_text") or m.get("filename") or ""
        d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
        if not d or d < since or re.search(r"hearing|workshop|site walk", title, re.I):
            continue
        if (m["board"], d) not in agendas and (m["board"], d) not in cal_posted:
            emergency = bool(re.search(r"emergency", title, re.I))
            notes.append({"board": name(m["board"]), "date": d.isoformat(), "title": title, "link": link(side),
                          "source": m["source_url"], "key": f"min-noagenda:{m['source_url']}",
                          "rule": "Minutes posted, but no agenda for that date on the board's page or the calendar"
                                  + (" (an emergency special meeting may be held without 24 hours' notice; its minutes "
                                     "must be posted within 72 hours and state the reason, CGS § 1-225(d))"
                                     if emergency else "")})
    return flags, notes, soon, summary


def write_calendar_report(summary: dict, now: dt.datetime, cfg: dict) -> None:
    out = ROOT / "reports" / "calendar.md"
    out.parent.mkdir(exist_ok=True)
    page = (cfg.get("calendar") or {}).get("page", "")
    L = ["# Town calendar cross-check", "", f"_Updated {fmt(now)}. Unofficial and automatic._", "",
         f"Meetings on the [Town calendar]({page}) in the 30 days before and after today, for boards whose "
         "records this archive has fully imported, with whether an agenda and minutes have been posted. "
         "Snapshots of the calendar, with every change to every entry, are kept in "
         "[calendar/](../calendar/). The calendar is not the legal notice of a meeting, and entries can be "
         "changed at any time, so this is a cross-check, not proof.", ""]
    rows = sorted(summary.get("rows", []), key=lambda r: r["begin"], reverse=True)
    if rows:
        L += ["| When | Meeting | Board | Agenda | Minutes |", "|---|---|---|---|---|"]
        for r in rows:
            past = r["begin"] < now
            ag = r["agenda"]
            ag = f"[{ag}](../{r['agenda_link']})" if r["agenda_link"] else ag
            mi = "cancelled" if r["cancelled"] else ("posted" if r["minutes"] else ("not yet" if past else "—"))
            L.append(f"| {r['begin'].strftime('%a %b %-d, %Y %-I:%M %p')} | {r['title']} | {r['board']} | "
                     f"{'—' if r['cancelled'] else ag} | {mi} |")
        L.append("")
    else:
        L += ["No calendar entries for imported boards in this window.", ""]
    nc = summary.get("not_covered", {})
    if nc:
        L += ["**Not checked yet** (board still being imported): "
              + ", ".join(f"{k} ({v})" for k, v in sorted(nc.items())), ""]
    um = summary.get("unmatched", {})
    if um:
        L += ["**Calendar entries for bodies this archive doesn't follow** (not checked): "
              + ", ".join(f"{k} ({v})" for k, v in sorted(um.items(), key=lambda kv: -kv[1])[:40]), ""]
    if summary.get("retroactive"):
        L += [f"_{summary['retroactive']} calendar entries created after their own meeting date were ignored._", ""]
    out.write_text("\n".join(L) + "\n", encoding="utf-8")


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
            lines.append(f"| {f['date']} | {f['board']} | [{f['title']}](../{f['link']}) ([{'calendar' if f.get('source_kind') == 'calendar' else 'Town'}]({f['source']})) "
                         f"| {f['rule']} | {f['detail']} |")
        lines.append("")
    if notes:
        lines += [f"## For review ({len(notes)})", "",
                  "Amended agendas and cancellations posted late, agendas whose meeting time couldn't be read, and "
                  "calendar cross-checks that need a person to look (see the [calendar report](calendar.md)).",
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
    cflags, cnotes, csoon, csum = calendar_checks(docs, boards, cfg, now)
    # Until the calendar's history has been fully read (a few runs), record its findings quietly so
    # past problems aren't announced as new.
    import towncal
    st = load_json(ROOT / "state" / "state.json", {})
    cur = now.astimezone(ET).strftime("%Y-%m")
    backfilling = (not st.get("calendar_initialized")
                   or st.get("calendar_backfill_next", "0000-00") < towncal.add_months(cur, -1))
    newly_covered = covered_boards(cfg) - set(state.get("calendar_covered", []))
    names_new = {boards.get(b, b) for b in newly_covered}
    if csum and newly_covered and not backfilling:
        state["flags"] = sorted(set(state["flags"]) | {f"{f['key']}|{f['rule']}" for f in cflags
                                                       if f["board"] in names_new})
    state["calendar_covered"] = sorted(covered_boards(cfg))
    if csum and (backfilling or "calendar_seeded" not in state):
        state["flags"] = sorted(set(state["flags"]) | {f"{f['key']}|{f['rule']}" for f in cflags})
        if not backfilling:
            state["calendar_seeded"] = now.isoformat(timespec="seconds")
    seen_k = {(f["key"], f["rule"]) for f in flags}
    flags += [f for f in cflags if (f["key"], f["rule"]) not in seen_k]
    seen_k = {(n["key"], n["rule"]) for n in notes if "key" in n}
    notes += [n for n in cnotes if (n["key"], n["rule"]) not in seen_k]
    write_compliance(flags, notes, now)
    if csum:
        write_calendar_report(csum, now, cfg)
    soon = csoon + upcoming(docs, boards, now)  # calendar first: it has exact times and special meetings
    seen_k, merged = set(), []
    for r in sorted(soon, key=lambda r: (r["due"], r["board"])):
        if r["key"] not in seen_k:
            seen_k.add(r["key"])
            merged.append(r)
    soon = merged
    write_upcoming(soon, now)
    try:
        import scorecard
        scorecard.write(scorecard.build(docs, boards, cfg, now, flags), now, cfg)
    except Exception as e:  # noqa: BLE001  (reports are extras; never block the checks)
        print(f"scorecard failed: {e}")
    try:
        import recusals
        recusals.write(recusals.extract(docs, boards), now)
    except Exception as e:  # noqa: BLE001
        print(f"recusals failed: {e}")
    try:
        import digest
        digest.run(docs, boards, cfg, now, state)
    except Exception as e:  # noqa: BLE001
        print(f"digest failed: {e}")
    import ordinances
    ords = ordinances.run(docs, doc_text, now, repo_url() + "/blob/main/")
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

    blob = repo_url() + "/blob/main/"
    if args.open_issues and new_flags:
        body = ["New posting-deadline flags. These are leads to review, not findings; see "
                f"[the report]({blob}reports/compliance.md) for how they're determined.", ""]
        for f in new_flags:
            body.append(f"- **{f['board']}, {f['date']}**: {f['rule']}. [{f['title']}]({blob}{f['link']}) — {f['detail']}")
        open_issue(f"Posting deadlines: {len(new_flags)} new flag{'s' if len(new_flags) != 1 else ''}",
                   "\n".join(body), "compliance", "d93f0b")
    if args.open_issues and new_hits:
        body = ["New or changed documents mention watched topics. "
                f"Full list: [topic index]({blob}reports/topics.md).", ""]
        for t, side, m, snip in new_hits:
            body.append(f"- **{t}** — {boards.get(m['board'], m['board'])}: "
                        f"[{m.get('link_text') or m.get('filename')}]({blob}{link(side)}) — “…{snip}…”")
        names = sorted({t for t, *_ in new_hits})
        open_issue(f"Topic alert: {', '.join(names)[:180]}", "\n".join(body), "topic-alert", "1d76db")

    if new_flags:
        notify(f"East Lyme: {len(new_flags)} posting-deadline flag{'s' if len(new_flags) != 1 else ''}",
               "\n".join(f"{f['board']}, {f['date']}: {f['rule']}" for f in new_flags[:8])
               + ("\n…" if len(new_flags) > 8 else ""),
               priority="high", tags=["warning"], click=repo_url("reports/compliance.md"))
    if new_hits:
        names = sorted({t for t, *_ in new_hits})
        notify(f"East Lyme topic alert: {', '.join(names)[:120]}",
               "\n".join(f"{t}: {m.get('link_text') or m.get('filename')} ({boards.get(m['board'], m['board'])})"
                         for t, side, m, snip in new_hits[:8]) + ("\n…" if len(new_hits) > 8 else ""),
               priority="default", tags=["mag"], click=repo_url("reports/topics.md"))

    # Heads-up reminders, about a day before each deadline, to a separate optional topic.
    today = now.astimezone(ET).date()
    reminded = set(state.get("reminders", []))
    due_soon = [r for r in soon if r["status"] == "not posted yet" and r["due"] <= today + dt.timedelta(days=1)
                and r["key"] not in reminded]
    for r in due_soon:
        notify(f"Deadline tomorrow: {r['kind'].lower()} for {r['board']}",
               f"{r['kind']} for the {r['meeting'].strftime('%b %-d')} meeting should be posted {r['due_text']}.",
               priority="default", tags=["alarm_clock"], click=repo_url("reports/upcoming.md"),
               topic_env="NTFY_REMINDER_TOPIC")
        reminded.add(r["key"])
    state["reminders"] = sorted(reminded)

    # Ordinance enactments: alert on a new enactment, a notice of adoption appearing, a new flag,
    # and (to the reminder topic) the day before an overrule-petition window closes.
    first_run = "ordinances" not in state
    seen_ord = state.setdefault("ordinances", {})
    for e, r in ords:
        prev = seen_ord.get(e["key"], {})
        n = r["notice"] or r["notice_possible"]
        cur = {"notice": str(n["side"].name) if n else "", "flags": sorted(r["flags"])}
        if not first_run:
            title = e["title"][:80]
            if not prev:
                notify(f"Ordinance enacted: {title}",
                       f"Board of Selectmen vote on {e['date']:%b %-d, %Y}. Watching for the notice of adoption and full "
                       "text on the Town's website (Charter § 3.4.3).", tags=["scroll"], click=repo_url("reports/ordinances.md"))
            if cur["notice"] and cur["notice"] != prev.get("notice"):
                notify(f"Notice of adoption found: {title}",
                       f"Appears posted {n['posted'][1]}. Earliest effective date {r['earliest_effective']:%b %-d, %Y}; "
                       f"overrule petitions due within 10 days of publication (about {r['petition_by']:%b %-d}).",
                       tags=["memo"], click=repo_url("reports/ordinances.md"))
            new = [f for f in cur["flags"] if f not in prev.get("flags", []) and not f.startswith("no ")]
            if new:
                notify(f"Ordinance check: {title}", "\n".join(new), priority="high", tags=["warning"],
                       click=repo_url("reports/ordinances.md"))
        pb = r.get("petition_by")
        rk = f"petition|{e['key']}"
        if pb and today <= pb <= today + dt.timedelta(days=1) and rk not in reminded:
            notify(f"Petition window closing: {e['title'][:70]}",
                   f"Overrule petitions (200 electors) are due about {pb:%b %-d}. Confirm the exact deadline with the Town Clerk.",
                   tags=["alarm_clock"], click=repo_url("reports/ordinances.md"), topic_env="NTFY_REMINDER_TOPIC")
            reminded.add(rk)
        seen_ord[e["key"]] = cur
    state["reminders"] = sorted(reminded)

    state["flags"] = sorted(set(state["flags"]) | {f"{f['key']}|{f['rule']}" for f in flags})
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"compliance: {len(flags)} flags ({len(new_flags)} new), {len(notes)} notes; "
          f"topics: {sum(len(v) for v in hits.values())} mentions ({len(new_hits)} new); ordinances: {len(ords)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
