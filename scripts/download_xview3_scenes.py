"""Download and extract selected xView3-SAR scenes using the user's personal signed link lists.

xView3 data require a (free) account at https://iuu.xview.us/. After logging in and accepting
the terms on the "Download the data" page, save the link lists ({tiny,validation,train,
public}.txt; aria2 input format) and the label CSVs into data/raw/xview3/ (git-ignored).
Signed links are personal and expire after a few hours: never commit or share them.

Usage (from the repository root):
    uv run python -I scripts/download_xview3_scenes.py --list validation.txt \
        --scenes b1844cde847a3942v fc2f57371370c521v fe6a8d80fb5ebb8ev

Each scene archive is verified against the SHA-1 given in the link list, then extracted
(with tarfile's safe "data" filter) into data/raw/xview3/scenes/<scene_id>/.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
from pathlib import Path

from shadow_ship_spotter.data.download import download
from shadow_ship_spotter.data.storage import publish_directory
from shadow_ship_spotter.paths import RAW_DIR

XVIEW3_DIR = RAW_DIR / "xview3"


def parse_aria2_list(path: Path) -> dict[str, tuple[str, str | None]]:
    """Return {scene_id: (url, sha1)} from an aria2 input file."""
    out: dict[str, tuple[str, str | None]] = {}
    url = None
    for line in path.read_text().splitlines():
        if line.startswith("http"):
            url = line.strip()
            scene = re.search(r"/([0-9a-f]{16}[tvp])\.tar\.gz", url)
            if scene:
                out[scene.group(1)] = (url, None)
        elif url and "checksum=sha-1=" in line:
            sid = re.search(r"/([0-9a-f]{16}[tvp])\.tar\.gz", url)
            if sid:
                out[sid.group(1)] = (url, line.split("checksum=sha-1=")[1].strip())
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--list", required=True, help="link list file name inside data/raw/xview3/")
    ap.add_argument("--scenes", nargs="+", required=True)
    ap.add_argument(
        "--keep-archives",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="retain verified raw archives (default)",
    )
    args = ap.parse_args()

    links = parse_aria2_list(XVIEW3_DIR / args.list)
    for sid in args.scenes:
        if sid not in links:
            sys.exit(f"{sid} not in {args.list}")
    for sid in args.scenes:
        url, sha1 = links[sid]
        out_dir = XVIEW3_DIR / "scenes" / sid

        def complete(root: Path, scene: str = sid) -> bool:
            d = root / scene if (root / scene).is_dir() else root
            return all(
                (d / name).is_file() and (d / name).stat().st_size > 0
                for name in (
                    "VV_dB.tif",
                    "VH_dB.tif",
                    "bathymetry.tif",
                    "owiMask.tif",
                    "owiWindSpeed.tif",
                    "owiWindDirection.tif",
                    "owiWindQuality.tif",
                )
            )

        if out_dir.exists() and complete(out_dir):
            print(f"[{sid}] already extracted, skipping", file=sys.stderr)
            continue
        archive = XVIEW3_DIR / "archives" / f"{sid}.tar.gz"
        print(f"[{sid}] downloading", file=sys.stderr)
        if not sha1 or not re.fullmatch(r"[0-9a-f]{40}", sha1):
            sys.exit(f"[{sid}] missing or invalid publisher SHA-1")
        download(url, archive, checksum=("sha1", sha1))
        with tarfile.open(archive) as tf:
            publish_directory(
                out_dir, lambda stage, tf=tf: tf.extractall(stage, filter="data"), complete
            )
        if not args.keep_archives:
            archive.unlink(missing_ok=True)
        print(f"[{sid}] done -> {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
