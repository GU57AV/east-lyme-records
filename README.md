# East Lyme Records (unofficial archive)

**This is not an official Town of East Lyme website.** It is a resident-run archive of public
meeting records published on [eltownhall.com](https://eltownhall.com). The Town's own website
remains the official source.

## Start here: how to use this archive (plain English)

New to GitHub? This section walks through everything step by step. You don't need an account to
look at anything here. You only need one if you want to report a problem or get updates.

**In this guide:**
[What this is](#what-this-is) ·
[The Charter and Code](#reading-the-charter-and-code) ·
[Finding a document](#finding-a-document) ·
[Searching](#searching-every-document-at-once) ·
[Reading a document's page](#what-youll-see-for-each-document) ·
[Seeing what changed](#seeing-what-was-added-changed-or-removed) ·
[What the dates mean](#what-the-dates-mean) ·
[Checking a document is genuine](#checking-that-a-document-is-genuine) ·
[The blockchain proofs](#the-blockchain-proofs-explained-simply) ·
[Deadline report and topic alerts](#deadline-report-and-topic-alerts) ·
[How often it checks](#how-often-it-checks) ·
[Downloading everything](#downloading-everything) ·
[Getting updates](#getting-updates) ·
[Words used here](#words-used-here) ·
[Problems and questions](#problems-and-questions)

### What this is

Think of this as a filing cabinet that copies itself. A small program visits the Town of East Lyme
website on a schedule, finds every agenda and set of minutes the Town has posted for its boards and
commissions, and saves a copy of each one here. It also writes down exactly when it found each
document and takes a digital "fingerprint" of it, so anyone can later tell whether a document was
changed, replaced, or taken down.

It is **not** run by the Town, and it does not replace the Town's website. If the two ever disagree,
check the Town's original, then look here to see whether and when it changed.

### Reading the Charter and Code

Open the [Charter and Code contents page](https://github.com/GU57AV/east-lyme-records/blob/main/code/README.md) and click a chapter. Every section
is a heading you can link to: hover over it and click the small link icon to copy a link straight to,
say, Charter § 3.4. The page shows which edition it is; newer ordinances not yet in that edition are
tracked through the publisher's new-ordinance list described above.

### Finding a document

1. Open the [list of archived boards](https://github.com/GU57AV/east-lyme-records/blob/main/records/README.md). It shows every board and
   commission, how many documents are saved for each, and whether its first import is finished.
2. Click the board you want, for example **East Lyme Board of Selectmen**. That opens its index: one
   table of every saved document, newest first.
3. Each row shows the year, whether it's the board or a subcommittee, whether it's an agenda or
   minutes, the document's title, and the date this archive first saved it.
4. In that row, click:
   - **text** to read the words of the document right in your browser, or
   - **original** to download the exact file the Town posted (usually a PDF).

Tip: the index is long. Press **Ctrl+F** (Windows) or **Cmd+F** (Mac) and type a date or word,
such as `September 16 2026`, to jump to it.

### Searching every document at once

1. Click in the **search box** at the very top of any page here (it may say "Type / to search").
2. Type what you're looking for, such as `speed camera` or `Altumint`.
3. Choose **Search in this repository**, then click **Code** on the left of the results.
4. Each result is a document's text copy. Click it to read it; the original is linked from there.

Good to know:

- Put phrases in quotes, like `"public hearing"`, to find those words together.
- GitHub's search skips very large files (roughly over 350 KB of text), so a few long agenda packets
  won't show up. Searching a downloaded copy (see [Downloading everything](#downloading-everything))
  finds those too.
- Search finds the words in the text copies. For scanned documents those words come from automatic
  text recognition, so an unusual spelling or a smudged page can hide a match.

### What you'll see for each document

Every document has up to three parts, stored side by side with the same name:

- **The text copy** (ends in `.md`). The top lists, in plain words:
  - `title`: the name the Town gave the link
  - `board` and `kind`: which board, and whether it's an agenda or minutes
  - `source_url`: where the Town posted it
  - `listing_page`: the Town page that linked to it
  - `sha256`: the document's fingerprint (see below)
  - `text_method`: how the words were captured. `pdftotext` means copied exactly from a typed
    document; `OCR` means read from a scan by text recognition and may contain mistakes.
  - `first_seen_utc`: when this archive first saved it (UTC is about 5 hours ahead of East Lyme
    time in winter, 4 in summer)

  Below that is the document's text.
- **The original file**, stored on the [Releases page](https://github.com/GU57AV/east-lyme-records/releases). It's never changed. Its file name
  ends with the first 12 characters of its fingerprint, so you can tell versions apart.
- **The details file** (ends in `.json`). Same information in a form computers read, plus every
  version the archive has seen, the Town server's own date for each, and, if it happened, the date the
  Town removed it.

### Seeing what was added, changed, or removed

- **Change reports.** Open the [changes folder](https://github.com/GU57AV/east-lyme-records/tree/main/changes). There's one page per day
  something happened, listing new documents, documents whose contents changed, and documents the
  Town stopped linking to. Each entry has a link to the Town's address.
- **Removed documents** stay here. In a board's index they're marked "(removed from Town site)".
- **A document's full history.** Open its text copy and click **History** near the top right. Each
  entry is a moment the archive saved something, with the date. Click one to see exactly which words
  changed, highlighted in red and green.

### What the dates mean

- **"Archived" or `first_seen_utc`** is when *this archive* first found a document. That is not
  necessarily when the Town posted it.
- **Documents that were already online when the archive started** (November 22, 2026 for the Board
  of Selectmen; later for the other boards) are marked `seen_in_initial_import: true`. For those, the
  archive can only show they existed by that date.
- **Documents posted after the archive started** are found on the next check. So the posting time is
  somewhere between the last check that didn't find it and the check that did. The change reports and
  history show both.
- The Town server's own date (`http_last_modified`) is recorded too. It shows when the file was last
  saved on the Town's server, which is a clue but not proof of when it was posted.

### Checking that a document is genuine

Every file has a **fingerprint** (called a SHA-256 hash): a 64-character code calculated from every
byte in the file. Change even one letter and the fingerprint is completely different. To check a
file:

1. Download it, from the Town's website or from here.
2. Work out its fingerprint:
   - **Windows:** open the Start menu, type `cmd`, press Enter, then type
     `certutil -hashfile ` (with a space at the end), drag the file into the window, type ` SHA256`
     (with a space before it), and press Enter.
   - **Mac:** open **Terminal**, type `shasum -a 256 ` (with a space at the end), drag the file into
     the window, and press Enter.
3. Compare the code it prints with the `sha256` shown on the document's page here. If they match,
   it's the identical file. If they don't, the files are different.

### The blockchain proofs, explained simply

The archive can prove its records weren't changed or backdated later, even by whoever runs it.

1. Each time the collection changes, the archive writes a **manifest**: a list of every document's
   fingerprint. These are in the [manifests folder](https://github.com/GU57AV/east-lyme-records/tree/main/manifests).
2. The manifest's own fingerprint is sent to a free public service called
   [OpenTimestamps](https://opentimestamps.org), which bundles it with many others and writes one
   combined code into the **Bitcoin blockchain**: a public record that thousands of computers keep
   copies of and nobody can edit.
3. Each manifest gets a small proof file (ending in `.ots`) showing how its fingerprint connects to
   that Bitcoin entry. The table [below](#proofs-so-far) lists each proof and links to its Bitcoin
   block and the block's time.

What this proves: that exact list of documents existed **no later than** that block's time. It does
**not** put any document on the blockchain; only a code that means nothing without the proof file.

To check a proof yourself:

1. Download a manifest (`.txt`) and its proof (`.txt.ots`) from the manifests folder. Open each file
   and click the **download** button (a downward arrow) near the top right.
2. Go to [opentimestamps.org](https://opentimestamps.org) and drag both files onto the page.
3. It reports which Bitcoin block confirms the list and when. To connect a particular document,
   find its fingerprint in the manifest (Ctrl+F or Cmd+F).

New proofs say "pending" for a few hours until Bitcoin confirms them. That's normal.

### Deadline report and topic alerts

Two automatic reports are built from what the archive records:

- **[Posting-deadline report](https://github.com/GU57AV/east-lyme-records/blob/main/reports/compliance.md).** Connecticut's Freedom of Information
  Act (CGS § 1-225) says a meeting's agenda must be available at least 24 hours before the meeting, and its
  minutes within seven days after. For every agenda and set of minutes posted after the archive started,
  the report checks whether the Town met those deadlines and lists anything that appears late, plus
  meetings with an agenda but no minutes after eight days.

  How it decides: the archive notes the last time it checked a Town page and the document *wasn't* there,
  and the first time it was. The document was posted somewhere in between. Something is flagged only when
  it was provably missing at a check made after its deadline. Each flag shows those times so you can
  judge it yourself.

  A flag is a lead, not a finding. A document posted on a page the archive doesn't watch, a cancelled
  meeting, or a misread date can all cause one. Amended agendas are listed separately for review, since
  adding items late can be allowed.
- **[Topic index](https://github.com/GU57AV/east-lyme-records/blob/main/reports/topics.md).** Every archived document mentioning each watched
  topic, such as "speed camera," "Altumint," "license plate," "executive session" or "proposed ordinance,"
  with a short excerpt and a link. The list of topics is in `config.json` under `topics`.

When a run finds new deadline flags, or a newly posted document mentions a watched topic, it opens an
**issue** (see the **Issues** tab) describing what it found. If you watch this repository on GitHub (see
[Getting updates](#getting-updates)), you get those by email.

### How often it checks

- **About every three hours:** the code publisher's list of new East Lyme ordinances, and every
  ordinance it links to.
- **About every three hours:** each board's agenda page for the current year, so a new agenda's posting
  time is known to within a few hours.
- **Once a day:** each board's current listing pages, for anything new or removed.
- **Every day, a rotating batch:** 150 previously saved documents are downloaded again and compared
  with their fingerprints, to catch files the Town replaced without renaming. Recent years come first.

To be considerate of the Town's server, the archive waits 20 seconds between requests. That's why the
first import of a large board takes a while.

### Downloading everything

- **All text copies, details, change reports and proofs:** click the green **Code** button on the
  [main page](https://github.com/GU57AV/east-lyme-records), then **Download ZIP**. Unzip it and search the folder with your computer's
  search, or any text-search tool.
- **Originals:** these are on the [Releases page](https://github.com/GU57AV/east-lyme-records/releases), grouped by board and year. Click a
  release to see and download its files.

### Getting updates

- **News reader (RSS):** add [this feed](https://github.com/GU57AV/east-lyme-records/commits/main.atom) to any news reader app to see each
  update as it's saved.
- **GitHub account:** click **Watch** at the top of the main page, then **Custom**, and tick
  **Releases** and **Issues** to get emails about new originals, deadline flags and topic alerts.

### Words used here

- **Repository:** this whole collection of files and its history.
- **Commit:** one saved update, with a date and a description.
- **Hash / fingerprint (SHA-256):** a 64-character code that identifies one exact file.
- **Manifest:** a list of every document's fingerprint at one moment.
- **Release:** a page holding downloadable original files.
- **OCR (text recognition):** software that reads the words in a scanned image; it can make mistakes.
- **UTC:** world standard time; subtract 5 hours for East Lyme in winter, 4 in summer.

### Problems and questions

If something looks wrong, such as a missing document, a garbled text copy, or a broken link, click
**Issues** at the top of the page, then **New issue**, and describe it. You'll need a free GitHub
account.

## How it works (technical details)

### What it does

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

Currently archived: the Board of Selectmen and every board and commission on the Town's
[Boards & Commissions page](https://eltownhall.com/government/boards-commissions/), plus Town Meetings.
See the [list of archived boards](records/README.md).

Also here: a searchable copy of the **[Town Charter and Code of Ordinances](code/README.md)**, one page per
chapter, from American Legal Publishing's 2025 S-7 edition (current through April 16, 2025).

Also watched on every run (about every three hours): American Legal Publishing's
[Advance Legislative Service list](https://files.amlegal.com/pdffiles/EastLyme/EastLymeALS.pdf)
of new East Lyme ordinances not yet in the Code, and every ordinance it links to. Each is hashed;
any change, new link, or removed link is recorded in [`records/watched/`](records/watched) and the
change reports, along with the publisher's server date for each version.

### How to read the dates

- **Archived / first seen** is when this archive first found the document. For documents that were
  already online when the archive started (marked `seen_in_initial_import`), this is *not* when the
  Town posted them.
- From the start of the archive forward, the git history shows when each document first appeared
  and whether it later changed.
- Newly found documents are also submitted to the Internet Archive's Wayback Machine for an
  independent timestamp.

### Blockchain timestamps

Whenever the set of archived files changes, the archive writes a dated list of every file's SHA-256
hash to [`manifests/`](manifests) and stamps it with [OpenTimestamps](https://opentimestamps.org),
which anchors the list in the Bitcoin blockchain. The `.ots` file next to each manifest proves that
exact list existed no later than the time of the Bitcoin block it names. Nobody, including the owner
of this repository, can backdate it.

To verify: download a manifest and its `.ots` file and drop both on <https://opentimestamps.org>,
or run `pip install opentimestamps-client` and `ots verify manifests/<name>.txt.ots`. To check a
document, compute its hash (`certutil -hashfile file.pdf SHA256` on Windows,
`shasum -a 256 file.pdf` on Mac, `sha256sum file.pdf` on Linux) and find it in the manifest.

Proofs start as "pending" and are completed automatically on a later run, usually within a few hours.

#### Proofs so far

Each row shows when that list of documents was anchored. Click the block number to see the block,
and its time, on a public Bitcoin block explorer.

<!-- proofs:start -->
| Manifest | Documents | Bitcoin block | Block time | Proof |
|---|---|---|---|---|
| [2026-11-23T092110Z](manifests/2026-11-23T092110Z.txt) | 1728 | [977,180](https://mempool.space/block/977180) | 2026-11-23 09:53 UTC | [.ots](manifests/2026-11-23T092110Z.txt.ots) |
| [2026-11-23T074334Z](manifests/2026-11-23T074334Z.txt) | 1450 | [977,170](https://mempool.space/block/977170) | 2026-11-23 07:52 UTC | [.ots](manifests/2026-11-23T074334Z.txt.ots) |
| [2026-11-23T024535Z](manifests/2026-11-23T024535Z.txt) | 726 | [977,170](https://mempool.space/block/977170) | 2026-11-23 07:52 UTC | [.ots](manifests/2026-11-23T024535Z.txt.ots) |
<!-- proofs:end -->

### Load on the Town website

The archiver identifies itself by name and a link to this repository, waits 20 seconds between
requests (the delay the Town's robots.txt asks of search engines), and avoids the paths that file
excludes. Daily checks read only the current year's listing pages and re-check a rotating set of 150 archived
files for silent changes.

### Limits

Text copies of scanned documents are made with OCR and may contain errors. Always rely on the
original file. If you find a problem, open an issue.

## Running your own copy

The archive is a single small program, [`archiver/crawl.py`](https://github.com/GU57AV/east-lyme-records/blob/main/archiver/crawl.py), plus a
settings file ([`config.json`](https://github.com/GU57AV/east-lyme-records/blob/main/config.json)) and a schedule
([`.github/workflows/archive.yml`](https://github.com/GU57AV/east-lyme-records/blob/main/.github/workflows/archive.yml)) that tells GitHub when
to run it. "Running your own copy" means running that same program yourself, so you have an
independent record that doesn't depend on this one. Two archives that agree are stronger evidence than
one.

### Option 1: your own copy on GitHub (no computer setup)

You'd be running the same program on GitHub's servers, under your own account, for free.

1. Create a free GitHub account if you don't have one, and sign in.
2. On this archive's [main page](https://github.com/GU57AV/east-lyme-records), click **Fork** (top right), then **Create fork**. This makes your
   own repository with all the code and everything archived so far.
3. In your new repository, click the **Actions** tab, and click the button to enable workflows. GitHub
   turns them off in new forks until you do this.
4. Click **Archive East Lyme meeting records** on the left, then **Run workflow**, then the green
   **Run workflow** button. After that it runs on its own schedule.

What to expect:

- Your copy starts with this archive's files. From then on, your checks, change reports, originals on
  your own Releases page, and blockchain proofs are made independently by your copy.
- GitHub doesn't copy Releases into forks, so links to originals saved before you forked still point
  here. New originals go to your own Releases page.
- Your copy identifies itself to the Town's server with a link to *your* repository.
- Please keep the 20-second delay in `config.json`. Several copies hitting the Town's site quickly
  would be unfair to its server.

### Option 2: on your own computer

For people comfortable with a command line. You'd be running the program once each time you start it,
and the files stay on your computer.

1. Install [Python 3](https://www.python.org), then the text tools: `poppler-utils`, `tesseract-ocr`
   and `ocrmypdf` (on a Mac with Homebrew: `brew install poppler tesseract ocrmypdf`).
2. Download this repository (green **Code** button, then **Download ZIP**, then unzip), and open a
   terminal in that folder.
3. Run:

   ```
   pip install requests beautifulsoup4 opentimestamps-client
   python archiver/crawl.py --force
   ```

Originals are kept in the `records` folder next to their text copies. To run it on a schedule, use your
computer's scheduler (Task Scheduler on Windows, `cron` on Mac or Linux).

### Changing what's archived

Edit `config.json`: each entry under `boards` is one Town board page, and each entry under `watch` is
one file checked every run. A newly added board gets its own first import, marked as such, so its older
documents aren't reported as newly posted.
