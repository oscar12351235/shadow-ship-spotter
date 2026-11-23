# Data sources: access status, selection and limitations

_Status as verified on 2026-11-23. Machine-readable registry: [`data/sources.json`](../data/sources.json).
Validation numbers: [`docs/validation_results.md`](validation_results.md). Map/reveal assessment:
[`docs/map_reveal_data_assessment.md`](map_reveal_data_assessment.md)._

## 0. Three distinct data needs

| Need | What it requires | Sources that satisfy it |
|---|---|---|
| **A. Model training & evaluation** | Radar images + vessel-location annotations | xView3-SAR ✅, SSDD ✅, GFW detection tiles ✅ (classifier stage only) |
| **B. Initial AIS map** | Vessel positions with timestamps over the area/time | DMA raw AIS (Danish waters only) 📍; GFW API (token, SCS) 📍; GFW SAR table gives *only AIS-matched detections*, not an AIS feed ✅ |
| **C. Reveal operation** | Georeferenced SAR scenes + acquisition time + compatible AIS | Planetary Computer S1 GRD ✅ (anonymous), CDSE ✅ catalogue / 📍 download (account), GFW SAR table ✅ as comparison layer |

✅ downloaded and validated (or access proven by an actual read) · 📍 located, access route
verified, not downloaded · ❌ unavailable / unverified.

## 1. xView3-SAR (preferred source) — ✅ labels + 3 scenes downloaded and validated

- **Source**: https://iuu.xview.us/ (DIU / Global Fishing Watch). Paper: Paolo et al., *xView3-SAR:
  Detecting Dark Fishing Activity Using Synthetic Aperture Radar Imagery*, NeurIPS 2022 Datasets &
  Benchmarks. Reference code: https://github.com/DIUx-xView/xview3-reference (last push 2022-08;
  no open issue about downloads).
- **Licence**: CC BY-NC-SA 4.0 ("contains modified Copernicus Sentinel data (2020)"). Non-commercial;
  do not redistribute download links (site terms).
  We therefore do **not** commit row-level labels (they go to git-ignored `data/processed/`);
  tracked xView3 artefacts are aggregate statistics and the overlay figures
  `docs/figures/xview3_*` (derived works, CC BY-NC-SA 4.0, attribution: xView3 / DIU / GFW).
- **Access (verified)**: the site is a Nuxt single-page app (static build 2023-09-29). Deep links
  such as `/signup` or `/download-links` return HTTP 404 when requested directly *by URL* because
  the server has no route for them (client-side routing). In-app navigation evidently works: a
  team member logged in and reached the download page on 2026-11-23. Direct deep links are the
  most likely cause of the "error pages" seen previously. Login uses AWS Cognito; after login the
  download page fetches per-user signed links from an AWS API Gateway. Label CSVs are direct
  downloads; imagery comes as per-scene `.tar.gz` with signed links valid a few hours (aria2 lists).
  **A team member logged in on 2026-11-23** and saved the label CSVs + link lists into
  `data/raw/xview3/` (git-ignored).
- **Partitions**: train 554 scenes (labels AIS-derived only), validation 50 scenes
  (human-reviewed), public 150 scenes (labels released after challenge), "tiny" = 7 scenes.
- **Downloaded**: `train.csv`, `validation.csv`, `ESA_xView3_sceneName_mapping.csv`,
  `GRD_train.csv` (SARFish) — all SHA-1 identical to the values published on the download page.
  Scenes (validation): `b1844cde847a3942v` (Lagos, NG, 2020-01-26 05:29:56Z), `fc2f57371370c521v`
  (North Sea/DK, 2020-09-28 17:18:00Z), `fe6a8d80fb5ebb8ev` (Adriatic, 2020-05-20 05:11:17Z).
  Archives 1.26–1.49 GB each, SHA-1 verified; ~2.5 GB per scene unpacked; full validation set
  would be ~123 GB.
- **Scene contents**: `VV_dB.tif`, `VH_dB.tif` (float16, dB, nodata −32768, 10 m pixels, UTM
  projection — e.g. EPSG:32631/32632/32633), plus coarse ancillary `bathymetry.tif`,
  `owiMask.tif`, `owiWindSpeed.tif`, `owiWindDirection.tif`, `owiWindQuality.tif`.
  ~28k × 24k pixels per scene.
- **Label fields**: `detect_lat, detect_lon, detect_scene_row, detect_scene_column, top, left,
  bottom, right, vessel_length_m, is_vessel, is_fishing, distance_from_shore_km, confidence
  (HIGH/MEDIUM/LOW), source (ais / manual / ais/manual), scene_id, detect_id`.
  - **No timestamps and no raw AIS tracks** in labels. Acquisition times come from the ESA product
    name via `ESA_xView3_sceneName_mapping.csv` (start/stop to the second).
  - **Pixel convention (verified)**: `detect_lat/lon` = upper-left corner of pixel
    (`detect_scene_row`, `detect_scene_column`) in the scene's UTM grid (median error 0 m).
  - **train.csv has no boxes** (top/left/bottom/right 100 % null) and `source` is always `ais`.
    In train, `confidence` is a deterministic function of `is_vessel` (HIGH ⇔ non-vessel,
    MEDIUM ⇔ vessel, LOW ⇔ unknown): it encodes label provenance, not human certainty.
  - Validation: 19,224 labels; 99 % have boxes; `is_fishing` null for 80 %; length for 36 %.
  - `distance_from_shore_km` uses 9999.99 as a sentinel in some rows.
- **Relevance**: same sensor and product family (Sentinel-1 IW GRD, VV+VH) as the application;
  full scenes allow CFAR → classifier → full-pipeline evaluation; known acquisition times.
  Geography: Europe (North Sea, Adriatic, Norway, Iceland) and West Africa — **no South China Sea**.
- **Alternative hosting found**: SARFish (https://huggingface.co/datasets/ConnorLuckettDSTG/SARFish,
  Apache-2.0, public, ungated) mirrors the *original ESA* GRD + SLC products of all 753 xView3
  scenes (~0.9 GB/GRD zip; 673 GB GRD total) plus a 1-scene sample repo. Its labels are **only**
  distributed via the same login-gated xView3 page (`GRD_*.csv`, `SLC_*.csv`) and refer to the
  SAFE pixel grid, not to xView3's processed rasters. Third-party HF copies (vrajvasath, xuleijuly,
  tuyao10086, yurise) contain imagery only. No public copy of xView3 labels was found on HF,
  GitHub code search or Zenodo. `xview3.org` (listed by a TIB catalogue entry) does not resolve.

## 2. Official SSDD (fallback benchmark) — ✅ downloaded and validated

- **Source**: https://github.com/TianwenZhang0825/Official-SSDD → Google Drive file
  `1glNJUGotrbEyk43twwB9556AdngJsynZ` (`Official-SSDD-OPEN.rar`, 1,043,241,197 bytes,
  sha256 `daf79e02…3ad9`, downloaded 2026-11-23). Mirror: Baidu (password 2021).
- **Licence**: Apache-2.0 (GitHub repository). **Cite**: Zhang et al., *Remote Sens.* 13(18):3690, 2021.
- **Archive structure (inspected)**: four variants `BBox_SSDD`, `RBox_SSDD`, `PSeg_SSDD`,
  `BBox_RBox_PSeg_SSDD`, each with `voc_style/` (and COCO for BBox and the combined set). All
  four contain **byte-identical original images** (1,160 JPEGs). We use
  `BBox_SSDD/coco_style/{images/{train,test}, annotations/*.json}`; VOC XML is used as a cross-check.
- **Do not use for training**: `JPEGImages_*_GT`, `JPEGImages_PSeg_GT*` (labels burnt into pixels),
  the bundled `*.py` scripts (not executed by us) and analysis PNGs.
- **Official split**: train 928 / test 232 (test = 46 inshore + 186 offshore), defined by file
  index ending in 1 or 9 (verified). Split lists are preserved in `voc_style/ImageSets/Main/`.
- **Content**: 2,587 ship boxes (COCO == VOC; the paper quotes 2,456 — the released files contain
  2,587), single class `ship`, every image has ≥1 ship (no negative images). Images 190–526 px
  tall, 214–668 px wide; median box 22 × 29 px; 158 boxes have a side < 8 px.
- **Changes relative to xView3** (important for any transfer):
  | Aspect | xView3 | SSDD |
  |---|---|---|
  | Sensor | Sentinel-1 IW GRD only | Mix of RadarSat-2, TerraSAR-X, Sentinel-1 (per paper; **not recorded per image**) |
  | Resolution | 10 m pixels | 1–15 m, varying and **unrecorded per image** |
  | Channels | VV + VH, float dB | 8-bit JPEG; 1,126 grayscale-as-RGB, **34 false-colour RGB composites** |
  | Radiometry | calibrated dB | unknown scaling/compression, lossy JPEG |
  | Extent | full scenes ~280 × 240 km | small crops (~500 × 350 px) centred on ships |
  | Labels | point + box + length + vessel/fishing classes + confidence | box (also RBox/polygon), class `ship` only |
  | Geo/time metadata | UTM grid, acquisition time | **none** (no coordinates, timestamps, parent scene ids) |
  | Negatives | many non-vessel labels and empty sea | no ship-free images |
- **What SSDD supports**: the *modelling benchmark* (traditional descriptors vs CNN under
  identical partitions on small labelled chips). It does **not** support the geographic
  application (no georeferencing → cannot be joined to AIS) and a model trained on SSDD crops
  must not be assumed to transfer to raw Sentinel-1 scenes (different sensors/resolutions/
  radiometry, ship-centred crops, JPEG compression).
- **Leakage warning**: 22 exact-duplicate groups (47 images), 10 of them crossing the official
  train/test split; 4 further cross-split near-duplicate crops (dHash ≤ 4); visual inspection
  also shows overlapping crops of the same harbour across splits (e.g. 000763 train vs 000729
  test). Parent-scene ids are not provided, so grouping must be approximate (hash clusters +
  manual review). See validation results.

## 3. LS-SSDD-v1.0 — ❓ not investigated in depth

https://github.com/TianwenZhang0825/LS-SSDD-v1.0-OPEN (Sentinel-1 large scenes, 24k × 16k px,
cut into 9,000 sub-images). Not needed now that xView3 full scenes are available; kept as a
fallback for large-background detection if xView3 access is lost.

## 4. GFW / Paolo et al. (2024) public data (figshare) — ✅ downloaded and validated

Paper: Paolo et al., *Satellite mapping reveals extensive industrial activity at sea*, Nature 625,
2024. Code: https://github.com/GlobalFishingWatch/paper-industrial-activity. Licence: **CC BY 4.0**;
no login. Files verified against figshare MD5 (`data/raw/gfw_paolo2024/manifest.json`).

### 4a. `detection_tiles.zip` (training record, https://doi.org/10.6084/m9.figshare.24309469)
- 142,908,413 B; Zarr v2; 11,965 Sentinel-1 GRDH tiles of 80 × 80 × 2 (float16, values 0–255),
  `presence` 6,574 vessel / 5,391 non-vessel, `length_m`, sample `weight`, lat/lon, and official
  CV/test indices.
- `detect_id` = `<ESA product name>;<LON>;<LAT>` (**longitude first** — verified; README is silent).
  Gives parent scene (6,578 scenes) and acquisition time (2017-01-01 → 2021-07-15).
- Global; only **23 tiles in the SCS box**. GFW's own train and test indices share 2 scenes.
  1,265 positives have length 0 (unknown). Band order and dB→0–255 scaling are **not documented**.
- Labels are GFW's training annotations (human-reviewed per the paper; not re-verified by us).
- Supports: the **classifier stage** (candidate patch → vessel / non-vessel) with real Sentinel-1
  data and scene-level grouping. Does not support full-scene detection evaluation.

### 4b. `industrial_vessels_v20240102.csv.zip` (analysis record, https://doi.org/10.6084/m9.figshare.24309475)
- 1,728,747,413 B; 23,088,625 rows; columns `scene_id, timestamp, lat, lon, year, mmsi,
  matching_score, fishing_score, length_m, matched_category, overpasses_2017_2021`; 2017–2021.
- **These are GFW model predictions** (CNN detection, length, fishing score) joined to AIS by GFW's
  matching algorithm — *not* human ground truth and *not* raw AIS positions. `timestamp` is the
  scene acquisition time (identical for all detections of a scene). Only detections classified as
  likely vessels inside GFW's study area (coastal waters, >15 % of the ocean) are included; no
  footprint of where imaging occurred is included (footprints come from the S1 catalogue).
- SCS box (105–122°E, 0–25°N): 1,812,280 detections in 17,529 scenes (~3,000–3,800 scenes/yr);
  56 % `unmatched`, 29 % `matched_nonfishing`, 10 % `matched_fishing`, 5 % `matched_unknown`.
- Supports: a labelled **comparison layer** for the reveal demo (what GFW's pipeline found and
  matched at that exact acquisition), and selection of demo dates/areas. Newer data (2017 →
  ~5 days ago) is on the GFW Data Download Portal (`public-sar-vessel-detections:v20231026`,
  login + terms).

## 5. Copernicus Data Space Ecosystem (CDSE) — ✅ catalogue (no auth) / 📍 download (account)

- OData/STAC catalogue queried anonymously (e.g. `catalogue.dataspace.copernicus.eu/odata/v1/Products`).
  Products are listed in both SAFE and `_COG.SAFE` forms. Download needs a free CDSE account and
  an OAuth access token (not tested; no account used).
- SCS coverage, Sep–Oct 2025 GRDH (unique acquisitions ≈ half the listed products):
  south of Spratly box ~6, Paracel box ~9, Gulf of Tonkin ≥50 (query capped at 100 products),
  Pearl River Delta coast ~35.
  Open-sea SCS is revisited roughly every 6–12 days; coasts more often (S1A + S1C; S1D since late 2025).
- Historical SCS scenes referenced by GFW (2017–2019) are **online** (1.7–2.0 GB SAFE each).

## 6. Microsoft Planetary Computer — ✅ access proven (anonymous)

- STAC `sentinel-1-grd` collection; anonymous SAS token from
  `https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-grd`; per-polarisation COGs
  (`vv`, `vh`, uint16 DN in radar geometry with 231 GCPs) + calibration/noise XML assets.
- Verified: 2017–2025 SCS scenes found; a 3072 × 3072 VV+VH window of
  `S1B_IW_GRDH_1SDV_20190318T104813_…_01CDA6` read by HTTP range requests in ~10 s
  (`scripts/fetch_pc_s1_window.py`, figure `docs/figures/scs_reveal_feasibility.png`).
- Item ids drop the 4-character product suffix used by ESA/GFW names.
- Limitations: not calibrated (σ⁰ requires applying the calibration LUT), thermal noise visible
  in VH, radar geometry (GCP geolocation ~tens of m), service-level/terms of a third party.

## 7. Global Fishing Watch API / Data Download Portal — 📍 located, not used (token required)

- Free self-service registration; API token per user; **non-commercial use, CC BY-NC 4.0**;
  50,000 requests/day, 1.5 M/month; tokens must not be shared or embedded publicly
  (https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits).
- Relevant products: SAR vessel detections (GFW model output, matched/unmatched, 2017 → ~5 days
  ago), AIS-based fishing effort / vessel presence (gridded, derived), vessel identity and events.
  Point-by-point AIS tracks via the public API were **not confirmed** from the pages read.
- GFW notes that from ~2022 dynamic onboard AIS receivers "substantially improved" reception
  around China and Southeast Asia — earlier SCS AIS coverage is weaker, which inflates
  "unmatched" counts (see assessment).

## 8. Danish Maritime Authority raw AIS — 📍 located, not downloaded

- `http://aisdata.ais.dk/` (public S3 listing, no login). Raw AIS messages as CSV: timestamp,
  type of mobile, MMSI, lat, lon, navigational status (incl. "Engaged in fishing"), SOG, COG,
  heading, IMO, call sign, name, ship type, dimensions, etc.
- 2020 only as monthly zips (~15–17 GB each); recent data as daily zips (~0.6–0.75 GB/day, e.g.
  2026-10-01 → 2026-11-20). Coverage: Danish waters only (relevant to the North Sea xView3 scene
  `fc2f57371370c521v`, not to the SCS).

## 9. NOAA MarineCadastre AIS (US waters) — 📍 located (daily 2020 files listed), not downloaded
`https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2020/` — raw AIS for US waters; not relevant
to SCS but another raw-AIS option for method validation.

## Decision

1. **Primary modelling data: xView3-SAR validation (+ selected train) scenes.** Same sensor/product
   as the application, full scenes for CFAR + classifier + end-to-end evaluation, real geo/time.
2. **SSDD** retained as a secondary *benchmark* for descriptor-vs-CNN chip classification/
   detection and literature comparison, with a duplicate-aware split. Not used for geography.
3. **GFW detection tiles** as an additional real-Sentinel-1 patch set for the classifier stage
   (global, scene-grouped), with caveats on undocumented scaling.
4. **Map/reveal demo**: Planetary Computer imagery (anonymous) + GFW SAR detections table for the
   same scene (labelled as GFW's AIS-matched detections, not raw AIS). Raw AIS requires either the
   GFW API (token; SCS) or DMA (Danish waters; xView3 North Sea scene).

## Citations
- Paolo, F. et al. (2022). xView3-SAR. NeurIPS Datasets & Benchmarks. https://iuu.xview.us/
- Zhang, T. et al. (2021). SSDD: Official Release and Comprehensive Data Analysis. Remote Sens. 13(18), 3690.
- Paolo, F. S. et al. (2024). Satellite mapping reveals extensive industrial activity at sea. Nature 625, 85–91. Data: figshare 10.6084/m9.figshare.24309469 / .24309475 (CC BY 4.0).
- Luckett, C. et al. (2024). The SARFish Dataset and Challenge. WACV Workshops.
- Contains modified Copernicus Sentinel data (2017–2025).
