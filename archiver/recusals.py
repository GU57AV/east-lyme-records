"""Recusal tracker: every recorded instance, in the minutes, of a member stepping aside from a matter.

Writes reports/recusals.md and reports/recusals.json. It looks for a named member who:
  * recused (e.g. "Mr. Peck recused himself from this item");
  * left the room during a vote (e.g. "Motion Passed 5-0-1 (Mr. Seery left the room)");
  * abstained, but only when the minutes give a conflict-type reason (abstentions because a member
    missed the meeting whose minutes are being approved are routine and left out).

For each, it records the meeting date, board, the member's name as written, the matter (the nearest
application or motion before it), a short excerpt, and a link to the minutes. Names are as the OCR
read them, so a name may be misspelled. A recusal is a member following the Ethics Code (Town Code
§ 35.18) and state law (e.g. CGS § 8-11 for zoning), not a finding of wrongdoing.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from compliance import fmt, link, meeting_date

ROOT = Path(__file__).resolve().parent.parent
TITLE = r"(?:Mr|Ms|Mrs|Miss|Dr|Chairman|Chairwoman|Chair|Vice[- ]Chair(?:man)?|Commissioner|Selectman|Selectwoman|Member|Alternate)"
NAME = (rf"(?:{TITLE}\.?\s+[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?"   # Mr. Peck, Commissioner Jett-Harris
        r"|[A-Z]\.\s?[A-Z][a-z][\w'’-]+"                         # R. Gordon
        r"|[A-Z][a-z]+\s+[A-Z][a-z][\w'’-]+)")                    # Rich Gordon
EVENTS = [
    ("recused", re.compile(r"\b(?:recused|recuses|recusing|will recuse|recusal)\b", re.I)),
    ("left the room", re.compile(r"\bleft the (?:room|table|dais)\b", re.I)),
    ("abstained", re.compile(r"\babstain(?:ed|s|ing)?\b", re.I)),
]
CONFLICT_REASON = re.compile(r"conflict|interest|relat(?:ed|ive|ionship)|employ|client|neighbor|abutt|own(?:s|er)|"
                             r"business|lives in|resides|family|spouse|husband|wife|son|daughter|brother|sister", re.I)
ROUTINE = re.compile(r"absen(?:t|ce)|not (?:present|in attendance)|did not attend|wasn'?t (?:present|there)|minutes", re.I)
ITEM = re.compile(r"(?:\bApplication (?:of|by|for)\b[^.;]{5,160}|\bAppl(?:ication)?\.?\s*#\s*[\w-]+[^.;]{0,120}|"
                  r"\bPetition (?:of|by)\b[^.;]{5,140}|\bmoved to (?:approve|adopt|accept|authorize|deny|table)[^.;]{5,160})", re.I)
NOT_NAMES = {"Motion", "Commission", "Board", "Town", "East", "Lyme", "Public", "Hearing", "Regular", "Special",
             "Meeting", "Minutes", "Application", "Zoning", "Planning", "The", "This", "Members", "Item", "Old", "New",
             "Business", "Passed", "Carried", "Seconded", "Approval", "Section", "State", "Statutes"}


def sentence_around(t: str, start: int, end: int) -> tuple[str, int]:
    """The sentence containing [start, end), without breaking on 'Mr.'-style abbreviations or initials."""
    masked = re.sub(rf"\b({TITLE}|[A-Z])\.", lambda m: m.group(0)[:-1] + "\x00", t)
    s = max(masked.rfind(". ", 0, start), masked.rfind("? ", 0, start), masked.rfind("; ", 0, start),
            masked.rfind(") ", 0, start) if masked.rfind("(", 0, start) < masked.rfind(")", 0, start) else -1)
    s = s + 2 if s >= 0 else max(0, start - 250)
    e = masked.find(". ", end)
    e = e + 1 if e >= 0 else min(len(t), end + 250)
    s, e = max(s, start - 300), min(e, end + 300)
    return t[s:e].strip(), s


def names_in(text: str) -> list[str]:
    out = []
    for m in re.finditer(NAME, text):
        n = m.group(0).strip()
        words = re.sub(rf"^{TITLE}\.?\s+", "", n).split()
        if not words or any(w.strip(".") in NOT_NAMES for w in words):
            continue
        if n not in out:
            out.append(n)
    return out


def surname(n: str) -> str:
    return re.sub(r"[^\w'’-]", "", n.split()[-1]).title()


VERB = r"(?i:recused|recuses|will recuse|is recusing|left the (?:room|table|dais)|abstained|abstains|abstaining)"
ADJ = re.compile(rf"(?P<who>{NAME}(?:\s*(?:,|and|&)\s*{NAME})*)\s*,?\s*(?i:has |have |had |then |also |both )?(?P<verb>{VERB})")
REASON = re.compile(r"(?i:\b(?:due to|because|as (?:he|she|they)|since|citing|given that|for reasons? of)\b[^.)]{0,160})")


def extract(docs, boards: dict) -> list[dict]:
    found, seen = [], set()
    for side, m in docs:
        if m.get("kind") != "minutes":
            continue
        d = meeting_date(m.get("filename", ""), m.get("link_text", ""), default_year=m.get("year"))
        if not d:
            continue
        try:
            raw = side.with_suffix(".md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = re.search(r"```text\n(.*)```", raw, re.S)
        t = " ".join((body.group(1) if body else raw).split())
        for ev in ADJ.finditer(t):
            verb = ev.group("verb").lower()
            kind = "recused" if verb.startswith("recus") or verb.startswith("will recuse") or verb.startswith("is recus") \
                else "left the room" if verb.startswith("left") else "abstained"
            who = names_in(ev.group("who"))
            if not who:
                continue
            tail = t[ev.end(): ev.end() + 220]
            rm = REASON.match(tail.lstrip(" ,")) or REASON.search(re.split(r"[.)]", tail, 1)[0])
            reason = rm.group(0).strip() if rm else ""
            if kind == "abstained":
                # Only abstentions with a stated conflict-type reason; absence-from-prior-meeting is routine.
                if not reason or ROUTINE.search(reason) or not CONFLICT_REASON.search(reason):
                    continue
            if kind == "left the room" and not re.search(r"motion|vote|\d\s*-\s*\d\s*-\s*\d|conflict|recus",
                                                          t[max(0, ev.start() - 250): ev.end() + 80], re.I):
                continue
            sent, _ = sentence_around(t, ev.start(), ev.end())
            items = list(ITEM.finditer(t[max(0, ev.start() - 1500): ev.start()]))
            item = items[-1].group(0).strip() if items else ""
            key = (m["board"], d, tuple(sorted(surname(w) for w in who)), kind, item[:40].lower())
            if key in seen:
                continue
            seen.add(key)
            found.append({"date": d.isoformat(), "board": m["board"], "board_name": boards.get(m["board"], m["board"]),
                          "members": who, "type": kind, "reason": reason[:160], "item": item[:200],
                          "excerpt": sent[:400], "minutes": link(side), "source_url": m["source_url"]})
    found.sort(key=lambda r: (r["date"], r["board"]), reverse=True)
    return found


def write(rows: list[dict], now: dt.datetime) -> None:
    out = ROOT / "reports"
    (out / "recusals.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    by_board, by_member = {}, {}
    for r in rows:
        b = r["board_name"].replace("East Lyme ", "")
        by_board[b] = by_board.get(b, 0) + 1
        for w in r["members"]:
            k = (b, surname(w))
            by_member[k] = by_member.get(k, 0) + 1
    L = ["# Recusals", "", f"_Updated {fmt(now)}. Unofficial and automatic._", "",
         "Each time the minutes record a named member stepping aside from a matter: recusing, leaving the room "
         "during a vote, or abstaining for a stated conflict-type reason. Recusal is what East Lyme's Ethics Code "
         "(Town Code § 35.18) and state law (for example CGS § 8-11 for zoning boards) call for when a member has "
         "an interest in a matter, so these entries show the rules being followed, not wrongdoing.", "",
         "**Limits.** Names are as written in the minutes and read by OCR, so spellings vary and some may be "
         "misread. Minutes don't always record recusals, and a member who quietly doesn't vote won't appear. The "
         "matter shown is the nearest application or motion before the recusal in the minutes, which is usually, "
         "but not always, the one it applies to. Abstentions because a member missed an earlier meeting are left "
         "out. The full data is in [recusals.json](recusals.json).", ""]
    if not rows:
        L += ["No recusals found yet.", ""]
    else:
        L += ["## By board", "", "| Board | Recusals |", "|---|---|"]
        L += [f"| {b} | {n} |" for b, n in sorted(by_board.items(), key=lambda kv: -kv[1])] + [""]
        L += ["## All recorded recusals (newest first)", "",
              "| Date | Board | Member(s) | How | Reason given | Matter | Minutes |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            item = (r["item"] or "—").replace("|", "/")
            L.append(f"| {r['date']} | {r['board_name'].replace('East Lyme ', '')} | {', '.join(r['members'])} | "
                     f"{r['type']} | {(r.get('reason') or '—').replace('|', '/')[:90]} | {item[:120]} | "
                     f"[minutes](../{r['minutes']}) |")
        L.append("")
    (out / "recusals.md").write_text("\n".join(L) + "\n", encoding="utf-8")
