"""Ordinance enactment check (Charter §§ 3.4.2 and 3.4.3).

Reads the OCR/text copies of Board of Selectmen minutes to find votes enacting an
ordinance, then looks through everything archived for:

  * the hearing notice with the proposed ordinance, which § 3.4.2 requires on the
    Town's website at least ten days before the hearing;
  * the notice of adoption with the full text, which § 3.4.3 requires on the Town's
    website, and from which the ten-day waiting period before the ordinance can take
    effect (and the ten days for an overrule petition) is counted.

The archive can only show what was on the pages it saves. "Not found" means not
found in the archive, not proof that nothing was ever posted anywhere. Posting
times come from the archive's own checks when the document appeared after
archiving began, and otherwise from the server's file date and WordPress upload
folder, which are evidence of when the file was uploaded but not proof.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from crawl import ROOT, load_json

ET_CHARTER = dt.date(2023, 12, 7)  # current Charter (website posting rules) effective
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DIG = str.maketrans({"T": "7", "S": "5", "s": "5", "l": "1", "L": "1", "I": "1", "i": "1",
                     "O": "0", "o": "0", "B": "8", "A": "0", "Z": "2", "z": "2", "g": "9"})
D = r"[0-9TSsIlLiOoBAZzg]"
DATE_RE = re.compile(rf"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+({D}{{1,2}})(?:st|nd|rd|th)?\s*[,.]?\s*({D}{{4}})")
QUOTE = "\"“”"
STOP = {"ordinance", "ordinances", "establishing", "establishment", "the", "and", "for", "of",
        "to", "in", "on", "an", "a", "town", "east", "lyme", "entitled", "titled", "amendment",
        "revisions", "with", "use", "certain", "new"}


def parse_dates(s: str) -> list[dt.date]:
    out = []
    for m in DATE_RE.finditer(s):
        try:
            out.append(dt.date(int(m.group(3).translate(DIG)), MONTHS.index(m.group(1)[:3].lower()) + 1,
                               int(m.group(2).translate(DIG))))
        except ValueError:
            pass
    return out


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", s.lower()) if w not in STOP}


def title_score(title: str, text_words: set[str]) -> float:
    w = words(title)
    return len(w & text_words) / len(w) if w else 0.0


def clean(s: str) -> str:
    return " ".join(s.split())


def enactments(docs, doc_text) -> list[dict]:
    """Passed motions to enact/adopt an ordinance, from Board of Selectmen minutes."""
    out = []
    for side, m in docs:
        if m.get("board") != "board-of-selectmen" or m.get("kind") != "minutes":
            continue
        if re.search(r"notice|hearing", f"{m.get('link_text')} {m.get('filename')}", re.I):
            continue
        try:
            mdate = dt.date.fromisoformat(side.stem[:10])
        except ValueError:
            continue
        t = clean(doc_text(side))
        for mv in re.finditer(r"MOVED|MOVE the", t, re.I):
            seg = t[mv.start(): mv.start() + 1500]
            end = re.search(r"Seconded|SECOND(?:ED)?\b", seg[20:], re.I)
            motion = seg[: end.start() + 20] if end else seg[:900]
            if not re.search(r"\b(?:to|and)\s+(?:enact|adopt)(?:\s+and\s+approve)?\s+(?:the\s+)?(?:proposed\s+)?"
                             r"(?:amendments?|revisions?|ordinances?|following)\b", motion, re.I):
                continue
            if re.search(r"notice is hereby given|consider the adoption|request\w*\s+(?:the\s+)?board|"
                         r"\b(table|postpone|schedule|set|hold)\w*\b.{0,40}\bhearing", motion[:300], re.I):
                continue
            after = seg[len(motion): len(motion) + 400]
            if re.search(r"\b(fail|defeat)", after, re.I):
                outcome = "failed"
            elif re.search(r"\b(pass|carri|unanim|approved)\w*|\b\d\s*-\s*\d\b", after, re.I):
                outcome = "passed"
            else:
                outcome = "unclear"
            if outcome == "failed":
                continue
            core = re.split(r"\b(?:as\s+)?presented\b|\bSeconded\b", motion, flags=re.I)[0]
            if re.search(r"\brepeal", core, re.I):  # keep only what's enacted, not what's repealed
                last = list(re.finditer(r"\b(?:enact|adopt)\w*", core, re.I))
                core = core[last[-1].start():] if last else core
            titles = [clean(x) for x in re.findall(rf"[{QUOTE}]\s*([^{QUOTE}]{{6,180}}?)\s*[{QUOTE}]", core)]
            if not titles:
                mt = (re.search(r"(?:entitled|titled|entiled|entitted)\W+(.{6,180}?)(?:,{1,2}|\.)?\s*$", core, re.I)
                      or re.search(r"(?:enact|adopt)\s+the\s+(.{6,180}?)[,\s]*$", core, re.I))
                if mt:
                    titles = [clean(mt.group(1).strip(" '.,:"))]
            titles = [x.strip(" '.,:") for x in titles]
            if not titles:
                titles = ["(title not readable in the minutes)"]
            hearings = []
            hm = re.search(r"public hearings?\b(.{0,160})", motion, re.I)
            if hm:
                hearings = [d for d in parse_dates(hm.group(1)) if d <= mdate]
            for title in titles:
                key = f"{mdate}|{re.sub(r'[^a-z]', '', title.lower())[:60]}"
                if any(e["key"] == key for e in out):
                    continue
                out.append({"key": key, "date": mdate, "title": title, "outcome": outcome,
                            "hearings": hearings, "minutes": side, "motion": motion[:600],
                            "stated_effective": [d for d in parse_dates(motion + after) if d > mdate]})
    return sorted(out, key=lambda e: e["date"])


def posted(m: dict) -> tuple[dt.date | None, str]:
    """Best available evidence of when a file went up, and how we know."""
    seen = m.get("first_seen_utc")
    if seen and str(m.get("seen_in_initial_import")) != "True":
        absent = m.get("not_on_site_at_utc")
        d = dt.datetime.fromisoformat(seen).date()
        if absent:
            return d, f"appeared between {absent[:16].replace('T', ' ')} and {seen[:16].replace('T', ' ')} UTC (archive checks)"
        return d, f"first seen {seen[:16].replace('T', ' ')} UTC (archive check)"
    lm = m.get("http_last_modified")
    if lm:
        try:
            d = dt.datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S GMT").date()
            up = f" (upload folder {m['upload_folder']})" if m.get("upload_folder") else ""
            return d, f"server file date {d:%b %-d, %Y}{up}"
        except ValueError:
            pass
    up = m.get("upload_folder")
    if up and re.match(r"\d{4}-\d{2}$", up):
        return dt.date(int(up[:4]), int(up[5:]), 1), f"upload folder {up} (month only)"
    return None, "no posting date available"


def candidates(docs, doc_text) -> list[dict]:
    out = []
    watched = []
    for side in sorted((ROOT / "records" / "watched").rglob("*.json")):
        m = load_json(side, None)
        if isinstance(m, dict) and m.get("source_url") and side.with_suffix(".md").exists() and "linked" in side.parts:
            watched.append((side, m))
    for side, m in list(docs) + watched:
        t = doc_text(side)
        if not t.strip():
            continue
        name = f"{m.get('link_text') or ''} {m.get('filename') or ''}"
        third = "watched" in side.parts or "eltownhall.com" not in (m.get("source_url") or "")
        routine = bool(re.search(r"minutes|agenda", name, re.I)) and not re.search(r"notice|ordinance", name, re.I)
        top = t[:1500]
        try:
            ddate = dt.date.fromisoformat(side.stem[:10])
        except ValueError:
            ddate = None
        out.append({"side": side, "m": m, "words": words(t), "name": name, "third": third, "routine": routine,
                    "ddate": ddate,
                    "notice": not routine and not re.search(r"hearing", name, re.I) and bool(
                        re.search(r"notice\W+of\W+(adoption|enactment|passage)|adoption\W+of\W+ordinance", name, re.I)
                        or re.search(r"notice\W+of\W+(adoption|enactment|passage)|return\W+of\W+posting", top, re.I)),
                    "hearing": bool(re.search(r"hearing\W+notice|notice\W+of\W+(a\W+)?public\W+hearing", name + " " + top, re.I)),
                    "body": len(re.findall(r"(?:^|\n)\s*(?:Section|Sec\.|§)\s*\d", t)) >= 2
                            or bool(re.search(r"be it (?:hereby )?ordained|is hereby (?:enacted|amended|adopted)", t, re.I)),
                    "posted": posted(m)})
    return out


def check(e: dict, cands: list[dict], used_notices: dict) -> dict:
    mdate = e["date"]
    res = {"notice": None, "notice_possible": None, "full_text": None, "hearing_notice": None,
           "third_party": [], "earliest_effective": None, "flags": []}
    after = [c for c in cands if c["side"] != e["minutes"] and c["posted"][0] and c["posted"][0] >= mdate]
    scored = sorted(((title_score(e["title"], c["words"]), c) for c in after), key=lambda x: (-x[0], x[1]["posted"][0]))
    for s, c in scored:
        if s < 0.6:
            break
        if c["third"]:
            res["third_party"].append(c)
            continue
        if c["notice"] and not res["notice"]:
            res["notice"] = c
        if c["body"] and not res["full_text"] and not c["routine"] and s >= 0.7 \
                and not (c["hearing"] and not c["notice"]) and (c["posted"][0] - mdate).days <= 60:
            res["full_text"] = c
    if not res["notice"]:
        # OCR of newspaper clippings is often too garbled to read the title: fall back to an
        # unmatched notice uploaded within 60 days, for a person to review.
        for c in sorted(after, key=lambda c: c["posted"][0]):
            if c["notice"] and not c["third"] and used_notices.get(str(c["side"]), mdate) == mdate \
                    and (c["posted"][0] - mdate).days <= 60:
                res["notice_possible"] = c
                break
    n = res["notice"] or res["notice_possible"]
    if n:
        used_notices[str(n["side"])] = mdate
        if n["body"] and not res["full_text"]:
            res["full_text"] = n
        res["earliest_effective"] = n["posted"][0] + dt.timedelta(days=10)
        res["petition_by"] = res["earliest_effective"]
        if e["stated_effective"] and min(e["stated_effective"]) < res["earliest_effective"]:
            res["flags"].append(f"stated effective date {min(e['stated_effective']):%b %-d, %Y} is less than "
                                f"10 days after the notice appears to have been posted")
    if e["hearings"]:
        first = min(e["hearings"])
        pre = [c for c in cands if not c["third"] and c["posted"][0] and c["posted"][0] <= first
               and (first - c["posted"][0]).days <= 60 and c["side"] != e["minutes"] and not c["routine"]
               and ((c["hearing"] and c["ddate"] in e["hearings"])
                    or (title_score(e["title"], c["words"]) >= 0.6 and (c["hearing"] or c["body"])))]
        named = [c for c in pre if c["hearing"] and c["ddate"] in e["hearings"]]
        if named or pre:
            c = min(named or pre, key=lambda c: c["posted"][0])
            res["hearing_notice"] = c
            lead = (first - c["posted"][0]).days
            if lead < 10:
                how = ("by the server's file date, which can also reflect a later replacement of the file"
                       if "server" in c["posted"][1] else "by the archive's own checks")
                res["flags"].append(f"the hearing notice found appears to have been posted {lead} days before the "
                                    f"{first:%b %-d, %Y} hearing, {how} (§ 3.4.2 requires at least 10)")
    if mdate >= ET_CHARTER:
        if not n:
            res["flags"].append("no notice of adoption found on the Town's website in the archive")
        if not res["full_text"]:
            res["flags"].append("no full text of the enacted ordinance, posted after adoption, found on the Town's website in the archive")
        if e["hearings"] and not res["hearing_notice"]:
            res["flags"].append("no hearing notice or proposed ordinance text found posted before the hearing")
    return res


def write_report(items, now: dt.datetime, repo: str) -> Path:
    def ln(c):
        rel = c["side"].with_suffix(".md").relative_to(ROOT).as_posix().replace(" ", "%20")
        return f"[{c['m'].get('link_text') or c['m'].get('filename')}]({repo}{rel})"

    L = ["# Ordinance enactments: notice and publication check", "",
         f"_Updated {now:%Y-%m-%d %H:%M} UTC._", "",
         "Every Board of Selectmen vote enacting an ordinance that the archive can read in the minutes, "
         "checked against the Charter:", "",
         "- **§ 3.4.2:** the proposed ordinance and the hearing's time and place must be posted on the Town's "
         "website at least 10 days before the public hearing.",
         "- **§ 3.4.3:** after enactment, notice of adoption *along with the full text* must be published on the "
         "Town's website and filed with the Town Clerk. The ordinance can't take effect sooner than 10 days after "
         "that notice, and electors have those 10 days to file an overrule petition (200 signatures).", "",
         "**How to read this.** These are leads to review, not findings. The text comes from OCR, which can misread "
         "titles and dates. *Not found* means not found among the pages this archive saves, which may not include "
         "every place the Town posts notices. Filing with the Town Clerk and newspaper publication can't be checked "
         "here. Posting dates are the archive's own observations for documents that appeared after archiving began; "
         "for older files they're the server's file date, which shows when the file was uploaded but isn't proof. "
         "The website requirements took effect with the current Charter on December 7, 2023, so only "
         "enactments since then are checked.", ""]
    for e, r in reversed(items):
        L += [f"## {e['date']:%B %-d, %Y}: {e['title']}", ""]
        L.append(f"- **Vote:** {e['outcome']} — [minutes]({repo}{e['minutes'].with_suffix('.md').relative_to(ROOT).as_posix().replace(' ', '%20')})")
        if e["hearings"]:
            L.append("- **Hearing(s):** " + ", ".join(f"{d:%b %-d, %Y}" for d in e["hearings"]))
        hn = r["hearing_notice"]
        L.append(f"- **Hearing notice / proposed text (§ 3.4.2):** " + (
            f"{ln(hn)} — {hn['posted'][1]}" if hn else "not found in the archive"))
        n = r["notice"] or r["notice_possible"]
        L.append(f"- **Notice of adoption (§ 3.4.3):** " + (
            f"{ln(n)} — {n['posted'][1]}" + (" _(title not legible in OCR; matched by timing, please verify)_" if r["notice_possible"] else "")
            if n else "not found on the Town's website in the archive"))
        ft = r["full_text"]
        L.append(f"- **Full text posted after adoption:** " + (f"{ln(ft)} — {ft['posted'][1]}" if ft else "not found in the archive"))
        if r["third_party"]:
            L.append("- **On a third-party site (not the Town's website):** " + "; ".join(
                f"{ln(c)} — {c['posted'][1]}" for c in r["third_party"][:3]))
        if r["earliest_effective"]:
            L.append(f"- **Earliest lawful effective date** (10 days after the notice above): {r['earliest_effective']:%b %-d, %Y}")
            L.append(f"- **Overrule petition window** (§ 3.4.3, 200 electors, filed with the Town Clerk): "
                     f"within 10 days after publication, i.e. about {r['petition_by']:%b %-d, %Y}; confirm the exact date with the Clerk")
        if e["stated_effective"]:
            L.append(f"- **Effective date stated in the motion:** {min(e['stated_effective']):%b %-d, %Y}")
        if e["outcome"] == "unclear":
            r["flags"].insert(0, "the vote result couldn't be read in the minutes; confirm the ordinance was enacted")
        if r["flags"]:
            L += ["", "**To review:**"] + [f"- {f}" for f in r["flags"]]
        L.append("")
    out = ROOT / "reports" / "ordinances.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def run(docs, doc_text, now: dt.datetime, repo: str) -> list[tuple[dict, dict]]:
    cands = candidates(docs, doc_text)
    used: dict = {}
    items = [(e, check(e, cands, used)) for e in enactments(docs, doc_text) if e["date"] >= ET_CHARTER]
    write_report(items, now, repo)
    return items
