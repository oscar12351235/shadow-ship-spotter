# Data directory

This folder holds everything the project knows about its data:
- a registry of every source;
- small machine-readable inventories produced by our validation scripts;
- the pinned pilot training manifest and partition policy;
- the large raw and processed files, which are git-ignored.

What each *source* is and whether it is useful is explained in `context.md` §5 and
`docs/data_sources.md`. This file explains the **folders and files**, and **how to recreate them**.

**What is in Git and what is not:**
- **Tracked (small):** this README, `sources.json`, `loading.toml`, `inventory/`, `splits/`.
- **Never committed:** `raw/` and `processed/`. They are large, and several sources (xView3,
  LSEG) forbid redistribution.

## Layout, with what each item is

```
data/
├── sources.json     Registry of every data source: URL, licence, citation, size, checksum,
│                    download date, status, and the command that reproduces it.
├── inventory/       Inventories and check results written by scripts/validate_*.py (tracked).
├── loading.toml     Offline-default provider order, required inputs and pinned Workspace runs.
├── splits/          training-v1.json pins inputs, partition assignments and seed.
├── raw/             Original downloads and extracted archives (git-ignored, ≈ 16 GB)
│   ├── ssdd/
│   │   ├── download/Official-SSDD-OPEN.rar      original 1 GB archive (SHA-256 in sources.json)
│   │   └── extracted/Official-SSDD-OPEN/        same 1,160 images with 4 label types:
│   │       BBox_SSDD (boxes, used), RBox_SSDD (rotated boxes), PSeg_SSDD (outlines), combined.
│   │       Folders named *_GT* have labels drawn on the pixels: never train on them.
│   ├── xview3/                                   needs a personal login (see below)
│   │   ├── validation.csv          human-reviewed object labels, 50 validation scenes (best labels)
│   │   ├── train.csv               AIS-only labels, 554 train scenes, no boxes
│   │   ├── ESA_xView3_sceneName_mapping.csv   xView3 scene id → ESA product name (= time)
│   │   ├── GRD_train.csv, GRD_validation.csv  SARFish copies of the labels (original ESA grid;
│   │   │                                      only usable with SARFish imagery)
│   │   ├── validation.tar          gzip of 50 coastline arrays used by the xView3 metric
│   │   │                           (not extracted)
│   │   ├── tiny.txt, validation.txt, train.txt  personal signed download links, which EXPIRE.
│   │   │                                        NEVER commit or share.
│   │   ├── archives/<scene>.tar.gz              original scene archives (SHA-1 verified;
│   │   │                                        deletable)
│   │   └── scenes/<scene>/<scene>/              the image rasters of each downloaded scene:
│   │       VV_dB.tif, VH_dB.tif   radar brightness in dB, 10 m pixels (main model input)
│   │       bathymetry.tif         sea depth / land height, 500 m
│   │       owiMask.tif            land/ice/valid mask, 500 m
│   │       owiWind{Speed,Direction,Quality}.tif   surface wind, 500 m
│   ├── gfw_paolo2024/                            Global Fishing Watch paper data (CC BY 4.0)
│   │   ├── training/detection_tiles.zip (+ _extracted/)  11,965 Sentinel-1 patches,
│   │   │                                                  vessel / not vessel
│   │   ├── analysis/industrial_vessels_v20240102.csv.zip 23 M detections by GFW's models
│   │   │                                                  with GFW's AIS matching
│   │   ├── */README.md                                    GFW's own file descriptions
│   │   └── manifest.json                                  what was downloaded + MD5 checks
│   ├── planetary_computer/<item>/                ~30 km window of a 2019 Sentinel-1 image off
│   │   window_vv.tif, window_vh.tif              Hainan (raw, uncalibrated values), plus
│   │   window_meta.json, item.json               window position and catalogue metadata
│   └── lseg/                                     LSEG Workspace samples (licensed, NEVER commit)
│       ├── probe_<UTC>/assessment.json           all results of one probe run
│       ├── probe_<UTC>/*.csv                     resolved ids, positions, area snapshot,
│       │                                         request log
│       └── assessment_latest.json                copy of the latest run's assessment
└── processed/       Files generated from raw data (git-ignored, ≈ 70 MB)
    ├── cache/pc-windows.sqlite3          verified native windows, GCPs and receipts
    ├── pc_windows/<ESA>/<window>/        georeferenced TIFF exports from the preview script
    ├── ssdd_overlays/*.png              52 SSDD images with COCO (green) / VOC (red) boxes
    ├── xview3_labels_downloaded.csv     row-level xView3 labels of the 3 scenes with our checks
    │                                    (never commit: licence)
    ├── gfw_sar_detections_scs.parquet   all GFW detections in the South China Sea box
    │                                    (1.8 M rows)
    └── gfw_scenes/<ESA scene>.parquet   GFW detections of a single scene (cached by the LSEG probe)
```

## Inventories (`data/inventory/`, tracked)

These are small files that let anyone check the data without downloading it. They are also read
by the notebook.

| File | Rows | What it contains | Used for |
|---|---|---|---|
| `ssdd_images.csv` | 1,160 | One row per SSDD image: id, path, official split, inshore/offshore, size, colour mode, whether the 3 channels are identical, MD5 and perceptual hash, box counts (COCO and VOC). Empty columns for metadata SSDD lacks (parent scene, sensor, time, lat/lon). | Duplicate detection, split building, filtering false-colour images |
| `ssdd_boxes.csv` | 2,587 | One row per box: COCO box, matching VOC box, their overlap (IoU), validity flags | Confirming label consistency |
| `ssdd_validation.json` | — | Every SSDD check result, including the list of duplicate groups | Split rules |
| `xview3_scenes.csv` | 3 | The downloaded scenes: ESA name, acquisition start/stop, projection, size, bounds, label counts | Knowing what we have locally |
| `xview3_label_files.json` | — | Aggregate statistics of `train.csv` and `validation.csv`: rows, scenes, missing values, categories. No row-level data, for licence reasons. | Understanding label quality |
| `xview3_validation.json` | — | Per-scene check results (labels inside the image, position error, box validity) | Evidence that labels and images line up |
| `gfw_detection_tiles.csv` | 11,965 | One row per GFW tile: source scene, acquisition time, position, vessel/non-vessel, length, GFW partition membership | Scene-grouped splits for the classifier |
| `gfw_detection_tiles_validation.json` | — | GFW tile check results | — |
| `gfw_sar_scs_scenes.csv` | 17,529 | One row per Sentinel-1 scene in the SCS: GFW detection counts by match category, unmatched fraction | **Choosing demo dates and areas** |
| `gfw_sar_detections_summary.json` | — | Global and SCS summary of the GFW detections table | Context numbers |

## Reproduce

Use the [data-layer guide](../docs/data_layer.md) to assemble samples and review a dated scene
after acquisition. The original `raw/planetary_computer` crop is preserved. New preview exports
use acquisition and window identities under `processed/pc_windows`.

Run these from the repository root, after `./install.sh` or `install.bat`.

```bash
# 1. SSDD (public, ~1 GB, Google Drive) -> download, sha256 check, extract (needs libarchive tar,
#    present on macOS and Windows 10+; otherwise unar/unrar/7z)
uv run python scripts/download_ssdd.py
uv run python -I scripts/validate_ssdd.py

# 2. xView3 (account needed): log in at https://iuu.xview.us/, open "Download the data" inside the
#    app (deep links 404), accept the terms, save train.csv, validation.csv,
#    ESA_xView3_sceneName_mapping.csv and the link lists (validation.txt, tiny.txt, ...) into
#    data/raw/xview3/. Links expire after hours.
shasum -a 1 data/raw/xview3/*.csv     # compare with data/sources.json -> xview3.files_sha1_official
uv run python -I scripts/download_xview3_scenes.py --list validation.txt \
    --scenes b1844cde847a3942v fc2f57371370c521v fe6a8d80fb5ebb8ev --keep-archives
uv run python -I scripts/validate_xview3.py

# 3. GFW / Paolo et al. 2024 figshare files (public, CC BY 4.0; 143 MB, +1.7 GB with flag)
uv run python -I scripts/download_gfw_paolo2024.py --with-detections
uv run python -I scripts/validate_gfw_tiles.py
uv run python -I scripts/summarise_gfw_sar_detections.py

# 4. Planetary Computer feasibility window (anonymous, ~11 MB)
uv run python -I scripts/fetch_pc_s1_window.py \
    --scene S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE \
    --lat 18.45 --lon 110.45 --size 3072

# 5. LSEG Workspace vessel-data probe (needs Workspace desktop running + logged in, and
#    EIKON_APP_KEY in the git-ignored .env; ~62 requests of the 10,000/day quota, ~10 MB)
uv run python -I scripts/probe_lseg_shipping.py
```

`-I` (isolated mode) is used whenever Python reads downloaded files, so that nothing in the
current directory can shadow standard modules.

**Disk use** after all steps (2026-11-23):
- raw ≈ 16 GB: xView3 12 GB (including the kept archives), SSDD 2.1 GB, GFW 1.9 GB;
- processed ≈ 70 MB.

Deleting `data/raw/xview3/archives/` frees 3.9 GB.
