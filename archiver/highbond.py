"""Reader for a Diligent Community (HighBond) meeting portal, such as the East Lyme Public Schools
Board of Education portal at https://eastlymeschools.community.highbond.com.

The portal's public pages load their content from a JSON service:

  /Services/MeetingsService.svc/meetings?from=...&to=...&loadall=true   every meeting
  /Services/MeetingsService.svc/meetings/<id>/meetingDocuments          one meeting's documents

and serve each document at /document/<id> (a Word-format agenda as a PDF with ?printPdf=true).
This module returns the same document list shape crawl.py uses for the Town website, so the
documents are stored, text-copied, checksummed and timestamped the same way.

Load is kept low: one request for the meeting list, then one per meeting, through the shared
Fetcher (same delay and honest user agent as the rest of the archive). Each meeting's document
list is cached in state; recent and upcoming meetings are re-read every run, older ones a few
at a time on full runs, so the whole portal is re-checked over a few weeks.
"""

from __future__ import annotations

import datetime as dt
import re
import time

API = "/Services/MeetingsService.svc/meetings"
RECENT_DAYS = 60          # meetings this recent (or upcoming) are re-read every run
OLD_PER_FULL_RUN = 40     # older meetings re-read per full run, stalest first
MARGIN_SECONDS = 900      # stop reading meeting lists this long before the batch deadline


def ticks_to_utc(ticks) -> str | None:
    """.NET ticks (the portal's LastModified) -> ISO time. The portal does not state a time zone;
    the values match its HTTP Last-Modified header, which is UTC by HTTP convention."""
    try:
        t = dt.datetime(1, 1, 1) + dt.timedelta(microseconds=int(ticks) // 10)
        return t.replace(microsecond=0, tzinfo=dt.timezone.utc).isoformat()
    except Exception:
        return None


def is_subcommittee(name: str) -> bool:
    return bool(re.search(r"committee", name, re.I)) and not re.search(r"committee of the whole", name, re.I)


def doc_entries(base: str, meeting: dict, docs: list[dict]) -> list[dict]:
    """Turn one meeting's document records into archive entries."""
    out = []
    page = f"{base}/Portal/MeetingInformation.aspx?Org=Cal&Id={meeting['Id']}"
    date = meeting.get("MeetingDate") or ""
    name = meeting.get("Name") or meeting.get("CleanName") or f"Meeting {meeting['Id']}"
    for d in docs:
        fmt = (d.get("Format") or "").lower()
        dtype, typ = d.get("DocumentType"), d.get("Type")
        if typ == 1 and dtype == 1:
            kind, label = "agendas", "Agenda"
        elif typ == 1 and dtype == 4:
            kind, label = "other", "Agenda Packet"
        elif typ == 2:
            # A PDF minutes record carries the id of its accessible HTML copy in "Html"; the PDF is
            # the signed version, so the HTML copy is not archived separately.
            kind, label = "minutes", "Signed Minutes" if fmt == "pdf" else "Minutes"
        else:
            kind, label = "other", f"Document type {dtype}"
        if fmt == "docx":
            url, ext = f"{base}/document/{d['Id']}/?printPdf=true", ".pdf"
        elif fmt == "html":
            url, ext = f"{base}/document/{d['Id']}", ".html"
        else:
            url, ext = f"{base}/document/{d['Id']}", f".{fmt or 'pdf'}"
        title = f"{name} - {label}"
        safe = re.sub(r"[^A-Za-z0-9]+", "-", f"{name}-{label}").strip("-")
        out.append({
            "url": url,
            "link_text": title,
            "listing_page": page,
            "kind": kind,
            "year": date[:4] or "unknown",
            "subcommittee": is_subcommittee(meeting.get("MeetingTypeName", "") + " " + name),
            "filename": f"{safe}{ext}",
            "extra": {
                "source": "highbond",
                "meeting_id": meeting["Id"],
                "meeting_date": date,
                "meeting_type": meeting.get("MeetingTypeName"),
                "portal_document_id": d.get("Id"),
                "portal_last_modified_utc": ticks_to_utc(d.get("LastModified")),
            },
        })
    return out


def crawl(f, board: dict, state: dict, full: bool, quick: bool, checks: dict | None,
          deadline: float, log) -> tuple[list[dict], bool, int]:
    """Return (documents, complete, meetings_never_read)."""
    base = board["highbond"].rstrip("/")
    cache = state.setdefault("highbond", {}).setdefault(board["slug"], {})
    meetings_cache = cache.setdefault("meetings", {})
    r = f.get(f"{base}{API}?from=2000-01-01&to=9999-12-31&loadall=true",
              headers={"Accept": "application/json"})
    r.raise_for_status()
    meetings = [m for m in r.json() if m.get("Published")]
    today = dt.date.today()
    soon = (today + dt.timedelta(days=30)).isoformat()
    recent = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
    unread, current, old = [], [], []
    for m in meetings:
        if m.get("MeetingDate", "") > soon:
            continue  # scheduled far ahead; nothing posted yet
        c = meetings_cache.get(str(m["Id"]))
        if not c:
            unread.append(m)
        elif m.get("MeetingDate", "") >= recent:
            current.append(m)
        else:
            old.append((c.get("at", ""), m))
    old.sort(key=lambda x: x[0])
    todo = current + unread  # recent meetings first, then the import backlog
    if full and not quick:
        todo += [m for _, m in old[:OLD_PER_FULL_RUN]]
    log(f"[{board['slug']}] portal: {len(meetings)} published meetings, {len(unread)} not yet read, "
        f"reading {len(todo)} this run")
    stopped = False
    for m in todo:
        if time.monotonic() > deadline - MARGIN_SECONDS:
            stopped = True
            break
        try:
            rr = f.get(f"{base}{API}/{m['Id']}/meetingDocuments", headers={"Accept": "application/json"})
            rr.raise_for_status()
            docs = [{k: v for k, v in d.items() if k not in ("Html", "AgendaCover")}
                    | {"Html": d.get("Html") if str(d.get("Html", "")).isdigit() else ""}
                    for d in rr.json().get("Documents", [])]
        except Exception as e:  # noqa: BLE001
            log(f"  portal meeting {m['Id']}: {e}")
            continue
        meetings_cache[str(m["Id"])] = {"at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                                       "meeting": m, "docs": docs}
        if checks is not None:
            checks[f"{base}/Portal/MeetingInformation.aspx?Org=Cal&Id={m['Id']}"] = meetings_cache[str(m["Id"])]["at"]
    found = []
    for c in meetings_cache.values():
        found += doc_entries(base, c["meeting"], c["docs"])
    pending = sum(1 for m in unread if str(m["Id"]) not in meetings_cache)
    log(f"[{board['slug']}] portal: {len(found)} documents listed"
        + (f"; {pending} meetings still to read" if pending else "")
        + (" (stopped for time)" if stopped else ""))
    # Removals are not inferred from the portal (old meetings are re-read only a few at a time).
    return found, False, pending
