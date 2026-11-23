#!/usr/bin/env python3
"""Update the "Blockchain proofs" table in README.md from manifests/*.txt and their .ots files.

For each manifest it shows the document count and, once the OpenTimestamps proof is complete,
the Bitcoin block that anchors it (linked to a public block explorer) and that block's time.
"""

from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- proofs:start -->", "<!-- proofs:end -->"
EXPLORER = "https://mempool.space"


def block_height(ots_file: Path) -> int | None:
    try:
        out = subprocess.run(["ots", "info", str(ots_file)], capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return None
    heights = [int(h) for h in re.findall(r"BitcoinBlockHeaderAttestation\((\d+)\)", out)]
    return min(heights) if heights else None


def block_time(height: int) -> str | None:
    try:
        h = requests.get(f"{EXPLORER}/api/block-height/{height}", timeout=30).text.strip()
        ts = requests.get(f"{EXPLORER}/api/block/{h}", timeout=30).json()["timestamp"]
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return None


def doc_count(manifest: Path) -> str:
    m = re.search(r"^# (\d+) documents", manifest.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def table() -> str:
    rows = ["| Manifest | Documents | Bitcoin block | Block time | Proof |", "|---|---|---|---|---|"]
    for man in sorted((ROOT / "manifests").glob("*.txt"), reverse=True):
        ots = man.with_name(man.name + ".ots")
        rel = man.relative_to(ROOT).as_posix()
        if not ots.exists():
            rows.append(f"| [{man.stem}]({rel}) | {doc_count(man)} | not yet stamped | | |")
            continue
        h = block_height(ots)
        if h is None:
            rows.append(f"| [{man.stem}]({rel}) | {doc_count(man)} | pending (usually confirms within a few hours) | | "
                        f"[.ots]({rel}.ots) |")
        else:
            when = block_time(h) or "see block"
            rows.append(f"| [{man.stem}]({rel}) | {doc_count(man)} | [{h:,}]({EXPLORER}/block/{h}) | {when} | "
                        f"[.ots]({rel}.ots) |")
    if len(rows) == 2:
        rows.append("| _none yet_ | | | | |")
    return "\n".join(rows)


def main() -> None:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    if START not in text:
        return
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), START + "\n" + table() + "\n" + END, text, flags=re.S)
    if new != text:
        readme.write_text(new, encoding="utf-8")


if __name__ == "__main__":
    main()
