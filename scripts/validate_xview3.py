"""Validate downloaded xView3-SAR scenes against their labels and build an inventory.

Usage (after the label CSVs are in data/raw/xview3/ and scenes were fetched with
scripts/download_xview3_scenes.py):
    uv run python -I scripts/validate_xview3.py

Checks per scene: rasters open; VV/VH share grid/CRS; nodata fraction; every label's
(detect_scene_row, detect_scene_column) lies inside the raster and, converted through the
raster geotransform, lands on (detect_lat, detect_lon) (great-circle error reported in metres);
label boxes (top/left/bottom/right) are ordered, in-bounds and contain the point.
Label-file checks (all scenes): columns, nulls, duplicates, partition sizes, value counts.

Outputs:
    data/inventory/xview3_scenes.csv            downloaded scenes (+ acquisition times)
    data/processed/xview3_labels_downloaded.csv labels of downloaded scenes + derived checks
                                                (git-ignored: xView3 terms forbid redistribution)
    data/inventory/xview3_label_files.json      label-file level summary (all scenes)
    data/inventory/xview3_validation.json       per-scene check results
    docs/figures/xview3_<scene>_overlay.png     overview + labelled crops per scene
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.windows import Window  # noqa: E402

from shadow_ship_spotter.paths import (  # noqa: E402
    FIGURES_DIR,
    INVENTORY_DIR,
    PROCESSED_DIR,
    RAW_DIR,
)

X3 = RAW_DIR / "xview3"
LABEL_FILES = {"train": "train.csv", "validation": "validation.csv"}
CLASS_COLOURS = {"fishing": "orange", "vessel": "lime", "non-vessel": "cyan", "unknown": "magenta"}


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6_371_008.8
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def label_class(r) -> str:
    if r.is_vessel is True and r.is_fishing is True:
        return "fishing"
    if r.is_vessel is True:
        return "vessel"
    if r.is_vessel is False:
        return "non-vessel"
    return "unknown"


def scene_dir(sid: str):
    d = X3 / "scenes" / sid
    return d / sid if (d / sid).is_dir() else d


def summarise_label_files() -> tuple[dict, pd.DataFrame]:
    out, frames = {}, []
    for part, fn in LABEL_FILES.items():
        df = pd.read_csv(X3 / fn, dtype={"scene_id": str})
        df["partition"] = part
        frames.append(df)
        out[part] = {
            "file": fn,
            "rows": len(df),
            "scenes": int(df.scene_id.nunique()),
            "columns": list(df.columns[:-1]),
            "null_fraction": df.isna().mean().round(4).to_dict(),
            "duplicate_detect_ids": int(df.detect_id.duplicated().sum()),
            "is_vessel": df.is_vessel.value_counts(dropna=False).astype(int).to_dict(),
            "is_fishing": df.is_fishing.value_counts(dropna=False).astype(int).to_dict(),
            "confidence": df.confidence.value_counts(dropna=False).to_dict(),
            "source": df.source.value_counts(dropna=False).to_dict(),
            "vessel_length_m_available": int(df.vessel_length_m.notna().sum()),
            "distance_from_shore_km_9999_sentinel": int((df.distance_from_shore_km > 9000).sum()),
        }
    mapping = pd.read_csv(X3 / "ESA_xView3_sceneName_mapping.csv")
    out["scene_mapping"] = {
        "rows": len(mapping),
        "by_partition": mapping.DATA_PARTITION.value_counts().to_dict(),
    }
    out["raw_ais_tracks_in_labels"] = False
    out["timestamp_column_in_labels"] = False
    return out, pd.concat(frames, ignore_index=True)


def main() -> None:
    label_summary, labels = summarise_label_files()
    labels["is_vessel"] = labels.is_vessel.map(
        {True: True, False: False, "True": True, "False": False}
    )
    labels["is_fishing"] = labels.is_fishing.map(
        {True: True, False: False, "True": True, "False": False}
    )
    mapping = pd.read_csv(X3 / "ESA_xView3_sceneName_mapping.csv").set_index("XVIEW3_SCENENAME")
    scenes = (
        sorted(p.name for p in (X3 / "scenes").iterdir() if p.is_dir())
        if (X3 / "scenes").exists()
        else []
    )

    scene_rows, label_rows, checks = [], [], {}
    for sid in scenes:
        d = scene_dir(sid)
        if not (d / "VV_dB.tif").exists():
            continue
        esa = mapping.ESA_SCENENAME.get(sid, "")
        t0 = pd.to_datetime(esa.split("_")[4], format="%Y%m%dT%H%M%S", utc=True) if esa else pd.NaT
        t1 = pd.to_datetime(esa.split("_")[5], format="%Y%m%dT%H%M%S", utc=True) if esa else pd.NaT
        with rasterio.open(d / "VV_dB.tif") as vv, rasterio.open(d / "VH_dB.tif") as vh:
            same_grid = vv.transform == vh.transform and vv.shape == vh.shape and vv.crs == vh.crs
            ovr = vv.read(
                1, out_shape=(vv.height // 20, vv.width // 20), resampling=Resampling.nearest
            )
            nod = vv.nodata
            nodata_frac = float(
                np.mean(ovr == nod) if nod is not None else np.mean(~np.isfinite(ovr))
            )
            lab = labels[labels.scene_id == sid].copy()
            rows, cols = lab.detect_scene_row.to_numpy(), lab.detect_scene_column.to_numpy()
            inside = (rows >= 0) & (rows < vv.height) & (cols >= 0) & (cols < vv.width)
            # Verified convention: detect_lat/lon == upper-left corner of (row, col) pixel.
            xs, ys = rasterio.transform.xy(vv.transform, rows, cols, offset="ul")
            if vv.crs and not vv.crs.is_geographic:
                from rasterio.warp import transform as warp

                xs, ys = warp(vv.crs, "EPSG:4326", xs, ys)
            lab["pixel_to_geo_error_m"] = haversine_m(
                lab.detect_lat, lab.detect_lon, np.array(ys), np.array(xs)
            )
            lab["inside_raster"] = inside
            hasbox = lab[["top", "left", "bottom", "right"]].notna().all(axis=1)
            lab["box_ok"] = ~hasbox | (
                (lab.top <= lab.bottom)
                & (lab.left <= lab.right)
                & (lab.top >= 0)
                & (lab.left >= 0)
                & (lab.bottom < vv.height)
                & (lab.right < vv.width)
                & lab.detect_scene_row.between(lab.top, lab.bottom)
                & lab.detect_scene_column.between(lab.left, lab.right)
            )
            lab["class"] = [label_class(r) for r in lab.itertuples()]
            lon0, lat0, lon1, lat1 = rasterio.warp.transform_bounds(vv.crs, "EPSG:4326", *vv.bounds)
            scene_rows.append(
                {
                    "scene_id": sid,
                    "partition": lab.partition.iloc[0] if len(lab) else "",
                    "esa_scene_name": esa,
                    "acquisition_start_utc": t0,
                    "acquisition_stop_utc": t1,
                    "crs": str(vv.crs),
                    "width": vv.width,
                    "height": vv.height,
                    "pixel_size_x": vv.transform.a,
                    "pixel_size_y": vv.transform.e,
                    "dtype": vv.dtypes[0],
                    "nodata": nod,
                    "nodata_fraction_approx": round(nodata_frac, 4),
                    "lon_min": lon0,
                    "lat_min": lat0,
                    "lon_max": lon1,
                    "lat_max": lat1,
                    "n_labels": len(lab),
                    "n_vessel": int((lab.is_vessel == True).sum()),  # noqa: E712
                    "n_fishing": int((lab.is_fishing == True).sum()),  # noqa: E712
                    "n_high_conf": int((lab.confidence == "HIGH").sum()),
                    "vv_vh_same_grid": same_grid,
                    "ancillary_files": ";".join(sorted(p.name for p in d.glob("*.tif"))),
                }
            )
            checks[sid] = {
                "vv_vh_same_grid": same_grid,
                "labels": len(lab),
                "labels_outside_raster": int((~inside).sum()),
                "pixel_to_geo_error_m": lab.pixel_to_geo_error_m.describe().round(2).to_dict(),
                "labels_geo_error_gt_100m": int((lab.pixel_to_geo_error_m > 100).sum()),
                "labels_with_box": int(hasbox.sum()),
                "bad_boxes": int((~lab.box_ok).sum()),
            }
            label_rows.append(lab)

            # ---- overlay figure -----------------------------------------------------
            fig = plt.figure(figsize=(16, 9))
            ax0 = fig.add_axes([0.01, 0.05, 0.36, 0.88])
            show = np.where(ovr == nod, np.nan, ovr) if nod is not None else ovr
            ax0.imshow(
                show, cmap="gray", vmin=np.nanpercentile(show, 2), vmax=np.nanpercentile(show, 99.5)
            )
            for cls, col in CLASS_COLOURS.items():
                s = lab[lab["class"] == cls]
                ax0.scatter(
                    s.detect_scene_column / 20,
                    s.detect_scene_row / 20,
                    s=4,
                    c=col,
                    label=f"{cls} ({len(s)})",
                )
            ax0.legend(fontsize=7, loc="lower right")
            ax0.set_title(f"{sid} VV dB (1/20 res)\n{esa}", fontsize=8)
            ax0.axis("off")
            rng = np.random.default_rng(1)
            pool = lab[
                lab["class"].isin(["fishing", "vessel"]) & lab.box_ok & (lab.confidence == "HIGH")
            ]
            if len(pool) < 4:
                pool = lab
            pick = pool.iloc[rng.choice(len(pool), size=min(4, len(pool)), replace=False)]
            half = 64
            for k, r in enumerate(pick.itertuples()):
                win = Window(
                    r.detect_scene_column - half, r.detect_scene_row - half, 2 * half, 2 * half
                )
                for b, (src, name) in enumerate(((vv, "VV"), (vh, "VH"))):
                    ax = fig.add_axes([0.39 + 0.15 * k, 0.52 - 0.47 * b, 0.14, 0.40])
                    chip = src.read(1, window=win, boundless=True, fill_value=np.nan)
                    ax.imshow(
                        chip,
                        cmap="gray",
                        vmin=np.nanpercentile(chip, 2),
                        vmax=np.nanpercentile(chip, 99.8),
                    )
                    near = lab[
                        (lab.detect_scene_row - r.detect_scene_row).abs().lt(half)
                        & (lab.detect_scene_column - r.detect_scene_column).abs().lt(half)
                    ]
                    for q in near.itertuples():
                        c = CLASS_COLOURS[q[lab.columns.get_loc("class") + 1]]
                        if pd.notna(q.top):
                            ax.add_patch(
                                mpatches.Rectangle(
                                    (
                                        q.left - r.detect_scene_column + half,
                                        q.top - r.detect_scene_row + half,
                                    ),
                                    q.right - q.left + 1,
                                    q.bottom - q.top + 1,
                                    fill=False,
                                    ec=c,
                                    lw=1,
                                )
                            )
                        ax.plot(
                            q.detect_scene_column - r.detect_scene_column + half,
                            q.detect_scene_row - r.detect_scene_row + half,
                            "+",
                            c=c,
                            ms=6,
                        )
                    ax.set_title(
                        f"{name} r{r.detect_scene_row} c{r.detect_scene_column}\n"
                        f"{r._asdict().get('confidence')} {r.source} L={r.vessel_length_m}",
                        fontsize=7,
                    )
                    ax.axis("off")
            fig.suptitle(
                "xView3 labels drawn by us on original VV/VH dB rasters "
                "(orange=fishing, lime=vessel, cyan=non-vessel, magenta=unknown)",
                fontsize=9,
            )
            fig.savefig(FIGURES_DIR / f"xview3_{sid}_overlay.png", dpi=90)
            plt.close(fig)
        print(f"[{sid}] {checks[sid]}")

    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    (INVENTORY_DIR / "xview3_label_files.json").write_text(
        json.dumps(label_summary, indent=2, default=str)
    )
    if scene_rows:
        pd.DataFrame(scene_rows).to_csv(INVENTORY_DIR / "xview3_scenes.csv", index=False)
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        pd.concat(label_rows).to_csv(PROCESSED_DIR / "xview3_labels_downloaded.csv", index=False)
    (INVENTORY_DIR / "xview3_validation.json").write_text(json.dumps(checks, indent=2, default=str))
    print(
        json.dumps(
            {
                k: {
                    kk: vv
                    for kk, vv in v.items()
                    if kk in ("rows", "scenes", "confidence", "source")
                }
                for k, v in label_summary.items()
                if isinstance(v, dict) and "rows" in v
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
