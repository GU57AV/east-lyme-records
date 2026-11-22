#!/usr/bin/env python3
"""Unofficial archiver for East Lyme, CT public meeting records.

Crawls the board pages listed in config.json, finds every agenda/minutes
document linked from the yearly listing pages, and stores for each one:

  * the original file, unmodified                (records/.../<name>.pdf)
  * a searchable text copy with a metadata header (records/.../<name>.md)
  * a JSON sidecar with provenance and checksums  (records/.../<name>.json)

It also writes a dated change report (changes/YYYY-MM-DD.md) and a browsable
index per board. Files are never deleted: if a document disappears from the
Town's listing or changes, the sidecar records it and git keeps the old copy.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DOC_EXT = (".pdf", ".doc", ".docx")
MIN_CHARS_PER_PAGE = 40  # below this, treat a PDF as scanned and OCR it


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def log(msg: str) -> None:
    print(msg, flush=True)


class Fetcher:
    def __init__(self, user_agent: str, delay: float):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent
        self.delay = delay
        self._last = 0.0

    def get(self, url: str, **kw) -> requests.Response:
        for attempt in range(4):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.s.get(url, timeout=60, **kw)
                self._last = time.monotonic()
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                return r
            except (requests.RequestException,) as e:
                self._last = time.monotonic()
                backoff = 5 * (2 ** attempt)
                log(f"  retry {attempt + 1} for {url}: {e}; sleeping {backoff}s")
                time.sleep(backoff)
        raise RuntimeError(f"giving up on {url}")


def main_links(html: str, page_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup.find("article") or soup.body or soup
    out = []
    for a in main.find_all("a", href=True):
        out.append((urljoin(page_url, a["href"]).split("#")[0], " ".join(a.get_text().split())))
    return out


def is_doc(url: str) -> bool:
    return urlparse(url).path.lower().endswith(DOC_EXT)


def classify(listing_url: str, link_text: str, doc_url: str) -> dict:
    slug = urlparse(listing_url).path.rstrip("/").rsplit("/", 1)[-1].lower()
    name = unquote(urlparse(doc_url).path.rsplit("/", 1)[-1])
    hay = f"{slug} {link_text} {name}".lower()
    if "minute" in slug:
        kind = "minutes"
    elif "agenda" in slug:
        kind = "agendas"
    elif "minute" in hay:
        kind = "minutes"
    elif "agenda" in hay:
        kind = "agendas"
    else:
        kind = "other"
    m = re.search(r"(?<!\d)(19|20)\d{2}(?!\d)", slug)
    upload = re.search(r"/wp-content/uploads/(\d{4})/(\d{2})/", urlparse(doc_url).path)
    year = m.group(0) if m else (upload.group(1) if upload else "unknown")
    sub = "subcommittee" if re.search(r"sub-?committee", slug) else ""
    return {
        "kind": kind,
        "year": year,
        "subcommittee": bool(sub),
        "upload_folder": f"{upload.group(1)}-{upload.group(2)}" if upload else None,
        "filename": name,
    }


def safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return name or "document"


def pdf_pages(path: Path) -> int:
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"^Pages:\s+(\d+)", out, re.M)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def extract_text(path: Path) -> tuple[str, str]:
    """Return (text, method). Never modifies the original file."""
    if path.suffix.lower() != ".pdf":
        return "", "none (not a PDF)"
    try:
        text = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                              text=True, timeout=300).stdout
    except Exception:
        text = ""
    pages = max(pdf_pages(path), 1)
    if len(text.strip()) >= MIN_CHARS_PER_PAGE * pages:
        return text, "pdftotext"
    with tempfile.TemporaryDirectory() as td:
        if shutil.which("ocrmypdf"):
            sidecar = Path(td) / "out.txt"
            r = subprocess.run(["ocrmypdf", "--skip-text", "--quiet", "--sidecar", str(sidecar),
                                str(path), str(Path(td) / "out.pdf")], capture_output=True, text=True,
                               timeout=1800)
            if r.returncode == 0 and sidecar.exists():
                return sidecar.read_text(errors="replace"), "ocrmypdf (OCR)"
        if shutil.which("tesseract") and shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-r", "300", "-png", str(path), str(Path(td) / "p")],
                           capture_output=True, timeout=1800)
            parts = []
            for img in sorted(Path(td).glob("p-*.png")):
                r = subprocess.run(["tesseract", str(img), "-", "--psm", "3"], capture_output=True,
                                   text=True, timeout=600)
                parts.append(r.stdout)
            if any(p.strip() for p in parts):
                return "\f".join(parts), "tesseract (OCR)"
    return text, "pdftotext (little or no text found)"


def write_text_copy(md_path: Path, meta: dict, text: str) -> None:
    head = [
        "---",
        f"title: {json.dumps(meta['link_text'] or meta['filename'])}",
        f"board: {meta['board']}",
        f"kind: {meta['kind']}",
        f"source_url: {meta['source_url']}",
        f"listing_page: {meta['listing_page']}",
        f"sha256: {meta['sha256']}",
        f"text_method: {meta['text_method']}",
        f"first_seen_utc: {meta['first_seen_utc']}",
        "---",
        "",
        "> Unofficial text copy made automatically from the Town's file. OCR may contain errors; "
        f"the original is authoritative: {meta.get('original_copy') or meta['source_url']}",
        "",
        "```text",
        text.replace("```", "'''").rstrip(),
        "```",
        "",
    ]
    md_path.write_text("\n".join(head), encoding="utf-8")


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def crawl_board(f: Fetcher, board: dict, full: bool = True) -> tuple[list[dict], bool]:
    """Return ([{url, link_text, listing_page}], complete) for every document."""
    base = board["url"]
    base_path = urlparse(base).path
    html = f.get(base).text
    listings = []
    for url, text in main_links(html, base):
        p = urlparse(url)
        if p.netloc == urlparse(base).netloc and p.path.startswith(base_path) and p.path.rstrip("/") != base_path.rstrip("/"):
            if not is_doc(url) and url not in listings:
                listings.append(url)
    if not full:
        # Daily runs only re-read the current and previous year's listings to keep load low;
        # full runs (initial import, weekly recheck, manual) read everything.
        yr = dt.date.today().year
        recent = {str(yr), str(yr - 1), str(yr + 1)}
        listings = [u for u in listings if any(y in urlparse(u).path for y in recent)
                    or not re.search(r"(19|20)\d{2}", urlparse(u).path)]
    log(f"[{board['slug']}] {len(listings)} listing pages{'' if full else ' (recent years only)'}")
    found, seen, complete = [], set(), True
    # Documents linked directly from the board page count too.
    pages = [(base, html)] + [(u, None) for u in listings]
    for url, body in pages:
        if body is None:
            r = f.get(url)
            if r.status_code != 200:
                log(f"  skip listing {url}: HTTP {r.status_code}")
                complete = False
                continue
            body = r.text
        for doc, text in main_links(body, url):
            if is_doc(doc) and doc not in seen:
                seen.add(doc)
                found.append({"url": doc, "link_text": text, "listing_page": url})
    log(f"[{board['slug']}] {len(found)} documents linked")
    return found, complete


def run(args) -> int:
    cfg = load_json(ROOT / args.config, None)
    if not cfg:
        log("config not found")
        return 1
    f = Fetcher(cfg.get("user_agent", "east-lyme-records-archiver"), float(cfg.get("delay_seconds", 2)))
    state_path = ROOT / "state" / "state.json"
    state = load_json(state_path, {"initial_import_complete": False, "runs": 0})
    initial = not state.get("initial_import_complete")
    today = dt.date.today().isoformat()
    report = {"new": [], "changed": [], "removed": [], "restored": [], "errors": []}
    processed = 0
    incomplete = False
    deadline = time.monotonic() + args.time_budget * 60 if args.time_budget else float("inf")
    if not initial and not args.force and state.get("last_full_run_utc"):
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(state["last_full_run_utc"])
        if age < dt.timedelta(hours=float(cfg.get("min_hours_between_runs", 20))):
            log(f"last run {age} ago; nothing to do (use --force to run anyway)")
            return 0

    for board in cfg["boards"]:
        bdir = ROOT / "records" / board["slug"]
        try:
            full = initial or args.recheck or args.force
            docs, complete = crawl_board(f, board, full)
            complete = complete and full  # only mark removals after reading every listing
        except Exception as e:
            report["errors"].append(f"{board['slug']}: crawl failed: {e}")
            continue
        live_urls = {d["url"] for d in docs}

        for d in docs:
            c = classify(d["listing_page"], d["link_text"], d["url"])
            folder = bdir / ("subcommittee" if c["subcommittee"] else "board") / c["year"] / c["kind"]
            stem = safe_name(Path(c["filename"]).stem)
            ext = Path(c["filename"]).suffix.lower() or ".pdf"
            side = folder / f"{stem}.json"
            meta = load_json(side, None)
            if meta and meta.get("source_url") != d["url"]:
                # Same file name from a different URL: keep both.
                stem = f"{stem}--{hashlib.sha1(d['url'].encode()).hexdigest()[:8]}"
                side = folder / f"{stem}.json"
                meta = load_json(side, None)

            if meta and meta.get("removed_from_listing_utc"):
                meta.pop("removed_from_listing_utc", None)
                report["restored"].append(d["url"])
                side.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

            if meta and not args.recheck:
                continue  # already archived; content checks run with --recheck
            if (args.max_new and processed >= args.max_new) or time.monotonic() > deadline:
                incomplete = True
                continue

            headers = {}
            if meta and meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta and meta.get("http_last_modified"):
                headers["If-Modified-Since"] = meta["http_last_modified"]
            try:
                r = f.get(d["url"], headers=headers)
            except Exception as e:
                report["errors"].append(f"{d['url']}: {e}")
                continue
            if r.status_code == 304:
                continue
            if r.status_code != 200:
                report["errors"].append(f"{d['url']}: HTTP {r.status_code}")
                continue
            data = r.content
            sha = hashlib.sha256(data).hexdigest()
            if meta and meta.get("sha256") == sha:
                continue
            processed += 1
            folder.mkdir(parents=True, exist_ok=True)
            doc_path = folder / f"{stem}{ext}"
            doc_path.write_bytes(data)
            first_seen = meta["first_seen_utc"] if meta else now_utc()
            history = (meta or {}).get("versions", [])
            history.append({"sha256": sha, "bytes": len(data), "retrieved_utc": now_utc(),
                            "http_last_modified": r.headers.get("Last-Modified")})
            text, method = extract_text(doc_path)
            stored = store_original(cfg, board["slug"], c["year"], doc_path, stem, ext, sha)
            new_meta = {
                "board": board["slug"],
                "kind": c["kind"],
                "year": c["year"],
                "subcommittee": c["subcommittee"],
                "link_text": d["link_text"],
                "filename": c["filename"],
                "source_url": d["url"],
                "listing_page": d["listing_page"],
                "upload_folder": c["upload_folder"],
                "first_seen_utc": first_seen,
                "seen_in_initial_import": initial if not meta else meta.get("seen_in_initial_import", initial),
                "sha256": sha,
                "bytes": len(data),
                "pages": pdf_pages(doc_path) if ext == ".pdf" else None,
                "http_last_modified": r.headers.get("Last-Modified"),
                "etag": r.headers.get("ETag"),
                "text_method": method,
                "original_copy": stored,
                "versions": history,
            }
            side.write_text(json.dumps(new_meta, indent=2) + "\n", encoding="utf-8")
            write_text_copy(folder / f"{stem}.md", new_meta, text)
            (report["changed"] if meta else report["new"]).append(
                f"{d['link_text'] or c['filename']} — {d['url']}")
            log(f"  {'changed' if meta else 'new'}: {d['url']} ({method})")

        # Mark documents that vanished from the Town's listing (files are kept).
        for side in (bdir.rglob("*.json") if bdir.exists() and complete else []):
            meta = load_json(side, None)
            if meta and meta.get("source_url") not in live_urls and not meta.get("removed_from_listing_utc"):
                meta["removed_from_listing_utc"] = now_utc()
                side.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
                report["removed"].append(f"{meta.get('link_text') or meta.get('filename')} — {meta['source_url']}")

        write_index(bdir, board)

    if not incomplete:
        state["initial_import_complete"] = True
        state["last_full_run_utc"] = now_utc()
    state["runs"] = state.get("runs", 0) + 1
    state["last_run_utc"] = now_utc()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    write_report(today, report, initial, incomplete)
    write_manifest()
    if cfg.get("wayback_new_documents") and not initial:
        submit_wayback(f, report["new"] + report["changed"])
    log(f"done: {len(report['new'])} new, {len(report['changed'])} changed, "
        f"{len(report['removed'])} removed, {len(report['errors'])} errors"
        + (" (more remain; run again)" if incomplete else ""))
    return 0


_releases: set[str] = set()


def store_original(cfg: dict, board: str, year: str, path: Path, stem: str, ext: str, sha: str) -> str:
    """Keep the original file. With storage 'release' (default on GitHub), upload it as a
    GitHub Release asset named with its checksum, so every version is kept without
    bloating the git history. Returns where the copy lives."""
    mode = cfg.get("original_storage", "release")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if mode != "release" or not repo or not shutil.which("gh"):
        return str(path.relative_to(ROOT))
    tag = f"{board}-{year}"
    asset = f"{stem}--{sha[:12]}{ext}"
    if tag not in _releases:
        if subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode != 0:
            subprocess.run(["gh", "release", "create", tag, "--title", f"{board} {year} originals",
                            "--notes", "Original files as downloaded from eltownhall.com. Unofficial archive; "
                            "file names end with the first 12 characters of the SHA-256 checksum."],
                           capture_output=True)
        _releases.add(tag)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / asset
        shutil.copyfile(path, tmp)
        r = subprocess.run(["gh", "release", "upload", tag, str(tmp)], capture_output=True, text=True)
    if r.returncode != 0 and "already_exists" not in r.stderr:
        log(f"  release upload failed for {asset}: {r.stderr.strip()}")
        return str(path.relative_to(ROOT))
    path.unlink()  # originals live in the release, not in git
    return f"https://github.com/{repo}/releases/download/{tag}/{asset}"


def write_manifest() -> None:
    """Write a dated manifest of every archived file's SHA-256 when the set of hashes changes.
    The workflow stamps each new manifest with OpenTimestamps (Bitcoin-anchored proof)."""
    rows = []
    for side in sorted((ROOT / "records").rglob("*.json")):
        m = load_json(side, None)
        if m and m.get("sha256"):
            rows.append(f"{m['sha256']}  {m['source_url']}  {side.relative_to(ROOT).with_suffix('')}")
    if not rows:
        return
    rows.sort(key=lambda r: r.split("  ", 2)[2])
    body = "\n".join(rows) + "\n"
    mdir = ROOT / "manifests"
    mdir.mkdir(exist_ok=True)
    previous = sorted(mdir.glob("*.txt"))
    if previous:
        old = previous[-1].read_text(encoding="utf-8")
        if old.split("\n\n", 1)[-1] == body:
            return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    header = (f"# East Lyme Records (unofficial) manifest {stamp}\n"
              f"# {len(rows)} documents. Each line: SHA-256 of the original file, source URL, archive path.\n"
              "# A matching .ots file is an OpenTimestamps proof that this exact list existed by the\n"
              "# time of the Bitcoin block it names. Verify at https://opentimestamps.org\n\n")
    (mdir / f"{stamp}.txt").write_text(header + body, encoding="utf-8")
    log(f"manifest written: manifests/{stamp}.txt ({len(rows)} documents)")


def write_report(today: str, rep: dict, initial: bool, incomplete: bool) -> None:
    if not any(rep.values()):
        return
    out = ROOT / "changes" / f"{today}.md"
    out.parent.mkdir(exist_ok=True)
    lines = [f"# Changes found {today}", ""]
    if initial:
        lines += ["_Initial import: these documents were already on the Town website when the archive "
                  "started, so the dates here show when they were archived, not when the Town posted them._", ""]
    if incomplete:
        lines += ["_Import in progress; more documents will be added on the next run._", ""]
    for key, title in (("new", "New documents"), ("changed", "Documents whose content changed"),
                       ("removed", "Documents no longer linked on the Town website (copies kept)"),
                       ("restored", "Documents linked again"), ("errors", "Errors")):
        if rep[key]:
            lines += [f"## {title} ({len(rep[key])})", ""] + [f"- {x}" for x in rep[key]] + [""]
    mode = "a" if out.exists() else "w"
    with out.open(mode, encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_index(bdir: Path, board: dict) -> None:
    if not bdir.exists():
        return
    rows = []
    for side in bdir.rglob("*.json"):
        m = load_json(side, None)
        if not m:
            continue
        rel = side.relative_to(bdir)
        orig = m.get("original_copy") or ""
        if orig and not orig.startswith("http"):
            orig = os.path.relpath(ROOT / orig, bdir)
        rows.append((m.get("year", ""), m.get("subcommittee"), m.get("kind", ""), m.get("link_text") or m.get("filename"),
                     str(rel.with_suffix(".md")), orig,
                     m.get("first_seen_utc", "")[:10], m.get("removed_from_listing_utc")))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]), reverse=True)
    lines = [f"# {board['name']} — archived documents", "",
             f"Source: <{board['url']}>  ", "Unofficial archive. “Archived” is the date this archive first saw the document.", "",
             "| Year | Body | Type | Document | Text | Original | Archived |", "|---|---|---|---|---|---|---|"]
    for y, sub, kind, title, md, doc, seen, removed in rows:
        flag = " (removed from Town site)" if removed else ""
        title = str(title).replace("|", "\\|")
        lines.append(f"| {y} | {'Subcommittee' if sub else 'Board'} | {kind} | {title}{flag} | "
                     f"[text]({md.replace(' ', '%20')}) | {'[original](' + doc.replace(' ', '%20') + ')' if doc else ''} | {seen} |")
    (bdir / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def submit_wayback(f: Fetcher, items: list[str]) -> None:
    for item in items[:25]:
        url = item.rsplit(" — ", 1)[-1]
        try:
            time.sleep(10)
            r = f.s.get("https://web.archive.org/save/" + url, timeout=120)
            log(f"  wayback: requested capture of {url} (HTTP {r.status_code})")
        except Exception as e:
            log(f"  wayback failed for {url}: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--max-new", type=int, default=0, help="stop after this many downloads (0 = no limit)")
    ap.add_argument("--recheck", action="store_true", help="re-download archived files to detect silent changes")
    ap.add_argument("--time-budget", type=float, default=0, help="stop starting new downloads after N minutes")
    ap.add_argument("--force", action="store_true", help="run even if a full run happened recently")
    sys.exit(run(ap.parse_args()))
