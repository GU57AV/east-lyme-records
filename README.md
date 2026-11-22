# East Lyme Records (unofficial archive)

**This is not an official Town of East Lyme website.** It is a resident-run archive of public
meeting records published on [eltownhall.com](https://eltownhall.com). The Town's own website
remains the official source.

## What it does

A scheduled job checks the Town website, downloads every agenda and set of minutes linked there,
and records:

- **The original file, unmodified**, stored as a download under [Releases](../../releases).
  Each file name ends with the first 12 characters of its SHA-256 checksum.
- **A searchable text copy** (`.md`) next to a **metadata file** (`.json`) with the source address,
  the listing page it came from, the checksum, the server's reported modification date, and the
  date this archive first saw it.
- **A dated change report** in [`changes/`](changes) whenever a document is added, changed, or removed.

Documents are never deleted here. If the Town replaces or removes a file, the metadata records it,
and the earlier version stays in the history.

Currently archived: [Board of Selectmen](records/board-of-selectmen/INDEX.md).

## How to read the dates

- **Archived / first seen** is when this archive first found the document. For documents that were
  already online when the archive started (marked `seen_in_initial_import`), this is *not* when the
  Town posted them.
- From the start of the archive forward, the git history shows when each document first appeared
  and whether it later changed.
- Newly found documents are also submitted to the Internet Archive's Wayback Machine for an
  independent timestamp.

## Load on the Town website

The archiver identifies itself by name and a link to this repository, waits 20 seconds between
requests (the delay the Town's robots.txt asks of search engines), and avoids the paths that file
excludes. Daily checks read only the current year's listing pages; a full check runs weekly.

## Limits

Text copies of scanned documents are made with OCR and may contain errors. Always rely on the
original file. If you find a problem, open an issue.

## Running it yourself

```
pip install requests beautifulsoup4    # plus poppler-utils, tesseract-ocr, ocrmypdf
python archiver/crawl.py --force
```

Add boards in `config.json`.
