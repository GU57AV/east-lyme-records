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

## Blockchain timestamps

Whenever the set of archived files changes, the archive writes a dated list of every file's SHA-256
hash to [`manifests/`](manifests) and stamps it with [OpenTimestamps](https://opentimestamps.org),
which anchors the list in the Bitcoin blockchain. The `.ots` file next to each manifest proves that
exact list existed no later than the time of the Bitcoin block it names. Nobody, including the owner
of this repository, can backdate it.

To verify: download a manifest and its `.ots` file and drop both on <https://opentimestamps.org>,
or run `pip install opentimestamps-client` and `ots verify manifests/<name>.txt.ots`. To check a
document, compute its hash (`certutil -hashfile file.pdf SHA256` on Windows,
`sha256sum file.pdf` on Mac or Linux) and find it in the manifest.

Proofs start as "pending" and are completed automatically on a later run, usually within a few hours.

### Proofs so far

Each row shows when that list of documents was anchored. Click the block number to see the block,
and its time, on a public Bitcoin block explorer.

<!-- proofs:start -->
| Manifest | Documents | Bitcoin block | Block time | Proof |
|---|---|---|---|---|
| _none yet_ | | | | |
<!-- proofs:end -->

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
