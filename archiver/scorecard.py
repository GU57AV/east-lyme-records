"""Transparency scorecard: how reliably and how promptly each board posts agendas and minutes.

Writes reports/scorecard.md. For each board whose history the archive has fully imported, it
counts meeting days since January 1, 2024 (and in the last 12 months) and reports:

  * agenda found: an agenda or notice for that day on the board's pages, or linked from the
    Town calendar;
  * agenda 24 hours ahead: the earliest version was online at least 24 hours before the meeting;
  * minutes found: minutes for that day, once more than eight days have passed;
  * minutes within 7 days, and the median days from meeting to minutes.

A "meeting day" is a board and a date that appears on the Town calendar or in an agenda or
minutes file. Several meetings of one board on one date (say, a hearing followed by a regular
meeting) count as one day. Cancelled meetings are left out.

Posting times: for a file that appeared after the archive began watching, the archive's own
checks bracket when it went up. For older files, the server's file date is used; that is when
the file was uploaded, and a file replaced later (an amended agenda saved over the original, say)
shows the later date. When the upload folder (wp-content/uploads/YYYY/MM, set at first upload) is an
earlier month than the file date, the folder month is used instead, or the timing is left unknown.
"""
from __future__ import annotations

import datetime as dt
import re
import statistics
from pathlib import Path

from compliance import (ET, calendar_entries, covered_boards, doc_text, fmt, link, meeting_date,
                        meeting_time, utc)

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"town-meetings"}  # town meetings are called by warning under different rules
SINCE = dt.date(2024, 1, 1)


def server_time(m: dict) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(m.get("http_last_modified") or "", "%a, %d %b %Y %H:%M:%S GMT").replace(
            tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def judge(m: dict, due: dt.datetime) -> tuple[str, dt.datetime | None]:
    """'on time', 'late' or 'unknown' against a deadline, plus the best posting time we have."""
    if str(m.get("seen_in_initial_import")) != "True" and m.get("first_seen_utc"):
        seen, absent = utc(m.get("first_seen_utc")), utc(m.get("not_on_site_at_utc"))
        if seen and seen <= due:
            return "on time", seen
        if absent and absent > due:
            return "late", seen
        return "unknown", seen
    t = server_time(m)
    if not t:
        return "unknown", None
    # WordPress files an upload under the month it was first uploaded (wp-content/uploads/YYYY/MM). If the
    # file date is in a later month, the file was replaced after first posting, so the folder month is the
    # better evidence: judge by it when it settles the question, otherwise call it unknown.
    up = m.get("upload_folder") or ""
    if re.fullmatch(r"\d{4}-\d{2}", up) and up < t.strftime("%Y-%m"):
        first = dt.datetime(int(up[:4]), int(up[5:]), 1, tzinfo=ET)
        nxt = dt.datetime(first.year + first.month // 12, first.month % 12 + 1, 1, tzinfo=ET)
        if nxt.astimezone(dt.timezone.utc) <= due:
            return "on time", first.astimezone(dt.timezone.utc)
        if first.astimezone(dt.timezone.utc) > due:
            return "late", first.astimezone(dt.timezone.utc)
        return "unknown", None
    return ("on time" if t <= due else "late"), t


def build(docs, boards: dict, cfg: dict, now: dt.datetime, flags: list[dict]) -> dict:
    today = now.astimezone(ET).date()
    covered = covered_boards(cfg) - SKIP
    by_file, days = {}, {}
    day = lambda k: days.setdefault(k, {"cal": [], "agendas": [], "minutes": []})
    for side, m in docs:
        fn = (m.get("filename") or "").lower()
        if fn:
            by_file[fn] = (side, m)
        if m["board"] not in covered or m.get("kind") not in ("agendas", "minutes"):
            continue
        title = f"{m.get('link_text') or ''} {m.get('filename') or ''}"
        # Only agendas, notices and cancellations mark a meeting; reports and packets filed with them don't.
        if m.get("kind") == "agendas" and (re.search(r"schedule", title, re.I) or not re.search(
                r"agenda|notice|cancel", title, re.I) or re.search(r"report|presentation|packet|slides", title, re.I)):
            continue
        d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
        if d and SINCE <= d < today:
            day((m["board"], d))[m["kind"]].append((side, m))
    for ce in calendar_entries(cfg, by_file):
        if ce["slug"] in covered and not ce["retro"] and SINCE <= ce["d"] < today:
            day((ce["slug"], ce["d"])).setdefault("cal", []).append(ce)

    rows = {}
    for (slug, d), x in sorted(days.items()):
        cal_live = [c for c in x["cal"] if not c["cancelled"]]
        ags = [(s, m) for s, m in x["agendas"] if not re.search(r"cancel", (m.get("link_text") or "") + " "
                                                                    + (m.get("filename") or ""), re.I)]
        cancel_docs = len(ags) < len(x["agendas"])
        if not x["minutes"] and ((x["cal"] and not cal_live) or (cancel_docs and not cal_live)):
            continue  # cancelled: the calendar marks it so, or a cancellation notice was posted, and no minutes
        if not cal_live and not ags and not x["minutes"]:
            continue
        # Meeting start: the calendar's time for the first non-hearing entry, else the agenda's own text.
        begin = min((c["begin"] for c in cal_live if not c["hearing"]), default=None) \
            or min((c["begin"] for c in cal_live), default=None)
        if not begin:
            for s, m in ags:
                hm = meeting_time(doc_text(s))
                if hm:
                    begin = dt.datetime(d.year, d.month, d.day, *hm, tzinfo=ET)
                    break
        rec = {"date": d, "begin": begin, "agenda": bool(ags) or any(c["link_only"] for c in cal_live),
               "agenda_time": None, "agenda_doc": ags[0] if ags else None,
               "minutes_due": (today - d).days > 8, "minutes": bool(x["minutes"]),
               "minutes_time": None, "minutes_days": None, "minutes_doc": x["minutes"][0] if x["minutes"] else None,
               "title": (cal_live[0]["title"] if cal_live else None)}
        if ags and begin:
            verdicts = [judge(m, begin.astimezone(dt.timezone.utc) - dt.timedelta(hours=24)) for _, m in ags]
            v = [a for a, _ in verdicts]
            rec["agenda_time"] = "on time" if "on time" in v else ("late" if v and all(a == "late" for a in v)
                                                                    else "unknown")
        if x["minutes"]:
            due = dt.datetime(d.year, d.month, d.day, 23, 59, tzinfo=ET).astimezone(dt.timezone.utc) + dt.timedelta(days=7)
            verdicts = [judge(m, due) for _, m in x["minutes"]]
            v = [a for a, _ in verdicts]
            rec["minutes_time"] = "on time" if "on time" in v else ("late" if all(a == "late" for a in v)
                                                                     else "unknown")
            times = [(t, str(m.get("seen_in_initial_import")) != "True") for (_, t), (_, m) in zip(verdicts, x["minutes"]) if t]
            if times:
                t, observed = min(times)
                rec["minutes_days"] = max(0, (t.astimezone(ET).date() - d).days)
                rec["minutes_observed"] = observed
        rows.setdefault(slug, []).append(rec)

    open_flags = {}
    for f in flags:
        open_flags[f["board"]] = open_flags.get(f["board"], 0) + 1
    return {"rows": rows, "today": today, "open_flags": open_flags, "boards": boards}


def stats(recs: list[dict]) -> dict:
    s = {"meetings": len(recs), "agenda": sum(r["agenda"] for r in recs)}
    timed = [r["agenda_time"] for r in recs if r["agenda_time"] in ("on time", "late")]
    s["agenda_on"], s["agenda_timed"] = timed.count("on time"), len(timed)
    due = [r for r in recs if r["minutes_due"]]
    s["minutes_due"], s["minutes"] = len(due), sum(r["minutes"] for r in due)
    mt = [r["minutes_time"] for r in due if r["minutes_time"] in ("on time", "late")]
    s["minutes_on"], s["minutes_timed"] = mt.count("on time"), len(mt)
    days = [r["minutes_days"] for r in due if r["minutes_days"] is not None]
    s["median_days"] = statistics.median(days) if days else None
    return s


def pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}% ({n}/{d})" if d else "—"


def table(data: dict, since: dt.date) -> list[str]:
    L = ["| Board | Meeting days | Agenda found | Agenda 24 h ahead | Minutes found | Minutes within 7 days "
         "| Median days to minutes | Open flags |", "|---|---|---|---|---|---|---|---|"]
    out = []
    for slug, recs in data["rows"].items():
        r = [x for x in recs if x["date"] >= since]
        if not r:
            continue
        s, name = stats(r), data["boards"].get(slug, slug)
        out.append((name, s))
    for name, s in sorted(out, key=lambda t: t[0]):
        md = "—" if s["median_days"] is None else f"{s['median_days']:g}"
        L.append(f"| {name} | {s['meetings']} | {pct(s['agenda'], s['meetings'])} | "
                 f"{pct(s['agenda_on'], s['agenda_timed'])} | {pct(s['minutes'], s['minutes_due'])} | "
                 f"{pct(s['minutes_on'], s['minutes_timed'])} | {md} | {data['open_flags'].get(name, 0)} |")
    return L


def write(data: dict, now: dt.datetime, cfg: dict) -> Path:
    today = data["today"]
    year_ago = today - dt.timedelta(days=365)
    L = ["# Transparency scorecard", "", f"_Updated {fmt(now)}. Unofficial and automatic._", "",
         "How reliably and how promptly each board posts agendas and minutes, for boards whose records this "
         "archive has fully imported. Connecticut's Freedom of Information Act (CGS § 1-225) requires agendas "
         "at least 24 hours before a meeting and minutes within seven days after it.", "",
         "## Last 12 months", "", f"Meetings from {year_ago:%b %-d, %Y} through yesterday.", ""]
    L += table(data, year_ago) + ["", "## Since January 1, 2024", ""] + table(data, SINCE) + [""]
    L += ["## How to read this", "",
          "- **Meeting days** are dates when the Town calendar, an agenda or minutes show the board meeting. A "
          "hearing and a meeting on the same date count once, and cancelled meetings are left out.",
          "- **Agenda found** counts an agenda or notice on the board's pages, or one linked from the Town calendar.",
          "- **Agenda 24 h ahead** and **minutes within 7 days** count only meetings where the posting time could "
          "be judged. For documents that appeared after this archive started watching, the archive's own checks "
          "show when they went up. For older files the server's file date is used: that is when the file was "
          "uploaded, and a file replaced later (for example draft minutes replaced by the approved version) shows the "
          "later date. When the Town website's upload folder shows the file first went up in an earlier month, "
          "that month is used instead, or the timing is left out if it can't settle the question. Even so, "
          "older figures can make a board look slower than it was.",
          "- **Draft minutes may not show.** If draft minutes were posted on time and later deleted when the "
          "approved version went up under a new file name, only the later file can be seen here (the archive can't "
          "see files removed before it started watching). \"Current minutes file uploaded after N days\" means "
          "the file online now; the Wayback Machine may show whether an earlier draft existed.",
          "- **Minutes found** counts only meetings more than eight days ago. A meeting that was announced but "
          "not held can show as missing minutes.",
          "- **Open flags** are this run's [deadline flags](compliance.md) for that board.",
          "- Town meetings are not scored: they are called by a published warning under different rules.",
          "- Boards still being imported will appear once their history is complete.", ""]
    # Details: the specific meetings behind the misses, last 12 months.
    L += ["## Details (last 12 months)", ""]
    for slug in sorted(data["rows"], key=lambda s: data["boards"].get(s, s)):
        miss = []
        for r in data["rows"][slug]:
            if r["date"] < year_ago:
                continue
            what = []
            if not r["agenda"]:
                what.append("no agenda found")
            elif r["agenda_time"] == "late":
                what.append("agenda not online 24 h ahead")
            if r["minutes_due"] and not r["minutes"]:
                what.append("no minutes found")
            elif r["minutes_time"] == "late":
                n = r["minutes_days"]
                what.append("minutes late" if n is None else (f"minutes appeared after {n} days"
                            if r.get("minutes_observed") else f"current minutes file uploaded after {n} days"))
            if what:
                doc = r["agenda_doc"] or r["minutes_doc"]
                ref = f" ([document](../{link(doc[0])}))" if doc else ""
                miss.append(f"- {r['date']:%a %b %-d, %Y}{(' — ' + r['title']) if r['title'] else ''}: "
                            f"{'; '.join(what)}{ref}")
        if miss:
            L += [f"<details><summary>{data['boards'].get(slug, slug)} ({len(miss)})</summary>", ""] + miss + \
                 ["", "</details>", ""]
    out = ROOT / "reports" / "scorecard.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out
