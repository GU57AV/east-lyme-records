"""Build one-click downloads of the whole archive for people who don't use GitHub.

Writes to dist/:
  east-lyme-records-index.csv     one row per document; opens in Excel, Numbers or Google Sheets
  east-lyme-records-text.zip      every text copy as a .txt file, in board/year/kind folders,
                                  plus the Charter and Code, the reports, and a READ-ME.txt
  east-lyme-records.sqlite        the same, as one database with full-text search
                                  (open with the free "DB Browser for SQLite")

The workflow uploads them to the "download" release, so the links never change.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
FIELDS = ["meeting_date", "board", "committee", "kind", "title", "source_url", "original_copy",
          "text_copy", "sha256", "first_seen_utc", "server_file_date", "upload_folder", "text_method"]


def text_of(md: Path) -> str:
    t = md.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"```text\n(.*)```", t, re.S)
    return (m.group(1) if m else t).strip() + "\n"


def server_date(s: str | None) -> str:
    try:
        return dt.datetime.strptime(s or "", "%a, %d %b %Y %H:%M:%S GMT").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def repo() -> str:
    import os
    return os.environ.get("GITHUB_REPOSITORY", "GU57AV/east-lyme-records")


def rows():
    cfg = json.loads((ROOT / "config.json").read_text())
    names = {b["slug"]: b["name"] for b in cfg.get("boards", [])}
    for side in sorted((ROOT / "records").rglob("*.json")):
        if "watched" in side.parts and "linked" not in side.parts:
            continue
        try:
            m = json.loads(side.read_text())
        except ValueError:
            continue
        md = side.with_suffix(".md")
        if not isinstance(m, dict) or "source_url" not in m or not md.exists():
            continue
        rel = side.relative_to(ROOT / "records")
        pre = side.stem[:10] if re.match(r"\d{4}-\d{2}-\d{2}", side.stem) else ""
        # "2015-12-00" = month known, day not; "2015-00-00" = year only
        date = pre[:4] if pre[5:7] == "00" else pre[:7] if pre[8:10] == "00" else pre
        yield {
            "meeting_date": date,
            "board": names.get(m.get("board"), "Watched sources" if "watched" in side.parts else m.get("board", "")),
            "committee": "subcommittee" if "subcommittee" in rel.parts else "",
            "kind": m.get("kind", "linked file" if "watched" in side.parts else ""),
            "title": m.get("link_text") or m.get("filename") or side.stem,
            "source_url": m["source_url"],
            "original_copy": m.get("original_copy", ""),
            "text_copy": f"https://github.com/{repo()}/blob/main/records/{rel.with_suffix('.md').as_posix()}".replace(" ", "%20"),
            "sha256": m.get("sha256", ""),
            "first_seen_utc": m.get("first_seen_utc", ""),
            "server_file_date": m.get("http_last_modified", ""),
            "upload_folder": m.get("upload_folder", ""),
            "text_method": m.get("text_method", ""),
            "_sort": pre or server_date(m.get("http_last_modified")) or (m.get("first_seen_utc") or "")[:10],
            "_zip": "records/" + rel.with_suffix(".txt").as_posix(),
            "_text": text_of(md),
        }


README = """East Lyme public records - unofficial archive download
=====================================================

Built {built} UTC from https://github.com/{repo}

WHAT'S IN HERE
  records/       the text of every archived agenda, minutes, notice and other document,
                 one .txt file each, in folders by board, year and kind. File names
                 start with the meeting date (YYYY-MM-DD) so they sort in date order.
  charter_code/  the Town Charter and Code of Ordinances (unofficial copy).
  reports/       the posting-deadline, topic, upcoming-deadline and ordinance reports.

HOW TO SEARCH
  Windows: open the folder in File Explorer and type in the search box (top right).
           To search inside files, turn on File Explorer > Options > Search >
           "Always search file names and contents".
  Mac:     open the folder in Finder and type in the search box; choose the folder,
           not "This Mac".
  For a list of every document with dates and links, open
  east-lyme-records-index.csv (a separate download) in Excel or Google Sheets.

IMPORTANT
  These are automatic text copies. Scanned pages were read by OCR and can contain
  errors. The Town's original files are authoritative; each document's original is
  linked in the index (source_url) and a saved copy is linked too (original_copy).
"""


def build() -> list[Path]:
    DIST.mkdir(exist_ok=True)
    built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    data = list(rows())
    data.sort(key=lambda r: r["_sort"], reverse=True)

    csv_path = DIST / "east-lyme-records-index.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM so Excel reads UTF-8
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(data)

    zip_path = DIST / "east-lyme-records-text.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("READ-ME.txt", README.format(built=built, repo=repo()).replace("\n", "\r\n"))
        for r in data:
            head = (f"{r['title']}\r\nBoard: {r['board']}\r\nDate: {r['meeting_date'] or 'unknown'}\r\n"
                    f"Original: {r['source_url']}\r\nSHA-256 of original: {r['sha256']}\r\n"
                    f"Unofficial text copy; OCR may contain errors.\r\n{'=' * 60}\r\n\r\n")
            z.writestr(r["_zip"], head + r["_text"].replace("\r\n", "\n").replace("\n", "\r\n"))
        for sub in ("charter_code", "reports"):
            for p in sorted((ROOT / sub).rglob("*.md")):
                z.write(p, p.relative_to(ROOT).with_suffix(".txt").as_posix())

    db_path = DIST / "east-lyme-records.sqlite"
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.execute(f"CREATE TABLE documents (id INTEGER PRIMARY KEY, {', '.join(f + ' TEXT' for f in FIELDS)}, text TEXT)")
    con.executemany(f"INSERT INTO documents ({', '.join(FIELDS)}, text) VALUES ({', '.join('?' * (len(FIELDS) + 1))})",
                    [[r[k] for k in FIELDS] + [r["_text"]] for r in data])
    con.execute("CREATE VIRTUAL TABLE search USING fts5(title, text, content='documents', content_rowid='id')")
    con.execute("INSERT INTO search(rowid, title, text) SELECT id, title, text FROM documents")
    con.execute("CREATE TABLE about (key TEXT, value TEXT)")
    con.executemany("INSERT INTO about VALUES (?, ?)", [
        ("built_utc", built), ("source", f"https://github.com/{repo()}"),
        ("example_search", "SELECT meeting_date, board, title, source_url FROM documents "
                           "WHERE id IN (SELECT rowid FROM search WHERE search MATCH '\"speed camera\"') "
                           "ORDER BY meeting_date DESC;"),
        ("note", "Unofficial OCR text copies; the Town's originals are authoritative.")])
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"bundle: {len(data)} documents -> " + ", ".join(f"{p.name} ({p.stat().st_size / 1e6:.1f} MB)"
                                                          for p in (csv_path, zip_path, db_path)))
    return [csv_path, zip_path, db_path]


if __name__ == "__main__":
    build()
