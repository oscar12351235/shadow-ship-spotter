"""Proof of access for the "Reveal hidden vessels" route: read a small window of a Sentinel-1
GRD scene from Microsoft Planetary Computer (anonymous SAS token, cloud-optimised GeoTIFF range
reads; no full-scene download) and overlay GFW's AIS-matched / unmatched SAR detections for the
*same scene* (same acquisition timestamp).

Usage:
    uv run python -I scripts/fetch_pc_s1_window.py \
        --scene S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE \
        --lat 18.62 --lon 109.84 --size 2048

Writes data/raw/planetary_computer/<pc_item_id>/window_{vv,vh}.tif (+ item.json without tokens)
and docs/figures/scs_reveal_feasibility.png. GRD rasters are in radar geometry: lat/lon <-> pixel
uses the product GCPs (accuracy tens of metres; fine for a feasibility check, not for matching).
Pixel values are uncalibrated digital numbers (DN); dB here is 10*log10(DN^2) for display only.
"""

from __future__ import annotations

import argparse
import json
import urllib.request

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
import rasterio  # noqa: E402
from rasterio.transform import GCPTransformer  # noqa: E402
from rasterio.windows import Window  # noqa: E402

from shadow_ship_spotter.data.download import USER_AGENT  # noqa: E402
from shadow_ship_spotter.paths import FIGURES_DIR, PROCESSED_DIR, RAW_DIR  # noqa: E402

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-grd"
COLOURS = {
    "matched_fishing": "#1f77b4",
    "matched_nonfishing": "#17becf",
    "matched_unknown": "#9467bd",
    "unmatched": "#ff7f0e",
}


def get_json(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body else None
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    return json.load(
        urllib.request.urlopen(urllib.request.Request(url, data, headers), timeout=60)
    )  # noqa: S310


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scene", required=True, help="full ESA product name (as in GFW scene_id)")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--size", type=int, default=2048, help="window size in pixels")
    a = ap.parse_args()

    pc_id = "_".join(a.scene.split("_")[:8])  # PC ids drop the 4-char product unique id
    item = get_json(f"{STAC}/search", {"collections": ["sentinel-1-grd"], "ids": [pc_id]})[
        "features"
    ]
    if not item:
        raise SystemExit(f"{pc_id} not found on Planetary Computer")
    item = item[0]
    token = get_json(SAS)["token"]
    out = RAW_DIR / "planetary_computer" / pc_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "item.json").write_text(json.dumps(item, indent=2))  # hrefs are unsigned

    chips, meta = {}, {}
    for pol in ("vv", "vh"):
        href = f"{item['assets'][pol]['href']}?{token}"
        with rasterio.open(href) as src:
            gcps, gcp_crs = src.gcps
            tr = GCPTransformer(gcps)
            row, col = tr.rowcol(a.lon, a.lat)
            win = Window(col - a.size // 2, row - a.size // 2, a.size, a.size)
            data = src.read(1, window=win, boundless=True, fill_value=0)
            meta[pol] = {
                "shape": src.shape,
                "dtype": src.dtypes[0],
                "gcps": len(gcps),
                "gcp_crs": str(gcp_crs),
                "window": [int(win.col_off), int(win.row_off), a.size, a.size],
            }
            prof = {
                "driver": "GTiff",
                "height": a.size,
                "width": a.size,
                "count": 1,
                "dtype": src.dtypes[0],
                "compress": "deflate",
            }
            with rasterio.open(out / f"window_{pol}.tif", "w", **prof) as dst:
                dst.write(data, 1)
                dst.update_tags(
                    source=item["id"],
                    window=json.dumps(meta[pol]["window"]),
                    note="radar geometry; use item GCPs for geolocation",
                )
            chips[pol] = data.astype(float)
    (out / "window_meta.json").write_text(json.dumps(meta, indent=2))

    det = (
        pl.read_parquet(PROCESSED_DIR / "gfw_sar_detections_scs.parquet")
        .filter(pl.col("scene_id") == a.scene)
        .to_pandas()
    )
    rows, cols = tr.rowcol(det.lon.to_numpy(), det.lat.to_numpy())
    det["r"] = np.asarray(rows) - meta["vv"]["window"][1]
    det["c"] = np.asarray(cols) - meta["vv"]["window"][0]
    inwin = det[(det.r >= 0) & (det.r < a.size) & (det.c >= 0) & (det.c < a.size)]

    fig, axes = plt.subplots(1, 2, figsize=(16, 8.4))
    for ax, pol in zip(axes, ("vv", "vh"), strict=True):
        db = 10 * np.log10(np.maximum(chips[pol], 1) ** 2)
        ax.imshow(db, cmap="gray", vmin=np.percentile(db, 2), vmax=np.percentile(db, 99.7))
        for cat, colr in COLOURS.items():
            s = inwin[inwin.matched_category == cat]
            ax.scatter(
                s.c,
                s.r,
                s=60,
                facecolors="none",
                edgecolors=colr,
                lw=1.2,
                label=f"{cat} ({len(s)})",
            )
        ax.set_title(f"{pol.upper()} (DN→dB, display only)", fontsize=9)
        ax.axis("off")
    axes[0].legend(fontsize=8, loc="lower left")
    fig.suptitle(
        f"Feasibility: Planetary Computer window of {a.scene}\n"
        f"acquired {item['properties']['datetime']} around {a.lat:.2f}N {a.lon:.2f}E  |  circles = "
        "GFW SAR detections for this scene (GFW model output + GFW AIS matching; NOT ground truth, "
        "NOT raw AIS)",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "scs_reveal_feasibility.png", dpi=90)
    print(
        json.dumps(
            {
                "pc_item": item["id"],
                "datetime": item["properties"]["datetime"],
                "meta": meta,
                "gfw_detections_in_scene": len(det),
                "gfw_detections_in_window": len(inwin),
                "in_window_by_category": inwin.matched_category.value_counts().to_dict(),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
