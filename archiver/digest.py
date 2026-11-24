"""Weekly digest: one page per week (Monday to Sunday, Eastern time) in reports/digest/.

Each page lists the week's meetings from the Town calendar with whether an agenda and minutes
have been posted, the documents newly posted on the Town website that week, documents the Town
changed or removed, the archive's alerts and calendar changes, and next week's meetings. The
current and previous weeks are rebuilt on every run; older pages are left as they were. When a
week ends, its digest is announced in the public RSS feed feeds/digest.xml.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from compliance import ET, calendar_entries, covered_boards, fmt, link, meeting_date

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "digest"
UP = "../../"  # from reports/digest/ to the repository root


def week_id(monday: dt.date) -> str:
    y, w, _ = monday.isocalendar()
    return f"{y}-W{w:02d}"


def span(monday: dt.date) -> str:
    sun = monday + dt.timedelta(days=6)
    if monday.month == sun.month:
        return f"{monday:%b %-d}–{sun:%-d, %Y}"
    return f"{monday:%b %-d}–{sun:%b %-d, %Y}"


def changes_in(first: dt.date, last: dt.date) -> dict:
    """Changed and removed documents from the daily change logs, skipping initial imports."""
    out = {"changed": [], "removed": []}
    d = first
    while d <= last:
        p = ROOT / "changes" / f"{d.isoformat()}.md"
        if p.exists():
            for block in p.read_text(encoding="utf-8").split("\n### ")[1:]:
                if "Initial import" in block.split("\n", 1)[0]:
                    continue
                for sec in block.split("\n## ")[1:]:
                    head, _, body = sec.partition("\n")
                    key = ("changed" if head.startswith("Documents whose content changed") else
                           "removed" if head.startswith("Documents no longer linked") else None)
                    if key:
                        out[key] += [ln[2:] for ln in body.splitlines() if ln.startswith("- ")]
        d += dt.timedelta(days=1)
    return out


def feed_items(start: dt.datetime, end: dt.datetime) -> list[dict]:
    try:
        items = json.loads((ROOT / "state" / "feed_items.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    keep = []
    for it in items:
        try:
            at = dt.datetime.fromisoformat(it.get("at", ""))
        except ValueError:
            continue
        if start <= at < end:
            keep.append(it)
    return keep


def as_link(text: str) -> str:
    """'Title — https://…' (the change-log format) as a markdown link."""
    title, sep, url = text.rpartition(" — ")
    return f"[{title}]({url})" if sep and url.startswith("http") else text


def build_week(docs, boards: dict, cfg: dict, monday: dt.date, now: dt.datetime) -> tuple[str, str]:
    sunday = monday + dt.timedelta(days=6)
    start = dt.datetime(monday.year, monday.month, monday.day, tzinfo=ET).astimezone(dt.timezone.utc)
    end = start + dt.timedelta(days=7)
    today = now.astimezone(ET).date()
    covered = covered_boards(cfg)
    name = lambda b: boards.get(b, b).replace("East Lyme ", "")
    by_file, agendas, minutes = {}, {}, {}
    for side, m in docs:
        fn = (m.get("filename") or "").lower()
        if fn:
            by_file[fn] = (side, m)
        d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
        if d and m.get("kind") == "agendas":
            agendas.setdefault((m["board"], d), []).append(side)
        elif d and m.get("kind") == "minutes":
            minutes.setdefault((m["board"], d), []).append(side)

    def meetings(first: dt.date, last: dt.date) -> list[str]:
        rows = []
        for ce in sorted(calendar_entries(cfg, by_file), key=lambda c: c["begin"]):
            if ce["retro"] or not (first <= ce["d"] <= last):
                continue
            slug, d = ce["slug"], ce["d"]
            ours = slug in covered
            if ce["cancelled"]:
                ag, mi = "cancelled", "—"
            else:
                side = ce["linked"][0] if ce["linked"] else ((agendas.get((slug, d)) or [None])[0] if ours else None)
                if side:
                    ag = f"[posted]({UP}{link(side)})"
                elif ce["link_only"] or (ce["e"].get("link") and not ours):
                    ag = f"[on calendar]({ce['e']['link']})"
                else:
                    ag = "not found" if ours else "—"
                if d >= today:
                    mi = "—"
                elif ours:
                    ms = minutes.get((slug, d))
                    mi = f"[posted]({UP}{link(ms[0])})" if ms else "not yet"
                else:
                    mi = "not followed"
            rows.append(f"| {ce['begin']:%a %b %-d, %-I:%M %p} | {ce['title']} | {name(slug) if slug else '—'} "
                        f"| {ag} | {mi} |")
        return rows

    held = meetings(monday, sunday)
    nxt = meetings(sunday + dt.timedelta(days=1), sunday + dt.timedelta(days=7))
    new = {}
    for side, m in docs:
        if str(m.get("seen_in_initial_import")) == "True" or not m.get("first_seen_utc"):
            continue
        try:
            seen = dt.datetime.fromisoformat(m["first_seen_utc"])
        except ValueError:
            continue
        if start <= seen < end:
            new.setdefault(name(m["board"]), []).append(
                (seen, f"[{m.get('link_text') or m.get('filename')}]({UP}{link(side).rsplit('.', 1)[0]}.md) — "
                       f"{fmt(seen)} ([Town original]({m['source_url']}))"))
    ch = changes_in(monday, sunday)
    items = feed_items(start, end)
    alerts = [i for i in items if i.get("feed") == "alerts"]
    cal = [i for i in items if i.get("feed") == "calendar"]
    n_new = sum(len(v) for v in new.values())
    glance = (f"{len(held)} meeting{'s' * (len(held) != 1)} on the calendar · {n_new} new document"
              f"{'s' * (n_new != 1)} · {len(ch['changed']) + len(ch['removed'])} changed or removed · "
              f"{len(alerts)} alert{'s' * (len(alerts) != 1)}")
    done = end <= now
    L = [f"# Week of {span(monday)}", "",
         f"**At a glance:** {glance}", "",
         ("_Final for the week._" if done else f"_Week in progress; updated {fmt(now)}._")
         + " Unofficial and automatic; the Town's website is the official source.", ""]
    hdr = ["| When | Calendar entry | Board | Agenda | Minutes |", "|---|---|---|---|---|"]
    L += ["## Meetings this week", ""] + ((hdr + held) if held else ["None on the Town calendar."]) + [""]
    L += ["## New on the Town website", ""]
    if new:
        for b in sorted(new):
            L += [f"**{b}**", ""] + [f"- {t}" for _, t in sorted(new[b])] + [""]
    else:
        L += ["No new documents found on the pages this archive follows.", ""]
    if ch["changed"] or ch["removed"]:
        L += ["## Changed or removed by the Town", ""]
        L += [f"- Changed: {as_link(x)}" for x in ch["changed"]] + [f"- No longer linked: {as_link(x)}"
                                                                    for x in ch["removed"]] + [""]
    if alerts:
        L += ["## Alerts", ""] + [f"- **{a['title']}.** {a.get('message', '').splitlines()[0] if a.get('message') else ''}"
                                  for a in alerts] + [""]
    if cal:
        L += ["## Calendar changes", ""] + [f"- {c.get('message') or c['title']}" for c in cal] + [""]
    L += ["## Coming up next week", ""] + ((hdr + nxt) if nxt else ["Nothing on the Town calendar yet."]) + [""]
    L += ["---", "", "Agenda and minutes status is checked only for boards whose records this archive has "
          "fully imported (others show “—” or “not followed”). See the [deadline report](../compliance.md), "
          "[upcoming deadlines](../upcoming.md) and [scorecard](../scorecard.md).", ""]
    return "\n".join(L), glance


def write_index() -> None:
    rows = []
    for p in sorted(OUT.glob("20*-W*.md"), reverse=True):
        lines = p.read_text(encoding="utf-8").splitlines()
        title = lines[0].lstrip("# ") if lines else p.stem
        glance = next((ln.replace("**At a glance:** ", "") for ln in lines if ln.startswith("**At a glance:**")), "")
        rows.append(f"| [{title}]({p.name}) | {glance} |")
    (OUT / "README.md").write_text("\n".join(
        ["# Weekly digests", "",
         "What happened each week (Monday to Sunday) in East Lyme's boards and commissions, as seen by this "
         "archive: meetings on the Town calendar, documents newly posted, documents changed or removed, and "
         "alerts. Subscribe to new digests with the RSS feed "
         "[feeds/digest.xml](https://raw.githubusercontent.com/GU57AV/east-lyme-records/main/feeds/digest.xml).", "",
         "| Week | At a glance |", "|---|---|"] + rows) + "\n", encoding="utf-8")


def run(docs, boards: dict, cfg: dict, now: dt.datetime, state: dict) -> None:
    from notify import record, repo_url
    OUT.mkdir(parents=True, exist_ok=True)
    today = now.astimezone(ET).date()
    this_monday = today - dt.timedelta(days=today.weekday())
    for monday in (this_monday - dt.timedelta(days=7), this_monday):
        text, glance = build_week(docs, boards, cfg, monday, now)
        (OUT / f"{week_id(monday)}.md").write_text(text, encoding="utf-8")
    write_index()
    last = this_monday - dt.timedelta(days=7)
    if state.get("digest_announced") != week_id(last) and (OUT / f"{week_id(last)}.md").exists():
        _, glance = build_week(docs, boards, cfg, last, now)
        record(f"Weekly digest: {span(last)}", glance, repo_url(f"reports/digest/{week_id(last)}.md"), feed="digest")
        state["digest_announced"] = week_id(last)
