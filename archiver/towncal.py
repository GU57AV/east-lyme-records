"""The Town calendar, kept as dated snapshots for cross-checking against posted agendas and minutes.

The Town's website runs the WordPress "My Calendar" plugin, which publishes every calendar entry
through a public JSON API (/wp-json/my-calendar/v1/events?from=YYYY-MM-DD&to=YYYY-MM-DD). For
each entry it gives the title, start and end, the time the entry was created ("event_added") and,
usually, a link to the agenda PDF. One request per month is enough.

Snapshots go to calendar/YYYY/YYYY-MM.json (outside records/, since these are not Town documents).
Each entry keeps the time the archive first saw it and a history of changes, so a meeting that is
added late, rescheduled, retitled "CANCELLED" or deleted leaves a record. Each month file carries a
SHA-256 of its entries and is listed in the archive's blockchain-timestamped manifests.

The calendar is not the legal notice of a meeting (that is the notice or agenda filed with the
Town Clerk and posted under CGS § 1-225), and entries can be edited at any time. It is used to
anticipate meetings and to cross-check, never as proof on its own.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CAL = ROOT / "calendar"
ET = ZoneInfo("America/New_York")
TRACK = ("title", "begin", "end", "link", "location")


def add_months(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def month_range(ym: str) -> tuple[str, str]:
    first = dt.date.fromisoformat(ym + "-01")
    last = dt.date.fromisoformat(add_months(ym, 1) + "-01") - dt.timedelta(days=1)
    return first.isoformat(), last.isoformat()


def normalize(data) -> dict:
    """API response (a dict of date -> list of occurrences) to {occur_id: entry}."""
    out = {}
    days = data.values() if isinstance(data, dict) else []
    for day in days:
        for e in day or []:
            if not isinstance(e, dict):
                continue
            oid = str(e.get("occur_id") or e.get("uid") or "")
            if not oid:
                continue
            out[oid] = {
                "occur_id": oid,
                "event_id": str(e.get("event_id") or ""),
                "title": html.unescape(str(e.get("event_title") or "")).strip(),
                "begin": str(e.get("occur_begin") or "")[:16],
                "end": str(e.get("occur_end") or "")[:16],
                "added": str(e.get("event_added") or "")[:16],
                "link": str(e.get("event_link") or "").strip(),
                "location": html.unescape(str(e.get("event_label") or "")).strip(),
                "category": html.unescape(str(e.get("category_name") or "")).strip(),
            }
    return out


def entries_hash(events: dict) -> str:
    return hashlib.sha256(json.dumps(events, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_month(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def all_entries() -> list[dict]:
    """Every entry in every snapshot, current and removed."""
    out = []
    for p in sorted(CAL.rglob("*.json")):
        m = load_month(p)
        if m:
            for e in m.get("events", {}).values():
                out.append({**e, "_file": p.relative_to(ROOT).as_posix()})
    return out


def merge(ym: str, fresh: dict, now: str, url: str, quiet: bool) -> list[tuple[str, str]]:
    """Fold a fresh fetch into the month's snapshot. Returns (kind, line) changes unless quiet."""
    path = CAL / ym[:4] / f"{ym}.json"
    old = load_month(path) or {"month": ym, "events": {}}
    ev = old.get("events", {})
    before = json.dumps(ev, sort_keys=True)
    changes: list[tuple[str, str]] = []
    when = lambda e: dt.datetime.strptime(e["begin"], "%Y-%m-%d %H:%M").strftime("%a %b %-d, %Y %-I:%M %p") \
        if e.get("begin") else "?"
    for oid, e in fresh.items():
        prev = ev.get(oid)
        if not prev:
            e["first_seen_utc"] = now
            if quiet:
                e["seen_in_backfill"] = True
            ev[oid] = e
            if not quiet:
                changes.append(("new", f"Added: {e['title']} — {when(e)}"))
            continue
        diffs = {k: [prev.get(k), e[k]] for k in TRACK if prev.get(k) != e[k]}
        if prev.get("removed_utc"):
            prev.pop("removed_utc")
            prev.setdefault("history", []).append({"at": now, "restored": True})
            if not quiet:
                changes.append(("restored", f"Back on the calendar: {e['title']} — {when(e)}"))
        if diffs:
            prev.setdefault("history", []).append({"at": now, "changes": diffs})
            for k in TRACK:
                prev[k] = e[k]
            prev["added"] = e["added"]
            if not quiet:
                desc = "; ".join(f"{k} was “{a}”" for k, (a, b) in diffs.items() if k != "link")
                changes.append(("changed", f"Changed: {e['title']} — {when(e)}" + (f" ({desc})" if desc else
                                                                                    " (agenda link changed)")))
    if fresh or not ev:  # an empty answer for a month that had entries is treated as a glitch
        for oid, prev in ev.items():
            if oid not in fresh and not prev.get("removed_utc"):
                prev["removed_utc"] = now
                if not quiet:
                    changes.append(("removed", f"Removed from the calendar: {prev['title']} — {when(prev)}"))
    if json.dumps(ev, sort_keys=True) != before or not path.exists():
        ev = dict(sorted(ev.items(), key=lambda kv: (kv[1].get("begin", ""), kv[0])))
        doc = {"month": ym, "source_url": url, "sha256": entries_hash(ev),
               "note": "Unofficial snapshot of the Town of East Lyme calendar. Times are local (America/New_York).",
               "events": ev}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return changes


def write_changes(today: str, rep: dict) -> None:
    if not any(rep[k] for k in ("new", "changed", "removed", "restored", "errors")):
        return
    out = ROOT / "changes" / f"{today}.md"
    out.parent.mkdir(exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%H:%M UTC")
    lines = [f"# Changes found {today}", ""] if not out.exists() else []
    lines += [f"### Town calendar — check at {stamp}", ""]
    for key, title in (("new", "New calendar entries"), ("changed", "Calendar entries changed"),
                       ("removed", "Calendar entries removed"), ("restored", "Calendar entries restored"),
                       ("errors", "Calendar errors")):
        if rep[key]:
            lines += [f"## {title} ({len(rep[key])})", ""] + [f"- {x}" for x in rep[key]] + [""]
    with out.open("a" if out.exists() else "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def sync(f, cfg: dict, state: dict, deadline: float, quick: bool = False, log=print) -> dict:
    """Fetch recent and upcoming months every run, and older months a batch at a time until the
    configured start is reached. The first ever sync records everything quietly."""
    rep = {"new": [], "changed": [], "removed": [], "restored": [], "errors": []}
    c = cfg.get("calendar") or {}
    if not c.get("api"):
        return rep
    cur = dt.datetime.now(ET).strftime("%Y-%m")
    live = [add_months(cur, i) for i in ((0, 1) if quick else (-1, 0, 1, 2))]
    first_sync = not state.get("calendar_initialized")
    backfill = []
    if not quick:
        nxt = state.get("calendar_backfill_next", c.get("start", "2020-01"))
        while nxt < add_months(cur, -1) and len(backfill) < int(c.get("backfill_months_per_run", 24)):
            backfill.append(nxt)
            nxt = add_months(nxt, 1)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for ym in backfill + live:
        if time.monotonic() > deadline:
            break
        a, b = month_range(ym)
        url = f"{c['api']}?from={a}&to={b}"
        try:
            r = f.get(url)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001
            rep["errors"].append(f"{ym}: {e}")
            if ym in backfill:
                break
            continue
        quiet = first_sync or ym in backfill
        for kind, line in merge(ym, normalize(data), now, url, quiet):
            rep[kind].append(line)
        if ym in backfill:
            state["calendar_backfill_next"] = add_months(ym, 1)
    if not rep["errors"] or len(rep["errors"]) < len(live):
        state["calendar_initialized"] = True
    log(f"calendar: {len(backfill)} older month(s), {len(live)} current; {len(rep['new'])} new, "
        f"{len(rep['changed'])} changed, {len(rep['removed'])} removed, {len(rep['errors'])} errors")
    return rep
