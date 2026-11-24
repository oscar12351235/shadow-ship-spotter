# Validation results (step 2)

**What this file is.** Before any data is used for modelling or for the map, we check that it is
what it claims to be:
- files are complete and unaltered;
- labels line up with the images;
- train and test sets don't share images;
- and so on.

This file records **what was checked on each dataset, the actual numbers, and what they mean for
the project**. What each dataset is and whether it is useful is in `context.md` §5 and
`docs/data_sources.md`.

_Run on 2026-11-23. All numbers below were produced by the scripts named in each section; the
machine-readable outputs are in `data/inventory/`. Figures are in `docs/figures/`._

**Summary of what the checks mean:**

| Dataset | Verdict after validation |
|---|---|
| **SSDD** | Labels are consistent, but the official train/test split leaks duplicate images. Usable as a benchmark only with our own duplicate-aware split. |
| **xView3** | Files are intact and labels line up with the images to within 9 m. Train labels have no boxes, and their `confidence` column carries no extra information. Small fishing boats are hard to see. |
| **GFW tiles** | Intact and parseable. Ids are lon-first (undocumented), and the band scaling is undocumented. GFW's own train/test share 2 scenes. |
| **GFW detections table** | Intact. Timestamps are scene times. 56 % of SCS detections are unmatched, which is partly an AIS-coverage effect. |
| **Planetary Computer** | A real SCS image window is readable anonymously in ~10 s, and GFW detections fall on bright targets. |

## 1. SSDD (`scripts/validate_ssdd.py`)

**Why these checks:**
- SSDD ships its labels in two formats and an official split.
- If the formats disagree, or the same image appears in both train and test, any benchmark result
  would be wrong.
- We also needed to know whether the images are plain radar greyscale.

Inputs: `BBox_SSDD/coco_style` images + COCO JSON; VOC XML and ImageSets as cross-check.
Outputs: `ssdd_images.csv` (1,160 rows), `ssdd_boxes.csv` (2,587 rows), `ssdd_validation.json`,
`docs/figures/ssdd_overlays.png`, 52 per-image overlays in `data/processed/ssdd_overlays/`.

| Check | Result |
|---|---|
| Images listed in COCO / found on disk / open with PIL | 1,160 / 1,160 / 1,160 |
| Official split | train 928, test 232 (46 inshore + 186 offshore); identical to VOC `ImageSets/Main` lists |
| Train ∩ test ids; inshore ∪ offshore = test; test ids end in 1/9 | disjoint ✔; ✔; ✔ (train ids never do) |
| COCO image id == filename number | ✔ all |
| Dimensions: COCO = VOC XML = actual JPEG | ✔ 0 mismatches |
| Boxes: COCO vs VOC count per image | 2,587 vs 2,587; 0 images differ |
| Boxes: COCO↔VOC greedy IoU match ≥ 0.5 | 2,587 / 2,587 matched; IoU median 0.924, 1 % quantile 0.745, min 0.643 (VOC integer-rounded corners vs COCO polygon-derived floats) |
| Non-positive or out-of-bounds boxes (1 px tolerance) | 0 / 0 |
| Images without ships | 0 (no negative images in SSDD) |
| Box sizes (px) | width median 21.8 (4.2–383), height median 28.5 (4.5–307); 158 boxes with a side < 8 px |
| Boxes per image | median 1, mean 2.23, max 29 |
| Pixel format | all 3-channel RGB JPEG; 1,126 grey-as-RGB; **34 false-colour composites** (channel max diff up to 217; ids around 000051–000069 and others) |
| Exact duplicates (MD5) | **22 groups / 47 images; 10 groups cross the official train/test split** (e.g. 001121 test ≡ 001122 train; 000033 train ≡ 000389 test ≡ 000637 train) |
| Near duplicates (dHash Hamming ≤ 4, excluding exact) | 9 pairs, **4 cross-split** (000011/000226, 000059/000218, 000898/000901, 001129/001132) — shifted crops of the same scene |
| Parent-scene metadata | not provided; visual review also found overlapping harbour crops across splits (000763 train vs 000729 test) that hashing misses |
| `*_GT` image folders | differ from originals for 1,160/1,160 images (labels drawn on pixels) → excluded |

Overlay check (`ssdd_overlays.png`): COCO (green) and VOC (red dashed) boxes coincide and enclose
the ships in all 12 sampled images (train/test × inshore/offshore + densest image).

**Implications**: the official SSDD split leaks; our future split must cluster exact and near
duplicates (and visually confirmed same-scene crops) into the same partition. False-colour images
need a documented single-channel conversion (or exclusion) for descriptor features.

## 2. xView3-SAR (`scripts/validate_xview3.py`)

**Why these checks.** xView3 is our primary dataset, so we checked:
- that the files are the official ones (checksums);
- how good each label file is (boxes, sources, confidence);
- above all, that each label's coordinates and pixel position really point at the object in the
  image.

Matching against AIS later depends on positions being right.

Label files (all scenes) — `xview3_label_files.json`:

| | train.csv | validation.csv |
|---|---|---|
| rows / scenes | 64,113 / 554 | 19,224 / 50 |
| SHA-1 vs download page | ✔ | ✔ |
| boxes (top/left/bottom/right) | **none** (100 % null) | 99.1 % present |
| source | ais 100 % | ais/manual 11,027; manual 8,022; ais 175 |
| confidence | HIGH 16,692 / MEDIUM 36,375 / LOW 11,046 — **identical to is_vessel False/True/NaN** | HIGH 9,219 / MEDIUM 6,571 / LOW 3,434 (mixed with is_vessel) |
| is_vessel null | 17.2 % | 0.6 % |
| is_fishing null | 43.3 % | 79.8 % |
| vessel_length_m present | 45,303 | 7,001 |
| duplicate detect_id | 0 | 0 |
| timestamps / raw AIS in labels | no / no | no / no |

Downloaded scenes — `xview3_scenes.csv`, `xview3_validation.json` (row-level labels with derived
checks go to `data/processed/xview3_labels_downloaded.csv`, git-ignored because xView3 terms ask
not to redistribute the data):

| scene | place, acquisition (UTC) | CRS, size | labels | outside raster | pixel→geo error (UL corner) | bad boxes |
|---|---|---|---|---|---|---|
| b1844cde847a3942v | Lagos coast, 2020-01-26 05:29:56–05:30:25 | EPSG:32631, 28,676 × 24,512 | 722 | 0 | median 0 m, max 8.7 m | 0 / 715 |
| fc2f57371370c521v | North Sea (DK), 2020-09-28 17:18:00–17:18:31 | EPSG:32632, 30,402 × 26,560 | 1,079 | 0 | median 0 m, max 5.4 m | 0 / 1,076 |
| fe6a8d80fb5ebb8ev | Adriatic, 2020-05-20 05:11:17–05:11:42 | EPSG:32633, 29,374 × 21,553 | 506 | 0 | median 0 m, max 7.0 m | 0 / 489 |

VV and VH share grid/CRS in all scenes; float16 dB, nodata −32768, 10 m pixels. Using the pixel
centre instead of the upper-left corner gives a constant 7.09 m error, which identified the
convention. Overlays: `docs/figures/xview3_<scene>_overlay.png` (scene overview with all labels +
four HIGH-confidence vessel crops in VV and VH with boxes). Reviewed by eye: in the Lagos and North
Sea scenes labels sit on bright targets; in the Adriatic scene several small (~20–27 m) fishing
vessels are barely separable from sea clutter (e.g. r12695 c11409 nearly invisible in VV), and for
r14704 c15025 the brightest VH return lies just below the labelled box. Small fishing vessels are
therefore a hard case — directly relevant to the SCS fishing fleet.

## 3. GFW detection tiles (`scripts/validate_gfw_tiles.py`)

**Why these checks.** To use the tiles for the classifier, we need to know:
- the label balance;
- which scene and time each tile comes from, for grouping the split by scene;
- whether the ids and positions are consistent;
- what the pixel values look like.

`gfw_detection_tiles.csv` (11,965 rows), `gfw_detection_tiles_validation.json`,
`docs/figures/gfw_detection_tiles.png`.

- MD5 matches figshare; 11,965 tiles 80 × 80 × 2 float16, values 0–255, no NaN (sampled every 25th).
- presence 6,574 / 5,391; 0 duplicate ids; ids parse for all rows; **id = scene;lon;lat** (lat/lon
  arrays agree with id to < 1e-5°); 6,578 parent scenes (median 1 tile/scene, max 579);
  2017-01-01 → 2021-07-15; S1A 5,285 / S1B 6,680; all GRDH.
- Official indices: test 3,172 (base) + 3,196 (null); `train/all` 8,673 + 1,734 val; **2 scenes
  shared between GFW train and test**.
- 23 tiles in the SCS box. 1,265 positives with length 0.
- Gallery: positives show bright compact targets at the centre (small boats faint); negatives show
  sea clutter/speckle.

## 4. GFW SAR detections table (`scripts/summarise_gfw_sar_detections.py`)

**Why these checks.** This table is our stand-in "AIS-visible" layer for historical SCS scenes and
our way to pick demo dates. We needed:
- its size;
- the match categories;
- what `timestamp` means;
- how much of it falls in the SCS.

`gfw_sar_detections_summary.json`, `gfw_sar_scs_scenes.csv` (17,529 scenes);
SCS subset in `data/processed/gfw_sar_detections_scs.parquet` (git-ignored).

- 23,088,625 rows (2017–2021); matched_nonfishing 10.2 M, unmatched 9.2 M, matched_fishing 2.9 M,
  matched_unknown 0.8 M.
- SCS box: 1,812,280 rows, 17,529 scenes; unmatched 1.01 M (56 %); `mmsi` null 55.7 % (= unmatched).
- Each scene has a single timestamp (max spread 0 s) → timestamp is scene acquisition time.

## 5. Planetary Computer access (`scripts/fetch_pc_s1_window.py`)

**Why this check.** The "Reveal" button needs the real image for the selected date and area. We
verified that a historical SCS image can be found and read without an account, quickly, and that
its content matches GFW's detections for the same instant.

- Anonymous SAS token obtained; item `S1B_IW_GRDH_1SDV_20190318T104813_…_01CDA6` (2019-03-18
  10:48:27.9Z) found; full scene 25,204 × 19,462 uint16, 231 GCPs (EPSG:4326).
- 3072 × 3072 VV+VH window around 18.45°N 110.45°E read in ~10 s (~11 MB); 66 GFW detections of the
  same scene fall in the window (65 unmatched, 1 matched_nonfishing) and coincide with small bright
  targets (`docs/figures/scs_reveal_feasibility.png`).

## 6. Not yet validated / open questions

- SSDD per-image sensor/resolution/polarisation (not in release; paper gives only dataset-level ranges).
- GFW tile band order and scaling; GFW label provenance beyond the paper's description.
- PC vs xView3 radiometry (PC is uncalibrated DN; xView3 is calibrated dB) — calibration step needed.
- GFW AIS matching algorithm details and AIS reception quality per region/year.
- xView3 `public` partition and SARFish label files were not downloaded.
