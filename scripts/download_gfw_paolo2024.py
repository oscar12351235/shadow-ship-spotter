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
import urllib.request
import zipfile

from shadow_ship_spotter.data.download import USER_AGENT, download, file_hash
from shadow_ship_spotter.paths import RAW_DIR

RECORDS = {"training": 24309469, "analysis": 24309475}
DEFAULT = {"training": ["README.md", "detection_tiles.zip"], "analysis": ["README.md"]}
DETECTIONS = "industrial_vessels_v20240102.csv.zip"
EXTRACT = {"detection_tiles.zip"}
OUT = RAW_DIR / "gfw_paolo2024"


def record_files(article: int) -> dict[str, dict]:
    req = urllib.request.Request(
        f"https://api.figshare.com/v2/articles/{article}", headers={"User-Agent": USER_AGENT}
    )
    meta = json.load(urllib.request.urlopen(req, timeout=60))  # noqa: S310
    return {f["name"]: f for f in meta["files"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--with-detections", action="store_true")
    args = ap.parse_args()
    wanted = {k: list(v) for k, v in DEFAULT.items()}
    if args.with_detections:
        wanted["analysis"].append(DETECTIONS)

    manifest = []
    for rec, names in wanted.items():
        files = record_files(RECORDS[rec])
        for name in names:
            f = files[name]
            dest = OUT / rec / name
            print(f"[{rec}] {name} ({f['size'] / 1e6:.1f} MB)", file=sys.stderr)
            download(f["download_url"], dest, expected_size=f["size"])
            md5 = file_hash(dest, "md5")
            if md5 != f["computed_md5"]:
                sys.exit(f"MD5 mismatch for {dest}: {md5} != {f['computed_md5']}")
            manifest.append(
                {
                    "record": rec,
                    "article": RECORDS[rec],
                    "file": name,
                    "file_id": f["id"],
                    "size_bytes": f["size"],
                    "md5": md5,
                    "url": f["download_url"],
                }
            )
            if name in EXTRACT:
                out = dest.with_name(dest.stem + "_extracted")
                if not out.exists():
                    out.mkdir()
                    with zipfile.ZipFile(dest) as zf:
                        for m in zf.infolist():  # refuse absolute / parent-traversal paths
                            if m.filename.startswith("/") or ".." in m.filename.split("/"):
                                sys.exit(f"unsafe path in zip: {m.filename}")
                        zf.extractall(out)
                    print(f"  extracted -> {out}", file=sys.stderr)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"MD5 verified for {len(manifest)} files; manifest at {OUT / 'manifest.json'}")


if __name__ == "__main__":
    main()
