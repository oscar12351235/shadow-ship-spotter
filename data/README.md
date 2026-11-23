# Data directory

Large data never goes into Git. Tracked here: this README, `sources.json`, `inventory/`, `splits/`.

```
data/
├── sources.json            registry: URLs, licences, citations, sizes, checksums, status
├── inventory/              machine-readable inventories + validation reports (tracked, small)
├── splits/                 partition assignments (none finalised yet; see splits/README.md)
├── raw/                    original downloads and extracted archives (git-ignored)
│   ├── ssdd/download/Official-SSDD-OPEN.rar
│   ├── ssdd/extracted/Official-SSDD-OPEN/{BBox_SSDD,RBox_SSDD,PSeg_SSDD,BBox_RBox_PSeg_SSDD}/
│   ├── xview3/{train,validation,ESA_xView3_sceneName_mapping,GRD_train,GRD_validation}.csv (login)
│   ├── xview3/validation.tar                   = shoreline/validation.tar.gz (50 .npy; not extracted)
│   ├── xview3/{tiny,validation,train}.txt       personal signed links — NEVER commit/share
│   ├── xview3/archives/<scene>.tar.gz          original scene archives (SHA-1 verified)
│   ├── xview3/scenes/<scene>/<scene>/{VV_dB,VH_dB,bathymetry,owi*}.tif
│   ├── gfw_paolo2024/{training,analysis}/…     figshare files + manifest.json (MD5 verified)
│   └── planetary_computer/<item>/window_{vv,vh}.tif, item.json
└── processed/              generated artefacts (git-ignored)
    ├── ssdd_overlays/*.png
    ├── xview3_labels_downloaded.csv   (row-level xView3 labels: never commit, licence terms)
    └── gfw_sar_detections_scs.parquet
```

## Reproduce (from the repository root, after `./install.sh` or `install.bat`)

```bash
# 1. SSDD (public, ~1 GB, Google Drive) -> download, sha256 check, extract (needs libarchive tar,
#    present on macOS and Windows 10+; otherwise unar/unrar/7z)
uv run python scripts/download_ssdd.py
uv run python -I scripts/validate_ssdd.py

# 2. xView3 (account needed): log in at https://iuu.xview.us/, open "Download the data",
#    accept the terms, save train.csv, validation.csv, ESA_xView3_sceneName_mapping.csv and the
#    link lists (validation.txt, tiny.txt, ...) into data/raw/xview3/. Links expire after hours.
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
```

`-I` (isolated mode) is used when Python reads downloaded files so that nothing in the current
directory can shadow standard modules.

Disk use after all steps (2026-11-23): raw ≈ 16 GB (xView3 12 GB incl. kept archives, SSDD 2.1 GB,
GFW 1.9 GB), processed ≈ 70 MB. Deleting `data/raw/xview3/archives/` frees 3.9 GB.

## Inventories (`data/inventory/`)

| File | Rows | Content |
|---|---|---|
| `ssdd_images.csv` | 1,160 | image id, path, official split, inshore/offshore, size, mode, channel check, md5, dhash, box counts (COCO/VOC); empty columns for metadata SSDD lacks (parent scene, sensor, time, lat/lon) |
| `ssdd_boxes.csv` | 2,587 | COCO box + matched VOC box + IoU, validity flags |
| `ssdd_validation.json` | — | all SSDD checks incl. duplicate groups |
| `xview3_scenes.csv` | 3 | downloaded scenes: ESA name, acquisition start/stop, CRS, size, bounds, label counts |
| `xview3_label_files.json`, `xview3_validation.json` | — | label-file stats; per-scene checks |
| `gfw_detection_tiles.csv` | 11,965 | tile index, parent scene, acquisition time, lat/lon, presence, length, GFW partitions |
| `gfw_sar_scs_scenes.csv` | 17,529 | per-scene counts of GFW SAR detections in the SCS box by match category |
| `gfw_sar_detections_summary.json` | — | global + SCS summary of the GFW detections table |
