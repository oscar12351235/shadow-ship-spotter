"""Download selected public files from the Global Fishing Watch / Paolo et al. (2024) figshare
records (CC BY 4.0, no login required) and verify them against figshare's published MD5.

Records:
  training data  https://doi.org/10.6084/m9.figshare.24309469  (article 24309469)
  analysis data  https://doi.org/10.6084/m9.figshare.24309475  (article 24309475)

Usage (from the repository root):
    uv run python -I scripts/download_gfw_paolo2024.py                 # default small set
    uv run python -I scripts/download_gfw_paolo2024.py --with-detections   # + 1.7 GB table

Default set: both README.md files and detection_tiles.zip (143 MB: 11,965 Sentinel-1 80x80
VV/VH tiles labelled vessel / non-vessel). --with-detections adds
industrial_vessels_v20240102.csv.zip (GFW's global SAR vessel detections 2017-2021, matched to
AIS). Files land in data/raw/gfw_paolo2024/<record>/; zip files are extracted into a fresh
sibling directory "<name>_extracted/" except the large CSV, which is read in place.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from shadow_ship_spotter.data.download import download
from shadow_ship_spotter.data.storage import publish_directory, write_json
from shadow_ship_spotter.paths import RAW_DIR, SOURCES_FILE

RECORDS = {"training": 24309469, "analysis": 24309475}
DEFAULT = {"training": ["README.md", "detection_tiles.zip"], "analysis": ["README.md"]}
DETECTIONS = "industrial_vessels_v20240102.csv.zip"
EXTRACT = {"detection_tiles.zip"}
OUT = RAW_DIR / "gfw_paolo2024"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--with-detections", action="store_true")
    args = ap.parse_args()
    wanted = {k: list(v) for k, v in DEFAULT.items()}
    if args.with_detections:
        wanted["analysis"].append(DETECTIONS)

    registry = json.loads(SOURCES_FILE.read_text())
    manifest = []
    verified = 0
    for rec, names in wanted.items():
        release = registry[f"gfw_paolo2024_{rec}"]
        for name, f in release["files"].items():
            dest = OUT / rec / name
            # Keep records for previously installed optional assets in the manifest.
            if name not in names and not dest.is_file():
                continue
            md5 = f["md5"]
            url = f"https://ndownloader.figshare.com/files/{f['file_id']}"
            if name in names:
                print(f"[{rec}] {name} ({f['bytes'] / 1e6:.1f} MB)", file=sys.stderr)
                download(url, dest, expected_size=f["bytes"], checksum=("md5", md5))
                verified += 1
            manifest.append(
                {
                    "record": rec,
                    "article": RECORDS[rec],
                    "file": name,
                    "file_id": f["file_id"],
                    "article_version": release["article_version"],
                    "size_bytes": f["bytes"],
                    "md5": md5,
                    "validation": "verified" if name in names else "installed_not_rechecked",
                    "url": url,
                }
            )
            if name in names and name in EXTRACT:
                out = dest.with_name(dest.stem + "_extracted")
                extract_tiles(dest, out)
    write_json(OUT / "manifest.json", manifest)
    print(f"Verified {verified} requested files. Manifest at {OUT / 'manifest.json'}")


def extract_tiles(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        for m in members:
            if (
                m.filename.startswith("/")
                or ".." in m.filename.split("/")
                or "\\" in m.filename
                or ":" in m.filename
            ):
                raise ValueError("unsafe path in zip")

        def complete(root: Path) -> bool:
            return all(
                (root / m.filename).is_file() and (root / m.filename).stat().st_size == m.file_size
                for m in members
                if not m.is_dir()
            )

        publish_directory(dest, zf.extractall, complete)


if __name__ == "__main__":
    main()
