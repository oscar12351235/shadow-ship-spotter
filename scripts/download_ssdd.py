"""Download, verify and extract the Official SSDD archive (Official-SSDD-OPEN.rar).

Usage (from the repository root):
    uv run python scripts/download_ssdd.py            # download + verify + extract
    uv run python scripts/download_ssdd.py --no-extract

Source registry (URL, size, sha256, date) lives in data/sources.json under key "ssdd".
On the first successful download, missing checksum fields are filled in automatically so
that later downloads are verified against them.

Extraction needs a RAR-capable tool: bsdtar/tar (libarchive >= 3.4; macOS and Windows 10+
`tar` qualify), `unar`, `unrar` or `7z`. The archive is extracted into a fresh directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

from shadow_ship_spotter.data.download import download, gdrive_direct_url, verify
from shadow_ship_spotter.data.storage import publish_directory, write_json
from shadow_ship_spotter.paths import RAW_DIR, SOURCES_FILE

KEY = "ssdd"
DEST_DIR = RAW_DIR / "ssdd"


def _extract_cmd(archive: Path, out: Path) -> list[str]:
    for tool in ("bsdtar", "tar"):
        exe = shutil.which(tool)
        if (
            exe
            and "libarchive"
            in subprocess.run([exe, "--version"], capture_output=True, text=True).stdout
        ):
            return [exe, "-xf", str(archive), "-C", str(out)]
    if shutil.which("unar"):
        return ["unar", "-q", "-o", str(out), str(archive)]
    if shutil.which("unrar"):
        return ["unrar", "x", "-idq", str(archive), str(out) + "/"]
    for tool in ("7z", "7zz"):
        if shutil.which(tool):
            return [tool, "x", "-y", f"-o{out}", str(archive)]
    raise SystemExit("No RAR-capable extractor found (need libarchive tar, unar, unrar or 7z).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--no-extract", action="store_true")
    args = ap.parse_args()

    sources = json.loads(SOURCES_FILE.read_text())
    src = sources[KEY]
    archive = DEST_DIR / "download" / src["filename"]

    if not archive.exists():
        print(f"Resolving Google Drive file {src['gdrive_id']} ...", file=sys.stderr)
        url = gdrive_direct_url(src["gdrive_id"])
        print(f"Downloading {src['filename']} -> {archive}", file=sys.stderr)
        download(
            url,
            archive,
            expected_size=src.get("size_bytes"),
            checksum=("sha256", src["sha256"]) if src.get("sha256") else None,
        )

    print("Verifying checksum ...", file=sys.stderr)
    digest = verify(archive, src.get("sha256"), src.get("size_bytes"))
    if not src.get("sha256"):
        src.update(
            sha256=digest,
            size_bytes=archive.stat().st_size,
            downloaded_on=dt.date.today().isoformat(),
        )
        write_json(SOURCES_FILE, sources)
        print(f"Recorded sha256={digest} in {SOURCES_FILE}", file=sys.stderr)
    else:
        print(f"OK sha256={digest}", file=sys.stderr)

    if args.no_extract:
        return
    out = DEST_DIR / "extracted"

    def complete(stage: Path) -> bool:
        coco = stage / "Official-SSDD-OPEN/BBox_SSDD/coco_style"
        return all(
            (coco / "annotations" / f"{split}.json").is_file()
            and len(list((coco / "images" / split).glob("*.jpg"))) == count
            for split, count in (("train", 928), ("test", 232))
        )

    def extract(stage: Path) -> None:
        subprocess.run(_extract_cmd(archive, stage), check=True)

    publish_directory(out, extract, complete)
    print(f"Extracted to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
