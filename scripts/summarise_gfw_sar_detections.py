"""Extract the South China Sea subset of GFW's SAR vessel detections (Paolo et al. 2024) and
summarise it per Sentinel-1 scene, to find candidate dates/areas for the map demo.

Usage (after `scripts/download_gfw_paolo2024.py --with-detections`):
    uv run python -I scripts/summarise_gfw_sar_detections.py

IMPORTANT: these rows are GFW *model predictions* (detection + length + fishing score) joined to
AIS by GFW's matching algorithm. They are neither human ground truth nor raw AIS positions.
"matched_*" rows imply an AIS-broadcasting vessel was matched at acquisition time; "unmatched"
means GFW's process found no AIS match (not proof of AIS disabling or illegality).

Outputs:
    data/processed/gfw_sar_detections_scs.parquet     all SCS-box rows (git-ignored)
    data/inventory/gfw_sar_scs_scenes.csv             per-scene counts (tracked, small)
    data/inventory/gfw_sar_detections_summary.json    global + SCS summary (tracked)
"""

from __future__ import annotations

import json
import zipfile

import pandas as pd
import polars as pl

from shadow_ship_spotter.paths import INVENTORY_DIR, PROCESSED_DIR, RAW_DIR

ZIP = RAW_DIR / "gfw_paolo2024" / "analysis" / "industrial_vessels_v20240102.csv.zip"
SCS_BOX = (105.0, 0.0, 122.0, 25.0)  # lon_min, lat_min, lon_max, lat_max (rough, includes coasts)


def main() -> None:
    with zipfile.ZipFile(ZIP) as zf:
        members = [m for m in zf.infolist() if m.filename.endswith(".csv")]
        assert len(members) == 1, members
        member = members[0]
        lo, la, hi, ha = SCS_BOX
        parts, n_total, cats, years = [], 0, {}, {}
        tmin, tmax, columns = None, None, None
        with zf.open(member) as fh:
            for chunk in pd.read_csv(fh, chunksize=2_000_000, low_memory=False):
                columns = list(chunk.columns)
                n_total += len(chunk)
                for k, v in chunk.matched_category.value_counts(dropna=False).items():
                    cats[str(k)] = cats.get(str(k), 0) + int(v)
                ts = pd.to_datetime(chunk.timestamp, utc=True, format="mixed")
                for k, v in ts.dt.year.value_counts().items():
                    years[int(k)] = years.get(int(k), 0) + int(v)
                tmin = min(filter(None, [tmin, ts.min()]))
                tmax = max(filter(None, [tmax, ts.max()]))
                sel = chunk[chunk.lon.between(lo, hi) & chunk.lat.between(la, ha)]
                parts.append(sel)
    scs = pd.concat(parts, ignore_index=True)
    scs["timestamp"] = pd.to_datetime(scs.timestamp, utc=True, format="mixed")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(scs).write_parquet(PROCESSED_DIR / "gfw_sar_detections_scs.parquet")

    g = scs.groupby("scene_id")
    scenes = g.agg(
        timestamp=("timestamp", "min"),
        timestamp_max=("timestamp", "max"),
        n=("scene_id", "size"),
        lat_min=("lat", "min"),
        lat_max=("lat", "max"),
        lon_min=("lon", "min"),
        lon_max=("lon", "max"),
    )
    cat_counts = scs.pivot_table(
        index="scene_id", columns="matched_category", values="lat", aggfunc="size", fill_value=0
    )
    scenes = scenes.join(cat_counts).reset_index().sort_values("timestamp")
    scenes["unmatched_fraction"] = (scenes.get("unmatched", 0) / scenes.n).round(3)
    scenes["likely_fishing_unmatched"] = (
        scs[(scs.matched_category == "unmatched") & (scs.fishing_score >= 0.9)]
        .groupby("scene_id")
        .size()
        .reindex(scenes.scene_id)
        .fillna(0)
        .astype(int)
        .values
    )
    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    scenes.to_csv(INVENTORY_DIR / "gfw_sar_scs_scenes.csv", index=False)

    summary = {
        "source": f"{ZIP.name} / {member.filename}",
        "columns": columns,
        "global_rows": n_total,
        "global_matched_category": cats,
        "global_rows_by_year": dict(sorted(years.items())),
        "global_time_range": [str(tmin), str(tmax)],
        "scs_box": SCS_BOX,
        "scs_rows": int(len(scs)),
        "scs_scenes": int(scenes.shape[0]),
        "scs_matched_category": scs.matched_category.value_counts().to_dict(),
        "scs_rows_by_year": scs.timestamp.dt.year.value_counts().sort_index().to_dict(),
        "scs_scenes_by_year": scenes.timestamp.dt.year.value_counts().sort_index().to_dict(),
        "scs_null_fraction": scs.isna().mean().round(4).to_dict(),
        "scs_scene_duration_s_max": float(
            (scenes.timestamp_max - scenes.timestamp).dt.total_seconds().max()
        ),
        "scs_top_scenes_by_unmatched": scenes.sort_values("unmatched", ascending=False)
        .head(10)[
            ["scene_id", "timestamp", "n", "unmatched", "lat_min", "lat_max", "lon_min", "lon_max"]
        ]
        .astype(str)
        .to_dict("records"),
    }
    (INVENTORY_DIR / "gfw_sar_detections_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "scs_top_scenes_by_unmatched"},
            indent=1,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
