"""Read a PC native-DN window and plot the same-scene historical GFW reference layer.

The original --scene/--lat/--lon/--size interface is supported. Each export has its own
directory, parent-grid offsets, shifted WGS84 GCPs and source receipts. --offline replays
previous exact reads. The optional comparison layer comes from the 2017–2021 publication.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.control import GroundControlPoint  # noqa: E402
from rasterio.transform import GCPTransformer  # noqa: E402

from shadow_ship_spotter.data.contracts import Policy, RasterRequest  # noqa: E402
from shadow_ship_spotter.data.geo import points, window_at  # noqa: E402
from shadow_ship_spotter.data.imagery import RasterResolver  # noqa: E402
from shadow_ship_spotter.data.reference import SCS, load_reference  # noqa: E402
from shadow_ship_spotter.data.storage import (
    publish_directory,
    staged_file,
    write_json,
)  # noqa: E402
from shadow_ship_spotter.data.study import raster_summary  # noqa: E402
from shadow_ship_spotter.paths import DATA_DIR, FIGURES_DIR  # noqa: E402

COLOURS = {
    "matched_fishing": "#1f77b4",
    "matched_nonfishing": "#17becf",
    "matched_unknown": "#9467bd",
    "unmatched": "#ff7f0e",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--figure", type=str, default=str(FIGURES_DIR / "scs_reveal_feasibility.png"))
    a = ap.parse_args()
    policy = Policy.read(DATA_DIR / "loading.toml").model_copy(update={"online": not a.offline})
    resolver = RasterResolver.local(DATA_DIR, policy)
    lookup = resolver.locate(a.scene, "s1-grd-dn")
    if lookup.grid is None:
        raise SystemExit(lookup.model_dump_json())
    grid = lookup.grid
    w = window_at(grid, a.lon, a.lat, a.size)
    result = resolver.resolve(RasterRequest(scene=a.scene, product="s1-grd-dn", window=w))
    chips = result.stack()
    out = DATA_DIR / "processed/pc_windows" / a.scene / f"{w.col}_{w.row}_{w.width}_{w.height}"
    meta = raster_summary(result)

    def export(stage):
        for band, pixels in zip(result.request.bands, chips, strict=True):
            with rasterio.open(
                stage / f"window_{band.lower()}.tif",
                "w",
                driver="GTiff",
                height=w.height,
                width=w.width,
                count=1,
                dtype=pixels.dtype,
                nodata=0,
                compress="deflate",
                gcps=[
                    GroundControlPoint(row=r - w.row, col=c - w.col, x=x, y=y, z=z)
                    for r, c, x, y, z in grid.gcps
                ],
                crs=grid.crs,
            ) as dst:
                dst.write(pixels.filled(0), 1)
        write_json(stage / "window_meta.json", meta)

    publish_directory(
        out,
        export,
        lambda d: all(
            (d / n).is_file() for n in ("window_vv.tif", "window_vh.tif", "window_meta.json")
        ),
    )
    ref = load_reference(DATA_DIR, a.scene, SCS)
    detections = ref.predictions
    if detections:
        with GCPTransformer(points(grid)) as transform:
            rows, cols = transform.rowcol([d.lon for d in detections], [d.lat for d in detections])
        xy = [
            (c - w.col, r - w.row, d.matched_category)
            for c, r, d in zip(cols, rows, detections, strict=True)
            if w.col <= c < w.right and w.row <= r < w.bottom
        ]
    else:
        xy = []
    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    for ax, band, pixels in zip(axes, result.request.bands, chips, strict=True):
        db = 20 * np.ma.log10(pixels.astype(float))
        vals = db.compressed()
        if vals.size:
            ax.imshow(db, cmap="gray", vmin=np.percentile(vals, 2), vmax=np.percentile(vals, 99.7))
        for category, colour in COLOURS.items():
            pts = [(x, y) for x, y, cat in xy if cat == category]
            if pts:
                xs, ys = zip(*pts, strict=True)
                ax.scatter(xs, ys, facecolors="none", edgecolors=colour, s=40, label=category)
        ax.set_title(f"{band} log-amplitude display")
        ax.axis("off")
    if xy:
        axes[0].legend()
    fig.suptitle(f"{a.scene}\nGFW published predictions and matching ({ref.state})")
    with staged_file(Path(a.figure)) as stage:
        fig.savefig(stage, format="png", dpi=90)
    plt.close(fig)
    print(
        json.dumps(
            dict(
                export=str(out),
                reference_state=ref.state,
                published_detections_in_window=len(xy),
                raster=meta,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
