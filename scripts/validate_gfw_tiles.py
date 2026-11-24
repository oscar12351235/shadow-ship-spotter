"""Inventory + validation of the GFW / Paolo et al. (2024) Sentinel-1 detection tiles.

Usage (after scripts/download_gfw_paolo2024.py):
    uv run python -I scripts/validate_gfw_tiles.py

Outputs:
    data/inventory/gfw_detection_tiles.csv        one row per tile (no pixels)
    data/inventory/gfw_detection_tiles_validation.json
    docs/figures/gfw_detection_tiles.png          gallery of vessel / non-vessel tiles

detect_id is "<Sentinel-1 product name>;<lon>;<lat>" (lon first; verified), so the parent
scene and the
acquisition start time are recovered from it. Labels are GFW training labels (presence 1/0),
NOT our annotations; band order and 0-255 scaling are not documented in the release.
"""

from __future__ import annotations

import json
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import zarr  # noqa: E402

from shadow_ship_spotter.paths import FIGURES_DIR, INVENTORY_DIR, RAW_DIR  # noqa: E402

ROOT = RAW_DIR / "gfw_paolo2024" / "training" / "detection_tiles_extracted"
SCS_BOX = (105.0, 0.0, 122.0, 25.0)  # lon_min, lat_min, lon_max, lat_max (rough SCS extent)


def main() -> None:
    z = zarr.open_group(str(ROOT / "detection_tiles_v4.zarr"), mode="r")
    idx = zarr.open_group(str(ROOT / "detection_tiles_v4.zarr.index"), mode="r")
    ids = [str(s) for s in z["detect_id"][:]]
    df = pd.DataFrame(
        {
            "tile_index": np.arange(len(ids)),
            "detect_id": ids,
            "lat": z["detect_lat"][:].astype(float),
            "lon": z["detect_lon"][:].astype(float),
            "presence": z["presence"][:].astype(int),
            "length_m": z["length_m"][:].astype(float),
            "weight": z["weight"][:].astype(float),
        }
    )
    parts = df.detect_id.str.split(";", expand=True)
    df["scene_id"] = parts[0]
    # NB: verified empirically that detect_id is "<scene>;<LON>;<LAT>" (README does not say).
    df["id_lon"] = parts[1].astype(float)
    df["id_lat"] = parts[2].astype(float)
    m = df.scene_id.str.extract(r"^(S1[ABCD])_(\w\w)_(\w{4})_\w{4}_(\d{8}T\d{6})_")
    df["platform"], df["mode"], df["product"] = m[0], m[1], m[2]
    df["acquisition_start_utc"] = pd.to_datetime(m[3], format="%Y%m%dT%H%M%S", utc=True)
    lo, la, hi, ha = SCS_BOX
    df["in_scs_box"] = df.lon.between(lo, hi) & df.lat.between(la, ha)

    # official partition memberships
    for name in ("test/base", "test/null", "train/all/train", "train/all/validation"):
        col = "idx_" + name.replace("/", "_")
        df[col] = False
        df.loc[np.asarray(idx[name][:]), col] = True

    tiles = z["tiles"]
    sample = np.asarray(tiles[::25]).astype(float)  # every 25th tile for range stats
    test_scenes = set(df.loc[df.idx_test_base | df.idx_test_null, "scene_id"])
    train_scenes = set(df.loc[df.idx_train_all_train | df.idx_train_all_validation, "scene_id"])
    tests = {
        "n_tiles": len(df),
        "presence_counts": df.presence.value_counts().to_dict(),
        "duplicate_detect_ids": int(df.detect_id.duplicated().sum()),
        "id_coords_match_arrays_max_abs_deg": float(
            max((df.lat - df.id_lat).abs().max(), (df.lon - df.id_lon).abs().max())
        ),
        "unparsed_scene_ids": int(df.platform.isna().sum()),
        "n_scenes": int(df.scene_id.nunique()),
        "tiles_per_scene": df.scene_id.value_counts().describe().round(2).to_dict(),
        "date_range": [str(df.acquisition_start_utc.min()), str(df.acquisition_start_utc.max())],
        "platforms": df.platform.value_counts().to_dict(),
        "products": df["product"].value_counts().to_dict(),
        "lat_range": [df.lat.min(), df.lat.max()],
        "lon_range": [df.lon.min(), df.lon.max()],
        "tiles_in_scs_box": int(df.in_scs_box.sum()),
        "scs_box": SCS_BOX,
        "length_m_zero_or_missing_positives": int(((df.presence == 1) & ~(df.length_m > 0)).sum()),
        "tile_shape": list(tiles.shape),
        "tile_dtype": str(tiles.dtype),
        "tile_value_range_sampled": [float(sample.min()), float(sample.max())],
        "tile_band_means_sampled": np.nanmean(sample, axis=(0, 1, 2)).round(2).tolist(),
        "tile_nan_sampled": int(np.isnan(sample).sum()),
        "index_sizes": {
            k: int(idx[k].shape[0])
            for k in ("test/base", "test/null", "train/all/train", "train/all/validation")
        },
        "official_train_test_share_scenes": len(test_scenes & train_scenes),
        "n_test_scenes": len(test_scenes),
        "n_train_scenes": len(train_scenes),
    }
    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    df.drop(columns=["id_lat", "id_lon"]).to_csv(
        INVENTORY_DIR / "gfw_detection_tiles.csv", index=False
    )
    (INVENTORY_DIR / "gfw_detection_tiles_validation.json").write_text(
        json.dumps(tests, indent=2, default=str)
    )

    # Gallery: 8 vessels + 8 non-vessels, both bands, centre marked
    rng = np.random.default_rng(0)
    pos = rng.choice(df.index[df.presence == 1], 8, replace=False)
    neg = rng.choice(df.index[df.presence == 0], 8, replace=False)
    fig, axes = plt.subplots(4, 8, figsize=(16, 8.6))
    for col, i in enumerate([*pos, *neg]):
        t = np.asarray(tiles[int(i)]).astype(float)
        r = df.loc[i]
        for b in range(2):
            ax = axes[(col // 8) * 2 + b, col % 8]
            ax.imshow(t[..., b], cmap="gray")
            ax.plot(39.5, 39.5, "+", color="red", ms=8)
            ax.set_axis_off()
            if b == 0:
                lab = f"vessel L={r.length_m:.0f}m" if r.presence else "non-vessel"
                ax.set_title(f"{lab}\n{r.scene_id[17:25]} {r.lat:.1f},{r.lon:.1f}", fontsize=7)
    fig.suptitle(
        "GFW detection tiles (80x80, Sentinel-1). Rows 1-2: presence=1 (band0, band1); "
        "rows 3-4: presence=0. Red + = labelled detection position (tile centre).",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "gfw_detection_tiles.png", dpi=100)
    print(json.dumps(tests, indent=1, default=str))
    # Regex sanity (kept explicit for readers)
    assert all(re.match(r"^S1", s) for s in df.scene_id.head(100))


if __name__ == "__main__":
    main()
