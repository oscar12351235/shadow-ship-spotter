# SSS: Shadow Ship Spotter — Project Context

> **What this file is.** The one document that explains the whole project:
> - what we are building and for whom;
> - what data we have, what each source contains, and whether it is any good;
> - how the repository is organised;
> - what has been done, and what comes next.
>
> A new team member or coding agent should be able to continue from this file alone. Supporting
> evidence (exact numbers, figures, access details) lives in `docs/` and is referenced, not copied.
>
> **Status labels:** ✅ done and verified · 🔄 in progress · 📋 planned · 📍 located but not
> downloaded or used · ❌ tried and not possible · ❓ unverified (background knowledge or open
> question).
>
> **Usefulness verdicts for data sources:** **Essential** (the project depends on it) ·
> **Useful** · **Limited** (narrow use, or major caveats) · **Not useful now**.

_Updated 2026-11-24. Sections 14–15 preserve the history of the original acquisition work._

The data layer now serves two working entry points. Training reads pinned local samples for
both model families. Scene review selects a real acquisition by UTC date and WGS84 area,
then returns a georeferenced preview, position-query coverage and a published comparison.
The source inventory, enforced compatibility matrix, GSRAI comparison, configuration and
reproduction commands are in the [data-layer guide](docs/data_layer.md).

The pinned training reader has opened all three families. Lagos, the Adriatic and the North
Sea are separate xView3 train, validation and test scenes. They contain 722, 506 and 1,079
annotations in total. The default manually reviewed product contains 715, 489 and 1,076
respectively. The other 27 have AIS-only provenance and can be requested separately.
GFW has 8,820 / 1,533 / 1,612 tiles under the shared datatake grouping rule. All 1,160
SSDD crops with unknown parent scenes form a separate benchmark.

The historical Hainan study returned two 80 × 80 raw-DN windows and 231 WGS84 parent
control points. Both windows replayed offline with their original retrieval receipts.
The viewport contained six GFW predictions and zero selected LSEG reports in the acquisition
interval expanded by 30 minutes on each side. The North Sea test returned eight selected
report variants. Population coverage remains unknown in both areas. The project has no
evaluated SCS detector or matching result.

Public checks confirmed both Figshare release MD5s, the PC measurement parent and one exact
CDSE SAFE catalogue record. The local GFW analysis ZIP and six original xView3 files passed
their publisher checksums. The Workspace app key was configured and the desktop proxy
was unreachable. CDSE pixel equivalence, historical area AIS entitlement, receiver coverage
and licensed display rights still require separate evidence.

**Contents:**
1. The project in brief
2. The application we want to build
3. How it will work, and what data that requires
4. Where we are right now
5. Data sources: what each contains, what it is for, whether it is useful
6. Repository structure: every folder and file
7. Setting up and reproducing everything
8. Decisions taken
9. Checks performed
10. Problems encountered and how they were solved
11. Open questions and blockers
12. Next steps
13. Glossary
14. Chronological account of the work
15. Progress log

---

## 1. The project in brief

This is a university machine-learning project, intended to become a working application.

**The idea.** A ship at sea can be observed in two independent ways:
- **Satellite radar images** (Sentinel-1 *SAR*). Radar works through cloud and at night.
  Vessel visibility depends on size, material, aspect, sea conditions and resolution.
- **AIS** (*Automatic Identification System*). These are radio messages in which ships report
  their own identity and position. A ship appears only if it carries a transponder, has it
  switched on, and is within range of a receiver.

Comparing the two reveals vessels that are visible in the image but absent from the available AIS
records.

**Users.** Fisheries authorities who must decide where to send limited monitoring and inspection
resources.

**Target region.** The **South China Sea (SCS)**, especially fishing activity. Models may be
trained on labelled images from other regions, but applying them to the SCS needs its own
validation.

**The key caveat.** A detection with no AIS match is **not** proof of illegal fishing, of
nationality, or of a deliberately disabled transponder. AIS reception may be poor, or the boat may
be too small to carry AIS. The application must always separate three cases:
- (a) **matched**: reliably matched to an AIS record;
- (b) **unmatched**: not matched, although AIS coverage was adequate under a documented matching
  process;
- (c) **insufficient information**: not enough AIS information to decide.

## 2. The application we want to build (not implemented yet)

1. The user opens an interactive map.
2. They select a date. The selector shows which satellite images exist and when they were taken,
   or says "no imagery available".
3. They choose an area by drawing a zone, or simply by panning and zooming. A drawn zone takes
   precedence; otherwise the visible map area is used.
4. The map shows the vessels visible through AIS for that area and observation time.
5. They press a prominent **"Reveal hidden vessels"** button.
6. The app fetches the satellite image and runs our detection pipeline, or loads a clearly
   identified earlier result.
7. Our detections are compared with AIS. Extra, unmatched candidates appear in a distinct colour.
   The AIS layer stays visible, and the layers can be toggled.
8. Clicking a detection shows:
   - the image patch, coordinates and acquisition time;
   - the model name and version, and the score;
   - the AIS matching status with supporting information;
   - whether the result was computed now or loaded from a previous run.

**Counts shown:** AIS-visible vessels, satellite detections, matched, unmatched candidates, and
insufficient-information cases.

**Rules:**
- AIS and detections must refer to compatible times, because an image is a snapshot.
- No imagery means "no imagery available", never "no hidden vessels".
- Poor AIS coverage must never turn detections into confirmed unmatched vessels.
- A layer built from someone else's AIS-matched detections (e.g. GFW) must be labelled as such,
  not presented as an AIS feed.
- The app uses real data and real pipeline outputs, with proper loading, progress, error and
  no-data states.

## 3. How it will work, and what data that requires

**Planned processing chain** 📋:
1. Fetch the Sentinel-1 image for the chosen date and area.
2. **Candidate detection.** A CFAR detector flags pixels much brighter than the surrounding sea.
3. **Classification.** For each candidate, decide whether it is a vessel. Two approaches will be
   compared on identical train/validation/test partitions:
   - (A) classical ML on hand-crafted descriptors: local contrast, brightness statistics, texture
     and shape;
   - (B) a CNN on image patches.
4. **Matching.** Compare detections with AIS positions interpolated to the image's acquisition
   time, using distance and time gates. Draft rules are in `docs/map_reveal_data_assessment.md` §4.
5. **Display.** Show the results on the map with the evidence panel.

**Planned architecture** 📋: a Python backend (data access, pipeline, matching, API) and a React
map frontend (MapLibre or Leaflet).

**This chain creates three separate data needs.** Every source in §5 is judged against them.

| Need | What it means | Why we need it |
|---|---|---|
| **A. Training and evaluation data** | Radar images in which vessels have been labelled: positions or boxes, ideally vessel vs non-vessel and fishing vs non-fishing. | To build and measure the detector and classifier. |
| **B. Initial AIS map** | Vessel positions with timestamps for the area and moment the user chooses. | The "AIS-visible" layer shown before revealing. |
| **C. Reveal operation** | **C1:** the actual Sentinel-1 image for that date and area, with its exact acquisition time. **C2:** AIS positions close enough in time to that acquisition to match against. | To run our pipeline and decide matched or unmatched. |

The detector never takes AIS as input. AIS is used only for the map layer and for matching after
detection.

## 4. Where we are right now

| Step | State |
|---|---|
| Step 1: project scope | ✅ done before this file existed |
| Step 2: data acquisition, validation and a reproducible repo foundation | ✅ done (2026-11-23) |
| Investigation of LSEG Workspace/Eikon as an AIS source | ✅ done (2026-11-23) |
| Fixed split manifests and on-demand training chips | ✅ three local data families |
| Historical scene discovery, bounded inputs and offline replay | ✅ Python API, CLI and preview script |
| CFAR baseline | 📋 next |
| Model training (descriptors vs CNN) | 📋 not started |
| Matching code | 📋 not started; rules drafted |
| Backend and frontend application | 📋 not started |

**What exists now:**
- Downloaded and validated training/evaluation data: xView3 (3 full scenes plus all label files),
  SSDD, and the GFW detection tiles.
- A proven, account-free way to fetch real SCS satellite images (Microsoft Planetary Computer).
- A comparison layer for the SCS: GFW's AIS-matched satellite detections, 2017–2021.
- Selected historical LSEG reports and dated Search exports, available offline in this checkout.
- A product-specific resolver and preview interface in `run.py`. The trained detector, matching
  algorithm, HTTP backend and map UI remain future work.

**Most important findings so far:**
1. **xView3 supplies projected, calibrated training imagery** from Europe and West Africa.
   The SCS application currently retrieves raw radar-grid DN, with different processing.
2. **SSDD's official train/test split leaks** (duplicate images on both sides), so it is a
   separate benchmark in the current manifest.
3. **Fetching SCS imagery works anonymously** (Planetary Computer, about 10 s for a 30 km window).
   The pixels need calibration before a model trained on xView3 can use them.
4. **There is no complete AIS source for the SCS at image times yet.** The biggest open problem:
   - GFW's table contains its detections and matching outcomes, including unmatched predictions.
   - LSEG provided selected-vessel history and a dated, capped Search interface.
   - A GFW API token has not been requested yet.
5. **SCS AIS coverage before ~2022 was poor.** High "unmatched" rates there are partly a coverage
   effect, not hidden vessels.

**Git state at this assessment.** The checkout started on `main` at `3365809`. The previous
foundation was merged in PR #1. The data-layer implementation is in the working tree.
- **Commit rule:** no AI co-author or attribution lines, and commit only for significant changes.

---

## 5. Data sources: what each contains, what it is for, whether it is useful

Everything downloaded lives under `data/raw/` (≈ 16 GB) and `data/processed/` (≈ 70 MB). Both are
**git-ignored and never committed**. URLs, licences, checksums and dates for every source are in
`data/sources.json`. Access mechanics and citations are in `docs/data_sources.md`.

### 5.0 Overview

| Source | What it is, in one line | Need | Useful? | Status |
|---|---|---|---|---|
| **xView3-SAR** | Full Sentinel-1 radar scenes from 2020 (Europe, West Africa) with labelled vessels | A | **Essential** | ✅ labels + 3 scenes downloaded and validated |
| **SSDD** | 1,160 small radar image chips with ship boxes, no location or date | A (benchmark) | **Limited** | ✅ downloaded and validated |
| **GFW detection tiles** | 11,965 small Sentinel-1 patches labelled vessel / not vessel | A (classifier) | **Useful** | ✅ downloaded and validated |
| **GFW SAR vessel detections 2017–2021** | 23 M model predictions with GFW's own matching | Separate published comparison, scene selection | **Useful** | ✅ local SCS Parquet |
| **Planetary Computer Sentinel-1 GRD** | Free online archive of Sentinel-1 images, readable without an account | C1 | **Essential** | ✅ access proven |
| **CDSE** | The official ESA/Copernicus Sentinel archive | C1 discovery, candidate imagery source | **Useful** | ✅ exact catalogue hit, pixel compatibility unverified |
| **LSEG Workspace (Eikon)** | Selected-vessel historical reports and latest-location snapshots | B and C2 within the sampled identifiers and times | **Limited** | ✅ prior licensed exports loaded offline |
| **LSEG Vessel Tracking API** | Separate LSEG product: last 24 h of positions | B (live) | **Not useful now** | 📍 no key |
| **GFW API** | GFW's online API: AIS-derived products, SAR detections, vessel identity | B and C2 for the SCS | **Probably useful** ❓ | 📍 token not requested |
| **DMA raw AIS** | Raw AIS messages from Danish waters | C2 for validating matching | **Useful** (validation) | 📍 not downloaded |
| **NOAA MarineCadastre AIS** | Raw AIS messages from US waters | — | **Not useful now** | 📍 |
| **SARFish** | Public copy of the xView3 images in original ESA format | A (more scenes) | **Limited** | 📍 |
| **LS-SSDD** | Large-scene version of SSDD | A | **Not useful now** | ❓ not investigated |

**Coverage of each need:**
- **A (training/evaluation): covered.**
  - xView3 is the primary dataset.
  - GFW tiles serve the classifier stage.
  - SSDD is a literature benchmark.
- **B (initial AIS map): no complete source for the SCS.**
  - LSEG gives a partial layer for recent dates.
  - The GFW detections table supplies a separate historical comparison layer.
  - The GFW API is untested.
- **C1 (imagery):** verified Planetary Computer native-DN reads. CDSE pixel fallback is disabled pending compatibility evidence.
- **C2 (AIS at image time):**
  - Covered only partially for recent images (LSEG).
  - The Danish DMA archive is a candidate for a separate regional study. No DMA data was loaded here.
  - **Historical SCS AIS is a gap.**

### 5.1 xView3-SAR — **Essential** (Need A)

**What it is.** The dataset of the xView3 challenge, run in 2021 by the US Defense Innovation Unit
(DIU) and Global Fishing Watch (GFW) to detect "dark" fishing vessels.
- 754 full Sentinel-1 scenes from 2020, each about 280 × 240 km, around Europe (North Sea,
  Adriatic, Norway, Iceland) and West Africa.
- Lists of the objects in each scene, labelled using AIS and, in the validation partition, reviewed
  by people.
- **No SCS coverage.**
- Licence CC BY-NC-SA 4.0: non-commercial, and we must not redistribute it, so row-level labels are
  never committed.
- Partitions: **train** 554 scenes (AIS-derived labels only), **validation** 50 (human-reviewed),
  **public** 150 (labels released after the challenge), **tiny** 7 (a sample).
- Access needs a free account on https://iuu.xview.us/. A team member logged in on 2026-11-23 and
  saved the files.

**What we have** (`data/raw/xview3/`, 12 GB):

| File | What it contains, in plain words | What we can use it for | Useful? |
|---|---|---|---|
| `validation.csv`: 19,224 rows, 50 scenes | One row per object in the 50 validation scenes: position, pixel location, box, vessel or not, fishing or not, length, distance from shore, confidence, label source. Reviewed by humans; 99 % have a box. | Ground truth to train and evaluate the detector and classifier on the scenes we download. | **Essential.** Our best labels. |
| `train.csv`: 64,113 rows, 554 scenes | The same columns for the train scenes, but labels come **only from AIS**. There are **no boxes**, and `confidence` merely restates `is_vessel` (HIGH = non-vessel, MEDIUM = vessel, LOW = unknown). | Extra positives and negatives if we download train scenes. Must be treated as noisier labels. | **Useful, with caution.** We have no train-scene images yet. |
| `ESA_xView3_sceneName_mapping.csv`: 754 rows | Translates each short xView3 scene id (e.g. `fc2f57371370c521v`; the final letter t/v/p means train/validation/public) into the official ESA product name, which encodes the acquisition time. | The only way to know **when** each xView3 image was taken, and to find the same image in other archives (Planetary Computer, CDSE, GFW). | **Essential.** |
| `GRD_train.csv` (64,054 rows), `GRD_validation.csv` (19,222 rows) | The same labels, re-expressed by the SARFish project in the pixel grid of the *original* ESA product rather than xView3's re-projected rasters, plus two distance-to-shore columns. | Only usable with SARFish imagery, which we have not downloaded. | **Not useful now.** |
| `validation.tar` (84 MB; in fact the gzip file `shoreline/validation.tar.gz`) | 50 files `<scene>_shoreline.npy`, one per validation scene: the coastline that xView3's scoring code uses to score near-shore detections separately. Not yet extracted. | Reproducing the official xView3 metric; possibly a coastline mask. | **Limited.** Only if we adopt the xView3 metric. |
| `tiny.txt`, `validation.txt`, `train.txt` | Personal signed download links, one URL plus SHA-1 checksum per scene. **They expire on 2026-11-23 at 21:04 UTC and must never be committed or shared.** | Downloading more scenes with `scripts/download_xview3_scenes.py` while valid; afterwards a new login is needed. | A tool, not data. |
| `archives/<scene>.tar.gz`: 3 files, 3.9 GB | The original downloaded archives, SHA-1 verified, kept for provenance. | Re-extracting. Safe to delete to save space. | Optional. |
| `scenes/<scene>/<scene>/*.tif`: 8 GB | The extracted images, described below. | Model input. | **Essential.** |

**Inside each scene.** All files share the scene's UTM map projection, are stored as float16, and
use −32768 for missing pixels.

| File | Pixel size | What it shows | Use |
|---|---|---|---|
| `VV_dB.tif`, `VH_dB.tif` | 10 m; about 30,000 × 25,000 px; 1.4 GB each | Calibrated radar brightness in decibels for the two polarisations. Ships are bright points. | Main input to the detector and classifier |
| `bathymetry.tif` | 500 m | Sea depth and land height | Masking land; depth context |
| `owiMask.tif` | 500 m | Land/ice/valid-data mask from ESA's ocean-wind product. Codes not yet inspected. | Masking land |
| `owiWindSpeed.tif`, `owiWindDirection.tif`, `owiWindQuality.tif` | 500 m | Surface wind. Wind roughens the sea and creates more "clutter". | Context for CFAR thresholds |

**The three downloaded scenes**, all from the validation partition, chosen for regional variety:

| Scene | Place | Acquisition (UTC) | Labels | Vessel / fishing / non-vessel / unknown |
|---|---|---|---|---|
| `b1844cde847a3942v` | Lagos coast, Nigeria | 2020-01-26 05:29:56–05:30:25 | 722 | 489 / 5 / 226 / 2 |
| `fc2f57371370c521v` | North Sea, Danish/German waters | 2020-09-28 17:18:00–17:18:31 | 1,079 | 287 / 38 / 751 / 3 |
| `fe6a8d80fb5ebb8ev` | Adriatic | 2020-05-20 05:11:17–05:11:42 | 506 | 362 / 50 / 80 / 14 |

Notes on this table:
- "Vessel" means non-fishing or unclassified vessels.
- Many North Sea non-vessel objects look like offshore wind-farm structures.

**Label columns** (in `train.csv` and `validation.csv`):

| Column | Meaning |
|---|---|
| `scene_id`, `detect_id` | Scene and unique object id |
| `detect_lat`, `detect_lon` | WGS84 position: the **upper-left corner** of the labelled pixel (we verified this) |
| `detect_scene_row`, `detect_scene_column` | Pixel position in `VV_dB.tif` / `VH_dB.tif` |
| `top`, `left`, `bottom`, `right` | Box in pixels (validation only) |
| `is_vessel`, `is_fishing` | True / False / empty |
| `vessel_length_m` | Length in metres, mostly from AIS |
| `distance_from_shore_km` | Distance to shore. 9999.99 is a placeholder in some rows. |
| `confidence` | HIGH / MEDIUM / LOW |
| `source` | Where the label came from: `ais`, `manual` or `ais/manual` |

The labels contain **no timestamps and no AIS messages**. Times come from the scene-name mapping.

**Is it useful?** **Essential.** It uses the same satellite, product and polarisations as the
application. Full scenes allow testing the whole chain (CFAR → classifier → evaluation), the
validation labels are human-reviewed, and acquisition times are known.

Limits:
- It does not cover the SCS.
- Only 3 of the 50 validation scenes are downloaded; the full validation set is about 123 GB.
- Small fishing boats (~20–27 m) are barely visible in the Adriatic scene.

**Validated** (details in `docs/validation_results.md` §2):
- All label-file SHA-1 checksums equal the official ones.
- All 2,307 labels of the 3 scenes fall inside their image, and all boxes are valid.
- Positions agree with pixels to within 8.7 m.
- Overlays were checked by eye: `docs/figures/xview3_*_overlay.png`.

### 5.2 Official SSDD — **Limited** (Need A, benchmark only)

**What it is.** The *SAR Ship Detection Dataset* (Zhang et al., Remote Sensing 2021; Apache-2.0).
- 1,160 small radar image chips, about 500 × 350 px, 8-bit JPEG, cut around ships.
- Source images: RadarSat-2, TerraSAR-X and Sentinel-1, at 1–15 m resolution.
- 2,587 ship boxes.
- **Not recorded:** which satellite a chip comes from, coordinates, dates, and which larger image
  it was cut from.

**What it contains** (`data/raw/ssdd/`, 2.1 GB):
- `download/Official-SSDD-OPEN.rar`: the original archive (SHA-256 recorded).
- `extracted/Official-SSDD-OPEN/`: the same 1,160 images in four label variants:
  - `BBox_SSDD/`: straight boxes, in COCO format (one JSON per split) and VOC format (one XML per
    image). **The variant we use.**
  - `RBox_SSDD/`: rotated boxes.
  - `PSeg_SSDD/`: ship outlines (polygons).
  - `BBox_RBox_PSeg_SSDD/`: all three label types together.
- `JPEGImages_*_GT*/` folders: copies with the labels **drawn onto the pixels. Never train on these.**
- `ImageSets/Main/*.txt`: the official split lists. The authors' scripts and plots are also
  included; we have not run them.
- Official split: 928 train / 232 test. The test set is 46 *inshore* (near coast or port) plus 186
  *offshore* images; test images are those whose id ends in 1 or 9.

**What we can use it for.** A quick, standard benchmark for the descriptor-vs-CNN comparison on
small labelled chips, comparable with published results.

**Is it useful?** **Limited.**
- It cannot be placed on a map or joined to AIS.
- Mixed sensors, mixed resolutions, JPEG compression and ship-centred crops all differ from raw
  Sentinel-1 scenes, so results do not transfer automatically.
- There are no ship-free images (no negatives).
- **The official split leaks**: 22 groups of byte-identical images (47 files), 10 of them on both
  sides of train/test, plus 4 near-duplicate pairs across the split.
- 34 images are false-colour composites rather than greyscale.
- Any use needs our own duplicate-aware split (`data/splits/README.md`).

Validation details: `docs/validation_results.md` §1. Overlays: `docs/figures/ssdd_overlays.png`.

### 5.3 GFW detection tiles — **Useful** (Need A, classifier stage)

**What it is.** Training data from Global Fishing Watch's 2024 *Nature* paper (Paolo et al.;
figshare; CC BY 4.0; no login needed).
- 11,965 small patches, 80 × 80 px with 2 bands.
- Cut from real Sentinel-1 images worldwide, 2017-01-01 to 2021-07-15, from 6,578 scenes.
- Each patch labelled **vessel** (6,574) or **not vessel** (5,391).

**What it contains** (`data/raw/gfw_paolo2024/training/`: 145 MB zip plus the extracted Zarr store
`detection_tiles_v4.zarr`, 187 MB):

| Array | Meaning |
|---|---|
| `tiles` (11965 × 80 × 80 × 2, values 0–255) | The two radar bands. **Band order and value scaling are not documented.** |
| `presence` | 1 = vessel, 0 = no vessel |
| `length_m` | Vessel length; 0 means unknown, which is the case for 1,265 positives |
| `weight` | GFW's training sample weight |
| `detect_lat`, `detect_lon` | Patch centre |
| `detect_id` | `<ESA product name>;<LON>;<LAT>`. **Longitude comes first**, which the README does not say. It gives the source scene and acquisition time. |

`detection_tiles_v4.zarr.index` holds GFW's own partitions:
- the test sets `test/base` and `test/null`;
- the training sets `train/0..4` (5 cross-validation folds), `train/all` and `train/null`.

The meaning of "null" is not documented.

**What we can use it for.** Training and testing the classifier stage ("is this candidate a
vessel?") on real Sentinel-1 data with many true negatives. This complements xView3.

**Is it useful?** **Useful**, with caveats:
- The bands must be decoded before mixing with xView3's dB data.
- Only 23 tiles are in the SCS.
- GFW's own train and test sets share 2 scenes, so we must regroup by scene.
- Patches cannot evaluate full-scene detection.

Details: `docs/validation_results.md` §3; gallery `docs/figures/gfw_detection_tiles.png`.

### 5.4 GFW SAR vessel detections 2017–2021 — **Useful**, as a labelled comparison layer

**What it is.** The published output of running **GFW's own** detection model over Sentinel-1
images, 2017–2021.
- Coverage: coastal waters, about 15 % of the ocean.
- Each detection is matched to AIS by **GFW's** matching algorithm (figshare; CC BY 4.0).
- **It is model output, not ground truth and not raw AIS.**

**What it contains** (`data/raw/gfw_paolo2024/analysis/industrial_vessels_v20240102.csv.zip`,
1.7 GB, 23,088,625 rows):

| Column | Meaning |
|---|---|
| `scene_id` | ESA product name of the image |
| `timestamp` | Acquisition time of the image, identical for all detections in a scene |
| `lat`, `lon` | Detection position |
| `year` | Year |
| `mmsi` | AIS identifier of the matched vessel; empty when unmatched |
| `matching_score` | Strength of the AIS match |
| `fishing_score` | 0–1 likelihood that the vessel is fishing |
| `length_m` | Length estimated by GFW's model |
| `matched_category` | `matched_fishing`, `matched_nonfishing`, `matched_unknown` or `unmatched` |
| `overpasses_2017_2021` | How many Sentinel-1 images covered that spot over the period |

**Files we derived from it** (git-ignored):
- `data/processed/gfw_sar_detections_scs.parquet`: every SCS-box row (105–122°E, 0–25°N), 1,812,280
  detections in 17,529 scenes, 56 % unmatched.
- `data/inventory/gfw_sar_scs_scenes.csv` (tracked): one row per SCS scene with counts by match
  category.
- `data/processed/gfw_scenes/<scene>.parquet`: per-scene extracts cached by the LSEG probe.

**What we can use it for:**
1. A "what GFW found" comparison layer for historical SCS demo scenes: the same image at the same
   instant, showing which detections GFW matched to AIS and which it did not.
2. Choosing demo dates and areas, using the per-scene counts.
3. A source of real vessel identifiers (MMSIs) present at a known time. We used it to test LSEG.

**Is it useful?** **Useful**, but in the interface it must be labelled *"GFW detections, matched to
AIS by GFW"* and never presented as an AIS feed:
- AIS vessels that GFW did not detect are missing.
- SCS AIS reception before ~2022 was poor, which inflates "unmatched".

Details: `docs/validation_results.md` §4.

### 5.5 Microsoft Planetary Computer, Sentinel-1 GRD — **Essential** (Need C1)

**What it is.** Microsoft's public data catalogue, which hosts the global Sentinel-1 GRD archive as
cloud-optimised files.
- GRD is the same image type as xView3, but unprocessed.
- Search uses a standard STAC API.
- Reading only needs a free, anonymous token.

**What we have** (`data/raw/planetary_computer/S1B_IW_GRDH_1SDV_20190318T104813_…_01CDA6/`, 16 MB):
one 3072 × 3072 px window (about 30 km) of the 2019-03-18 10:48 UTC image off south-east Hainan.

| File | Content |
|---|---|
| `window_vv.tif`, `window_vh.tif` | Raw, uncalibrated pixel values (uint16 "digital numbers") in the satellite's own geometry |
| `window_meta.json` | Window position, full-scene size, number of geolocation tie points (GCPs) |
| `item.json` | Catalogue metadata: footprint, times, orbit, file links (unsigned) |

**What we can use it for:**
- Fetching the image for any user-selected SCS date and area for the reveal, reading only the
  needed part (~10 s for a 30 km window).
- Building the date selector and the "no imagery" state from catalogue footprints and times.

**Is it useful?** **Essential.** It is the only imagery route that is proven and needs no account.

Caveats:
- Pixel values must be calibrated to σ⁰/dB to resemble xView3's inputs.
- Images are in radar geometry and need geolocation through their tie points.
- It is a third-party service, subject to its terms.

Proof figure: `docs/figures/scs_reveal_feasibility.png`, with GFW's detections for the same image
overlaid.

### 5.6 Copernicus Data Space Ecosystem (CDSE) — catalogue and candidate C1 source

**What it is.** The official European portal for all Sentinel data.

**What it contains.** Every Sentinel-1 product, including the historical SCS scenes GFW used (1.7–2.0 GB
each).

**What we can use it for:**
- An authoritative catalogue for checking the exact SAFE identity.
- Footprints and acquisition times for the date selector.

The historical Hainan SAFE has one exact catalogue match. Pixel substitution requires a
compatible measured asset and native-grid evidence.
- The catalogue works anonymously. Measured coverage for Sep–Oct 2025 was about 6–9 acquisitions in
  open-SCS boxes and ≥50 in the Gulf of Tonkin. The open SCS is revisited roughly every 6–12 days.
- Downloads need a free account and an OAuth token, neither of which has been set up or tested.
- Nothing was downloaded.

### 5.7 LSEG Workspace (Eikon) vessel data — selected historical and recent reports

**What it is.** The vessel-tracking data in our LSEG Workspace licence, accessed with the LSEG Data
Library for Python through a *desktop session*. The Workspace desktop app must be running and
logged in on the same machine, with `EIKON_APP_KEY` in `.env`.

**What it contains**, all tested with real calls on 2026-11-23:
- **A searchable universe of 426,024 vessels.** Each record carries its LSEG id (RIC, e.g.
  `C}KN7309983101`), name, IMO, MMSI, flag, type, dimensions and **latest** position.
- **Per-vessel fields:**
  - position time (UTC, to the second) and latitude/longitude;
  - AIS speed, course, heading, navigational status, destination and ETA.
- **Per-vessel history from at least 2010**, requested by date, but **only in whole-day steps**.
- **Recent positions are dense**: about one report every 3 minutes.
- **Old history is sparse**: about 4 reports per vessel per day in 2019–2020, with course missing.

**What we can use it for:**
- A **recent** AIS map layer: who was in an area at a time T within roughly the last days. This is
  reconstructed by finding candidates near the area, then reading their history around T.
- Matching against **recent** satellite images.

**Is it useful?** **Limited:**
- **No historical area query.** Search only knows each vessel's latest position, so "who was here
  in 2019" cannot be asked.
- **Measured on our scenes:** of the vessels GFW matched to AIS, LSEG had a report within 30 min of
  acquisition for 6 of 112 in the North Sea 2020 scene, and 0 of 61 at Hainan 2019.
- **The universe is a commercial-fleet subset:**
  - The SCS box holds only 223 fishing-typed vessels.
  - Only 9 vessels were reconstructed in a 3° × 2° box off Hainan at a recent time.
  - Coverage is thin even in the Singapore Strait.
- **MMSIs are ambiguous.** One MMSI maps to 25 LSEG vessels; another now belongs to a different ship.
- **The desktop session cannot run on a server.**
- **Display rights for showing LSEG data to app users are unverified.**

Full evidence: `docs/lseg_shipping_access_assessment.md`. Samples (licensed, git-ignored):
`data/raw/lseg/`.

### 5.8 LSEG Vessel Tracking API — **Not useful now**

**What it is.** A separate LSEG REST/WebSocket product with its own API key.

**What it contains.** Position history for one vessel per call (IMO, RIC or ENI), covering the
**most recent 24 hours only**.

**What we can use it for.** At most, a live layer.

**Is it useful?** **Not useful now.** There is no key: `VESSEL_TRACKING_API_KEY` is absent, and
the endpoint answers HTTP 401 without one. 24 hours is too short for our imagery. Not tested.

### 5.9 Global Fishing Watch API / Data Download Portal — **Probably useful** ❓ (Needs B, C2)

**What it is.** GFW's online services. Free self-service registration gives a personal token.
Use must be non-commercial (CC BY-NC 4.0), with limits of 50,000 requests/day and 1.5 M/month.

**What it contains:**
- SAR vessel detections, from 2017 to about 5 days ago.
- AIS-derived fishing effort and vessel presence (gridded).
- Vessel identity and events.

Whether point-by-point AIS tracks are available was **not confirmed**.

**What we can use it for.**
- AIS context for the SCS at image times.
- Recent GFW detections for comparison.

**Is it useful?** **Probably**, as the best candidate for SCS AIS, but unverified. Someone on the
team must register; the token must never be committed.

### 5.10 Danish Maritime Authority (DMA) raw AIS — **Useful** for validating matching

**What it is.** Raw AIS messages for Danish waters, published openly at `http://aisdata.ais.dk/`.

**What it contains.** One CSV row per AIS message: timestamp, MMSI, position, navigational status
(including "engaged in fishing"), speed, course, heading, IMO, name, ship type and dimensions.
- 2020 data comes only as monthly zips of about 16 GB.
- Recent data comes as daily zips of about 0.7 GB.

**What we can use it for.** Validating *our matching procedure* with genuine raw AIS against the
labelled North Sea xView3 scene `fc2f57371370c521v` (2020-09-28).

**Is it useful?** **Useful** for method validation only. It covers Danish waters, not the SCS, and
the 2020 file is heavy. Not downloaded.

### 5.11 NOAA MarineCadastre AIS — **Not useful now**

**What it is.** Raw AIS for US waters, as daily files (2020 listing verified).

**Is it useful?** **Not useful now.** None of our scenes are in US waters. It remains a fallback for
method validation.

### 5.12 SARFish — **Limited**

**What it is.** An Australian (DSTG) public Hugging Face dataset containing the *original* ESA
files (GRD and SLC) of all 753 xView3 scenes. GRD zips are 0.5–1.2 GB each, 673 GB in total.

**What we can use it for.** Getting more xView3 scenes without the expiring xView3 links, or using
complex SLC data. Its labels are the `GRD_*.csv` files above.

**Is it useful?** **Limited.** xView3's own processed rasters are easier to use, and we already
have the labels. Not downloaded.

### 5.13 LS-SSDD-v1.0 — **Not useful now**

**What it is.** A larger SSDD variant: large Sentinel-1 scenes (24,000 × 16,000 px) cut into 9,000
sub-images.

**Is it useful?** **Not useful now**, because xView3 provides full scenes with better labels. It
is a fallback only. Not investigated in depth.

---

## 6. Repository structure: every folder and file

```
shadow-ship-spotter/
├── README.md, context.md          project intro / this complete context file
├── pyproject.toml, uv.lock        dependencies + tool settings (uv)
├── install.sh, install.bat        one-command setup (macOS/Linux, Windows)
├── run.py                         training, scenes, raster windows and dated scene review
├── .gitignore, .env.example       ignore rules / names of local secrets (no values)
├── src/shadow_ship_spotter/       the Python package (importable code)
├── scripts/                       runnable steps: download, validate, probe
├── tests/                         unit tests (pytest)
├── notebooks/                     exploratory notebooks
├── docs/                          detailed write-ups + figures
└── data/                          registry, inventories, splits (tracked) + raw/processed (ignored)
```

**Root files:**

| File | What it is | Notes |
|---|---|---|
| `README.md` | Short project introduction, setup and links | Points here for full context |
| `context.md` | This file | Update after every meaningful milestone |
| `pyproject.toml` | Project metadata, dependencies, tool configuration (black, ruff, mypy, pytest) | Main dependencies: numpy, pandas, polars, pydantic, matplotlib, scipy, seaborn, rasterio, zarr, pyarrow. Groups: `dev` (pytest, black, ipykernel), `lint` (ruff, mypy), `lseg` (lseg-data) |
| `uv.lock` | Exact locked versions, for reproducible installs | Generated by uv; commit with dependency changes |
| `install.sh` / `install.bat` | Run `uv sync --python 3.12 --all-groups` | Requires uv |
| `run.py` and `__main__.py` | Invoke the package data CLI | Same commands and validation from either entry point |
| `.gitignore` | Keeps `data/raw/`, `data/processed/`, `*.part`, `.env` and caches out of Git | |
| `.env.example` | Names of local secrets: `EIKON_APP_KEY`, `VESSEL_TRACKING_API_KEY` | Copy to `.env` (git-ignored) and fill in locally |

**Package `src/shadow_ship_spotter/`:**

| Module | What it does |
|---|---|
| `__init__.py`, `core.py` | Template placeholder (`build_demo_frame`), kept so the smoke test passes |
| `paths.py` | Canonical paths: `RAW_DIR`, `PROCESSED_DIR`, `SPLITS_DIR`, `INVENTORY_DIR`, `SOURCES_FILE`, `FIGURES_DIR` |
| `config.py` | Reads secrets from `.env` without printing them and without overriding existing environment variables |
| `data/download.py` | Standard-library downloader: resumable HTTP downloads, Google Drive large-file handling, SHA-256/MD5/SHA-1 verification |
| `data/ssdd.py` | SSDD readers (COCO JSON, VOC XML, split lists), box overlap (IoU) and matching, image hashing for duplicate detection |
| `data/lseg.py` | LSEG helpers: verified field lists, local Workspace proxy discovery, error classification, response parsing, timestamp and coordinate validation, nearest-report and interpolation, search filters |
| `data/contracts.py`, `compatibility.py` | Immutable requests, UTC intervals, WGS84 bounds, native windows, statuses, revisions and directional product rules |
| `data/catalog.py`, `imagery.py`, `geo.py` | Date/area discovery, checked raster routes, GCP/affine transformations and per-band window completion |
| `data/http.py`, `storage.py` | Bounded transfers, transactional window cache, integrity checks and atomic publication |
| `data/observations.py`, `search_exports.py`, `reference.py` | Position observations, registry candidates and published predictions with separate provenance and coverage |
| `data/training.py`, `study.py`, `cli.py` | Fixed sample assembly, historical scene preparation and command-line consumers |

**Scripts `scripts/`.** Run from the repository root with `uv run python -I scripts/<name>.py`. The
`-I` flag stops downloaded files from shadowing Python modules.

| Script | What it does | Needs | Writes |
|---|---|---|---|
| `download_ssdd.py` | Downloads the SSDD archive from Google Drive, checks SHA-256, extracts it | Internet | `data/raw/ssdd/` |
| `validate_ssdd.py` | Checks SSDD images, labels, split and duplicates; draws overlays | SSDD | `data/inventory/ssdd_*`, `docs/figures/ssdd_overlays.png`, `data/processed/ssdd_overlays/` |
| `download_xview3_scenes.py` | Downloads chosen xView3 scenes from a personal link list, checks SHA-1, extracts safely | Valid xView3 link list | `data/raw/xview3/archives/`, `scenes/` |
| `validate_xview3.py` | Checks xView3 label files, and each downloaded scene against its labels; draws overlays | xView3 files | `data/inventory/xview3_*`, `docs/figures/xview3_*`, `data/processed/xview3_labels_downloaded.csv` |
| `download_gfw_paolo2024.py` | Downloads GFW's figshare files and checks MD5 (`--with-detections` adds the 1.7 GB table) | Internet | `data/raw/gfw_paolo2024/` |
| `validate_gfw_tiles.py` | Checks the GFW tiles and parses scene and time from ids; draws a gallery | GFW tiles | `data/inventory/gfw_detection_tiles*`, `docs/figures/gfw_detection_tiles.png` |
| `summarise_gfw_sar_detections.py` | Scans the 23 M-row GFW table, extracts the SCS subset, counts per scene | GFW table | `data/processed/gfw_sar_detections_scs.parquet`, `data/inventory/gfw_sar_*` |
| `fetch_pc_s1_window.py` | Exports a native PC window with shifted GCPs and an optional published overlay | Cached window or PC access | `data/processed/pc_windows/`, configurable figure |
| `check_source_access.py` | Opt-in small Figshare, PC, CDSE and Workspace access checks | Network or local desktop for the relevant check | Redacted JSON to stdout |
| `probe_lseg_shipping.py` | Bounded test of LSEG vessel data: fields, identifiers, history at our scene times, area search, fishing coverage, limits | Workspace running + `EIKON_APP_KEY` | `data/raw/lseg/probe_<UTC>/` (licensed, git-ignored) |

**Tests.** Run the credential-independent suite with `uv run pytest`.

| File | Covers |
|---|---|
| `test_smoke.py` | The template placeholder |
| `test_raster_resolver.py` | Product selection, uncovered rectangles, cache recovery, parent grids, invalid requests and policy |
| `test_storage_transport.py` | Retry/entitlement handling, interrupted publication, concurrent cache access and corrupted bytes |
| `test_study_inputs.py` | Scene, position, registry and prediction inputs, empty/partial response semantics, split and CLI integration |
| `test_data_helpers.py` (6) | IoU, box matching, VOC parsing, checksum verification, xView3 link-list parsing |
| `test_lseg_helpers.py` | Environment parsing, error classes, response parsing, timestamps, bounded interpolation, geometry and filters |

**Notebook.** `notebooks/01_data_inspection.ipynb` reads the inventories (it works without raw
data) and, when raw data is present, shows:
- SSDD images with boxes, including a duplicate pair that crosses the split;
- an xView3 chip with its label;
- GFW tile and detection statistics.

It runs cleanly from top to bottom.

**Documentation `docs/`:**

| File | What it explains |
|---|---|
| `data_sources.md` | Every source: what it is, contents, use, usefulness, access mechanics, licence, citations |
| `data_layer.md` | Current source inventory, enforced compatibility matrix, architecture decision, verified runs and operating examples |
| `validation_results.md` | What was checked on each dataset, the actual numbers, and what they imply |
| `map_reveal_data_assessment.md` | What the map and "Reveal" interaction need step by step; realistic demo routes; draft matching rules |
| `lseg_shipping_access_assessment.md` | Evidence from the LSEG Workspace investigation |
| `figures/ssdd_overlays.png` | 12 SSDD images with COCO and VOC boxes |
| `figures/xview3_<scene>_overlay.png` | For each xView3 scene, an overview with all labels plus four close-ups in VV and VH |
| `figures/gfw_detection_tiles.png` | Gallery of GFW vessel and non-vessel tiles |
| `figures/scs_reveal_feasibility.png` | Planetary Computer window off Hainan with GFW's matched and unmatched detections |

**Data `data/`.** Small files are tracked; large ones are git-ignored. `data/README.md` has the
full layout and commands.

| Path | Tracked? | What it is |
|---|---|---|
| `sources.json` | ✅ | Registry of every source: URL, licence, citation, size, checksum, download date, status, reproduce command |
| `README.md` | ✅ | Data layout and exact reproduction commands |
| `inventory/ssdd_images.csv` | ✅ | One row per SSDD image: split, size, channel check, hashes, box counts, and empty columns for the metadata SSDD lacks |
| `inventory/ssdd_boxes.csv` | ✅ | One row per SSDD box: COCO box, matching VOC box, overlap, validity |
| `inventory/ssdd_validation.json` | ✅ | All SSDD check results, including duplicate groups |
| `inventory/xview3_scenes.csv` | ✅ | The 3 downloaded scenes: ESA name, times, projection, size, bounds, label counts |
| `inventory/xview3_label_files.json` | ✅ | Statistics of `train.csv` and `validation.csv` (aggregate only, for licence reasons) |
| `inventory/xview3_validation.json` | ✅ | Per-scene check results |
| `inventory/gfw_detection_tiles.csv` | ✅ | One row per GFW tile: source scene, time, position, label, length, GFW partition flags |
| `inventory/gfw_detection_tiles_validation.json` | ✅ | GFW tile check results |
| `inventory/gfw_sar_scs_scenes.csv` | ✅ | One row per SCS scene: GFW detection counts by match category, used to pick demo scenes |
| `inventory/gfw_sar_detections_summary.json` | ✅ | Global and SCS summary of the GFW detections table |
| `splits/training-v1.json`, `splits/README.md` | ✅ | Pilot partition policy, pinned inputs and evaluation constraints |
| `loading.toml` | ✅ | Validated raster priority, named position exports, online mode and required layers |
| `raw/` | ❌ ignored | Original downloads and extracted archives (§5), plus LSEG samples |
| `processed/ssdd_overlays/` | ❌ | 52 per-image SSDD overlay PNGs |
| `processed/xview3_labels_downloaded.csv` | ❌ | Row-level xView3 labels of the 3 scenes with our checks (never commit: licence) |
| `processed/gfw_sar_detections_scs.parquet` | ❌ | SCS subset of GFW detections |
| `processed/gfw_scenes/` | ❌ | Per-scene GFW detections cached by the LSEG probe |

## 7. Setting up and reproducing everything

```bash
./install.sh                     # or install.bat on Windows; needs uv
uv run pytest
uv run ruff check . && uv run black --check . && uv run mypy src
```

Every download, extraction and validation command is listed in `data/README.md`.
- **No account needed:** SSDD, GFW figshare, Planetary Computer.
- **xView3:** needs a personal login and fresh link lists.
- **LSEG probe:** needs the Workspace desktop app running and `EIKON_APP_KEY` in `.env`.

**Credentials:**
- Never commit `.env`, xView3 link lists or any token.
- Report only whether a secret is present, never its value.

## 8. Decisions taken (and alternatives)

| Decision | Why | Alternatives considered |
|---|---|---|
| xView3 validation scenes are the primary modelling data | Same sensor and product as the application, full scenes, human-reviewed labels, real location and time | SSDD only (no location, mixed sensors); SARFish (labels gated anyway) |
| Keep SSDD as a secondary benchmark (BBox variant, COCO), with a duplicate-aware split | Small, quick, comparable with the literature for descriptor vs CNN | Drop SSDD; LS-SSDD |
| Add GFW detection tiles for the classifier stage | Real Sentinel-1, global, groupable by scene, includes non-vessels | — |
| First demo route: Planetary Computer imagery + GFW detections of the same scene | No account needed, SCS coverage, exact time alignment | CDSE (account); GFW API (token) |
| Download 3 xView3 scenes, not whole partitions | Avoid 123+ GB; enough to prove access and formats | Full validation set |
| Never commit row-level xView3 labels or LSEG data | xView3 licence (no redistribution); LSEG data is licensed for individual use | Committing inventories |
| Standard-library downloader and `.env` loader | Fewer dependencies, resumable, checksum-verified, testable | gdown, requests, python-dotenv |
| LSEG through `lseg-data` desktop session, as an optional dependency group | Supported successor SDK; the only route our credential supports | Legacy `eikon` package; platform session (no credentials) |
| LSEG tests use GFW's AIS-matched MMSIs from our own scenes, resolved MMSI → LSEG id | Real vessels known to be present at the image time; identifiers never assumed interchangeable | Arbitrary well-known vessels |
| Never send the Eikon key to the Vessel Tracking API | Separate product and credential | Trying the Eikon key there |
| LSEG only for a recent-image demo; historical scenes keep the GFW layer (plus GFW token or DMA AIS) | Measured sparsity and no historical area query | LSEG for everything |

## 9. Checks performed

Actual results are in `docs/validation_results.md` and `docs/lseg_shipping_access_assessment.md`.

**Datasets:**
- ✅ **SSDD:** structure, COCO-vs-VOC agreement (all 2,587 boxes match), split, duplicates,
  colour channels. Overlays reviewed by eye.
- ✅ **xView3:**
  - Label-file checksums and statistics.
  - Every label of the 3 scenes checked against its image: position, inside the image, box validity.
  - All 3 overlays reviewed by eye. Lagos and North Sea are clear; in the Adriatic, small fishing
    boats are hard to see, and in one crop the brightest return sits just below the box.
- ✅ **GFW tiles:** checksum, id parsing, partitions, gallery.
- ✅ **GFW detections table:** global and SCS summary.
- ✅ **Planetary Computer:** window read and overlay.
- ✅ **LSEG:** probe run 3 times against the live session. The final run made 62 requests with no
  unexpected errors, and all 377 historical timestamps fell inside the requested days.

**Code quality:**
- ✅ `pytest` 19/19.
- ✅ `ruff`, `black` and `mypy` clean.
- ✅ The notebook executes.

## 10. Problems encountered and how they were solved

**xView3:**
- Pages returned 404 when opened by direct URL. This is single-page-app routing, solved by
  navigating inside the app after login (done by the user).
- The agent's probe of the authenticated download API was blocked by the permission policy and not
  retried.
- A pixel-to-coordinate check showed a constant 7.09 m error with pixel centres. The labels use
  pixel corners; check fixed.

**GFW:**
- Tile ids parsed as lat;lon gave 238° errors. The order is lon;lat; parser fixed and documented.

**Libraries:**
- Polars needed pyarrow for parquet output, so it was added.
- A zarr 3 string-type cast error was fixed in the script.

**Planetary Computer:**
- Id lookups failed with the ESA suffix. Planetary Computer ids drop it; lookup fixed.

**LSEG:**
- `.env` was staged for commit. It is now unstaged and git-ignored.
- Date parameters with unquoted times gave error 234. Quoted times are accepted but ignored (whole
  days only), so the probe pulls whole days and filters locally.
- Plausible field names (e.g. `TR.AssetLocationSpeed`) made requests fail. The correct names are
  `TR.AssetSpeed`, `TR.AssetCourse` and `TR.AssetHeading`.
- One malformed request returned "Permission Denied to parameter 'Dur'". It did not recur with
  valid fields, so it was not an entitlement limit.
- Search returns at most 10,000 results per query.
- Python's bundled certificate store failed for the Vessel Tracking host. Fixed with `certifi`.
- Shared and reassigned MMSIs produced false historical matches, e.g. a "Hainan 2019" vessel whose
  track was in the Baltic. Checks now require position consistency.

## 11. Open questions and blockers

**Data and radiometry:**
- **AIS for the SCS at image times** (the main blocker). GFW API token not requested; point-level
  tracks unconfirmed. LSEG has sparse selected-identifier history and unknown area reception.
- How "insufficient AIS information" will be measured, e.g. AIS message density nearby in the same
  hour.
- Planetary Computer pixels are uncalibrated and in radar geometry. Calibration and geolocation
  steps are needed before an xView3-trained model can be applied.
- GFW tile band order and scaling, and GFW's matching algorithm details.

**xView3:**
- Signed links expire on **2026-11-23 at 21:04 UTC**. More scenes need a fresh login.
- The `public` partition labels and the SARFish label files were not downloaded.

**LSEG:**
- The desktop session cannot back a hosted backend without a platform licence. ❓
- App display rights are unverified. ❓
- Why SCS coverage is so thin (AIS source or entitlement) is unknown. ❓
- No Vessel Tracking API key.
- The probe's failure exits (Workspace closed, session failure) are implemented but were not
  exercised.

## 12. Next steps

1. **Inspection:**
   - Review more xView3 chips per class and confidence.
   - Decide how to handle SSDD's false-colour images.
   - Manually review SSDD near-duplicate clusters.
2. **Extend evaluation coverage.** Acquire additional reviewed xView3 scenes and SCS labels
   under the relevant terms. Publish a new manifest for any changed split. Using SSDD for
   internal training would first require manual resolution of overlapping or duplicate crops.
3. **Pipeline foundations:**
   - Extract chips from xView3: positives from labels, negatives from sea areas away from labels.
   - CFAR baseline on the dB rasters, with land masking from bathymetry/`owiMask`.
4. **Map and reveal:**
   - Connect the date/area selector to the verified discovery and study interfaces.
   - Choose demo scene(s) from `gfw_sar_scs_scenes.csv`, preferring later dates with better AIS.
   - Implement σ⁰ calibration for Planetary Computer data.
   - Request a GFW API token.
5. **LSEG recent-image demo:**
   - Take a Sentinel-1 image from the last few days over the SCS.
   - Reconstruct the LSEG AIS layer at its acquisition time, save it locally, and label it
     "LSEG Workspace AIS (subset)".
   - Ask the LSEG account manager about the AIS source and entitlement, historical by-area
     products, a platform licence, a Vessel Tracking key, and display rights.
   - Use DMA raw AIS for historical North Sea validation.

## 13. Glossary — acronyms and technical terms

Statements marked ❓ come from general background knowledge, not something we verified ourselves.

**Maritime / domain**

| Term | Meaning |
|---|---|
| SSS | *Shadow Ship Spotter*, this project. |
| AIS | *Automatic Identification System*. A VHF radio transponder on ships that broadcasts identity, position, speed and course every few seconds to minutes. Coastal stations, other ships and satellites receive it. Large ships must carry it; many small fishing boats don't, and it can be switched off or go unreceived. |
| MMSI | *Maritime Mobile Service Identity*. The 9-digit identifier carried in every AIS message. GFW's matched detections include it. |
| IMO number | 7-digit ship identifier issued under the *International Maritime Organization* scheme. A column in raw AIS (DMA). |
| SOG / COG | AIS *Speed Over Ground* / *Course Over Ground*. Not to be confused with COG = Cloud-Optimised GeoTIFF (below). |
| IUU fishing | *Illegal, Unreported and Unregulated* fishing. The problem xView3 was designed around. |
| "Dark" vessel | A vessel seen in imagery with no matching AIS. We never use this as a conclusion: it may simply be an AIS reception gap. |
| EEZ | *Exclusive Economic Zone*: a coastal state's maritime zone, up to 200 nautical miles from shore. |
| SCS | *South China Sea*, our target region. Our rough analysis box is 105–122°E, 0–25°N. |
| AOI | *Area Of Interest*: the selected zone, or the map viewport. |

**Satellites and radar**

| Term | Meaning |
|---|---|
| SAR | *Synthetic Aperture Radar*. An active microwave imaging radar: it emits its own pulses, so it sees through cloud and at night. Metal ships reflect strongly and look like bright spots on darker sea. |
| ESA / Copernicus | *European Space Agency* / the EU Earth-observation programme that operates Sentinel satellites with free and open data. |
| Sentinel-1 (S1), S1A/B/C/D | Copernicus C-band SAR satellites ❓: S1A (launched 2014), S1B (2016, failed Dec 2021), S1C (launched Dec 2024), S1D (launched late 2025). All our imagery is Sentinel-1. |
| C-band | Radar frequency of about 5.4 GHz (wavelength ~5.5 cm). |
| IW | *Interferometric Wide swath*: Sentinel-1's standard mode near coasts. About 250 km wide, made of 3 sub-swaths (IW1–3) whose seams are visible in VH images. |
| GRD / GRDH | *Ground Range Detected*: Level-1 product with amplitude only (phase dropped), projected onto the ground. GRDH = high-resolution class, 10 m pixels. xView3, GFW and Planetary Computer all use GRDH. |
| SLC | *Single Look Complex*: Level-1 product keeping complex values (amplitude and phase) in slant-range geometry, with ~2.3 × 14.1 m pixels. SARFish provides SLC; we have not downloaded it. |
| OCN / OWI | Sentinel-1 Level-2 *Ocean* product / its *Ocean Wind field* component. xView3's `owiWindSpeed/Direction/Quality/Mask.tif` files come from it. |
| VV, VH (HH, HV) | Polarisations: first letter = transmitted, second = received (V = vertical, H = horizontal). VV is "co-pol"; VH is "cross-pol", where sea clutter is weaker, so ships often stand out better. |
| 1SDV | Part of a product name: Level **1**, **S**tandard class, **D**ual polarisation **V**V+VH. |
| SAFE | *Standard Archive Format for Europe*: ESA's product folder (`manifest.safe`, `measurement/*.tiff`, `annotation/*.xml`, calibration and noise XML). `_COG.SAFE` is a cloud-optimised variant. |
| Product name | Example `S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE`: mission S1B · mode IW · product GRD, resolution H · 1SDV · sensing start · sensing stop (UTC) · absolute orbit 015408 · data-take ID 01CDA6 · product unique ID F3BE. Planetary Computer IDs drop the last part (F3BE). |
| DN | *Digital Number*: the raw, uncalibrated pixel value stored in a GRD file. Planetary Computer serves DN. |
| σ⁰ (sigma-nought) | Calibrated radar backscatter coefficient, normally shown in dB. Computing it from DN requires the product's calibration look-up table (LUT). |
| dB | Decibel: 10·log₁₀ of a power ratio. xView3 rasters are stored in dB (`VV_dB.tif`), processed by the xView3 team ❓ (calibration and terrain correction per their paper; not re-derived by us). |
| Speckle / sea clutter | Granular noise inherent to SAR / backscatter from the sea surface (stronger with wind). Both cause false alarms. |
| GCP | *Ground Control Points*: tie points (pixel ↔ lat/lon) embedded in GRD products, used to geolocate images that are still in radar geometry. Our Planetary Computer scene has 231. |
| Radar geometry vs map projection | GRD from Planetary Computer/CDSE is in the satellite's geometry and needs GCPs. xView3 rasters are already projected to a UTM grid. |
| Revisit | How often the same place is imaged: roughly 6–12 days in the open SCS, more often near coasts (our catalogue query). |

**Geospatial and data formats**

| Term | Meaning |
|---|---|
| GeoTIFF / COG | TIFF image plus georeferencing / *Cloud-Optimised GeoTIFF*: internally tiled, so a client can download just the part it needs with HTTP range requests. Planetary Computer serves COGs. |
| CRS / EPSG / WGS84 | *Coordinate Reference System* / the EPSG numeric registry of CRSs / *World Geodetic System 1984*, the GPS datum. EPSG:4326 is WGS84 latitude/longitude. |
| UTM | *Universal Transverse Mercator*: 60 zones with metric coordinates. The xView3 scenes use zones 31N, 32N and 33N (EPSG:32631/32632/32633). |
| Geotransform | Affine formula mapping a pixel (row, column) to map coordinates. We used it to check xView3 labels. |
| STAC | *SpatioTemporal Asset Catalog*: standard JSON API for searching imagery by area and time (used with Planetary Computer). |
| OData | *Open Data Protocol*: the query API of the CDSE catalogue. |
| SAS token | *Shared Access Signature* (Microsoft Azure): a short-lived token appended to file URLs. Planetary Computer issues them without login. |
| Zarr | Chunked, compressed array format stored as a directory. Used for the GFW tiles. |
| Parquet | Columnar table format. Used for our SCS subset of GFW detections. |
| npy | NumPy array file. Used for the xView3 shoreline files. |
| RAR, tar.gz, zip | Archive formats. SSDD is RAR, xView3 scenes are tar.gz, GFW files are zip. |
| COCO | *Common Objects in Context* annotation format: one JSON file with `images`, `annotations` (bbox `[x, y, width, height]`, polygon `segmentation`, `area`) and `categories`. |
| VOC | *PASCAL Visual Object Classes* annotation format: one XML per image with `<bndbox>` holding xmin/ymin/xmax/ymax. |
| BBox / RBox / PSeg | Axis-aligned bounding box / rotated box (centre, width, height, angle θ, 4 corners) / polygon segmentation (ship outline). These are the three SSDD label types. |

**Checks, validation and ML**

| Term | Meaning |
|---|---|
| MD5, SHA-1, SHA-256 | Hash functions that fingerprint a file. If our hash equals the published one, the file is complete and unaltered. |
| dHash / Hamming distance | *Difference hash*: a 64-bit perceptual fingerprint of a shrunken grayscale image / number of differing bits. ≤ 4 bits means near-identical images. |
| IoU | *Intersection over Union* of two boxes: 0 = no overlap, 1 = identical. |
| Leakage | The same or near-same data in both training and test sets, which makes results look better than they are. |
| UL corner | Upper-left corner of a pixel. xView3 lat/lon refer to it. |
| ML / CNN | Machine learning / *Convolutional Neural Network* (approach B: learns features from image patches). |
| Descriptors | Hand-crafted features such as contrast, brightness statistics, texture and shape (approach A). |
| CFAR | *Constant False Alarm Rate* detector: flags pixels much brighter than their local sea background, with a threshold set so the false-alarm rate stays constant. Our planned candidate stage. |
| CV / train / val / test | Cross-validation / data partitions used for fitting, tuning and final evaluation. |

**Organisations, services, licences and tools**

| Term | Meaning |
|---|---|
| DIU | *Defense Innovation Unit* (US DoD). Runs the xView challenges. |
| xView3 / xView3-SAR | The third xView challenge (2021, with GFW): detecting vessels, including dark fishing vessels, in Sentinel-1 imagery. xView3-SAR is its dataset. |
| GFW | *Global Fishing Watch*: non-profit that publishes AIS- and SAR-derived fishing data, and co-organised xView3. |
| CDSE | *Copernicus Data Space Ecosystem*: the official portal for Sentinel data. |
| PC | Microsoft *Planetary Computer*: a public data catalogue hosting Sentinel-1 GRD as COGs. |
| DMA | *Danish Maritime Authority*: publishes raw AIS for Danish waters. |
| NOAA / MarineCadastre | US *National Oceanic and Atmospheric Administration* / the US AIS data portal. |
| SSDD / LS-SSDD | *SAR Ship Detection Dataset* (Zhang et al., 2021) / its *Large-Scale* variant. |
| SARFish | Dataset by Australia's DSTG (*Defence Science and Technology Group*) that re-packages the xView3 scenes as original GRD + SLC products. |
| HF | Hugging Face: dataset/model hosting site, where SARFish lives. |
| DOI / figshare | *Digital Object Identifier* / research-data repository hosting the GFW paper data. |
| NeurIPS / WACV | Conferences where the xView3 paper and the SARFish paper were published. |
| CC BY / CC BY-NC / CC BY-NC-SA / Apache-2.0 | Licences: attribution / + non-commercial / + share-alike / permissive software licence. |
| SPA / Nuxt / AWS Cognito / API Gateway | *Single-Page Application* / the JS framework of the xView3 site / Amazon's login service / Amazon's API front-end. Together they explain the xView3 404s and login. |
| aria2 | Download manager. The xView3 link lists are in its input format. |
| uv, pytest, ruff, black, mypy | Python environment manager, test runner, linter, formatter, type checker. |
| rasterio / GDAL | Python raster I/O library and its underlying geospatial engine. |

**LSEG / Eikon (vessel data)**

| Term | Meaning |
|---|---|
| LSEG | *London Stock Exchange Group*, which owns the former Refinitiv/Thomson Reuters data business. |
| Eikon / Workspace | LSEG's desktop data terminals; Workspace is the successor of Eikon. Ours is "Refinitiv Workspace" 1.26.843. |
| LSEG Data Library for Python (`lseg-data`) | Current Python SDK, the successor of `eikon` and `refinitiv-data`. We use 2.1.1. |
| Desktop session / platform session | Desktop: requests go through the local Workspace app (it must be running and logged in), authenticated by an *app key*. Platform: direct cloud access with RDP credentials (*Refinitiv Data Platform*), no desktop app. We have only the desktop route. |
| App key | Application identifier generated in Workspace ("App Key Generator"). Ours is `EIKON_APP_KEY` in `.env`. |
| Data API Proxy | Local HTTP proxy of Workspace (127.0.0.1:9000 here). It exposes `/api/status` and `/api/throttling/limits`. |
| RIC | *Refinitiv Instrument Code*. Vessels have RICs like `C}KN7309983101`. It is LSEG's own identifier, distinct from MMSI and IMO. |
| ENI | *European Number of Identification* for inland vessels. Accepted by the Vessel Tracking API. |
| PermID | LSEG's permanent entity identifier. |
| TR.* fields | Data-item names for `get_data`, e.g. `TR.AssetLocationLatitude`. `SDate`/`EDate` parameters request history, at day resolution for vessel positions. |
| Search view `VesselPhysicalAssets` | LSEG Search index of 426k vessels holding each vessel's **latest** position, type, flag and identifiers. Supports filters, navigators (facet counts) and `top + skip ≤ 10,000`. |
| Navigator | A Search facet: counts per value of a property, e.g. vessel type. |
| Vessel Tracking API | A separate LSEG REST/WebSocket product with its own key. History covers only the last 24 h. |
| Shared / reassigned MMSI | MMSIs are not unique over time or across units. One MMSI matched 25 RICs, and another moved to a different ship. Identity joins need position-time checks. |

## 14. Chronological account of the work

**Step 2: data foundation (2026-11-23).**

1. **Set-up.**
   - The repo was a bare uv template.
   - Created `context.md` and stored the commit rule in agent memory.
   - Created the `data/`, `scripts/`, `notebooks/` and `docs/` layout, and git-ignored the large
     data folders.
2. **xView3 access.**
   - Deep links returned 404. Reading the site's code showed a single-page app with a Cognito
     login and per-user signed links.
   - Searched Hugging Face, GitHub, Zenodo and other mirrors. SARFish has all the imagery publicly;
     no public copy of the labels exists.
3. **SSDD.** Wrote a resumable, checksum-verified Google Drive downloader. Downloaded and extracted
   the archive, then inspected its real structure (four variants, `_GT` folders with drawn labels).
4. **Map and reveal sources.**
   - Queried the CDSE catalogue anonymously and measured SCS coverage.
   - Confirmed anonymous Planetary Computer access.
   - Read GFW's pages and found the CC BY 4.0 figshare data.
   - Located the DMA and NOAA raw AIS archives.
5. **SSDD validation.** Inventory, box table and overlays. Found the split leakage, the
   false-colour images and the absence of ship-free images.
6. **xView3 downloads**, after a team member logged in.
   - Verified the label checksums.
   - Chose 3 validation scenes for regional variety.
   - Downloaded them with SHA-1 verification and safe extraction.
7. **GFW.**
   - Downloaded the tiles and the detections table with MD5 checks.
   - Validated the tiles and found the lon-first ids.
   - Extracted the SCS subset and per-scene counts.
8. **xView3 validation.**
   - Found that train has no boxes and that `confidence` restates `is_vessel`.
   - Found the pixel-corner convention.
   - 0 labels outside their image, 0 bad boxes. Overlays reviewed by eye.
9. **Reveal feasibility.**
   - Historical SCS scenes exist on Planetary Computer and CDSE.
   - Read a 30 km window anonymously; GFW's detections overlay real targets.
   - 65 of the 66 detections in that window are unmatched, which illustrates the AIS-coverage
     caveat.
10. **Documentation and quality.**
    - Wrote the `docs/` files, `data/README.md`, `data/sources.json`, the notebook and the tests.
    - Kept row-level xView3 labels out of Git.
    - Made one commit, `8e24e7b`, on `step2-data-foundation`; not pushed, no AI attribution.

**LSEG Workspace (Eikon) investigation (2026-11-23).**

11. **Access.**
    - Found Workspace running locally, with its data proxy ready.
    - Added the `lseg-data` SDK (optional group) and a standard-library `.env` loader.
    - Found `.env` staged in Git: unstaged it, git-ignored it, and added `.env.example`.
12. **Exploration.**
    - Opened a desktop session.
    - Mapped the vessel-search fields (222 properties).
    - Validated field names against real responses.
    - Found the day-only date resolution and the 10,000-result cap.
13. **Real-vessel tests.**
    - Took the MMSIs GFW matched in our Hainan 2019 and North Sea 2020 scenes and resolved them to
      LSEG ids.
    - Pulled their history around the acquisition times and compared it with GFW's positions.
    - Measured coverage in the SCS, the North Sea and two dense reference straits.
    - Reconstructed a recent AIS layer off Hainan.
14. **Probe and documentation.**
    - Wrote `scripts/probe_lseg_shipping.py`, the helpers, 13 tests, and
      `docs/lseg_shipping_access_assessment.md`.
    - Ran the probe 3 times.
    - The Vessel Tracking API returns 401 without a key; it was not tested.
15. **Documentation restructure.** Rewrote this file, so that every data source states what it
    contains, what it is for and whether it is useful, and every repository file is explained.
    Aligned `README.md`, `data/README.md`, `docs/data_sources.md`,
    `docs/map_reveal_data_assessment.md` and `docs/validation_results.md` with the same approach.

**Deliberately not done yet:**
- No model training, feature engineering or data split.
- No CFAR or pipeline code, backend or frontend.
- No CDSE account or GFW token.
- Shoreline files not extracted.

## 15. Progress log

- 2026-11-23: Created `context.md`; the repo was a bare uv template. Saved the commit rule to agent
  memory.
- 2026-11-23: Analysed the xView3 site (single-page-app 404s, Cognito login, signed links). Found
  the SARFish imagery mirror; the labels are gated.
- 2026-11-23: Downloaded, extracted and validated SSDD; found the duplicate leakage.
- 2026-11-23: Verified CDSE (anonymous catalogue) and Planetary Computer (anonymous token) for the
  SCS.
- 2026-11-23: Downloaded and validated the GFW figshare data; extracted the SCS subset.
- 2026-11-23: User logged in to xView3. Downloaded and validated 3 validation scenes (pixel-corner
  convention found).
- 2026-11-23: Planetary Computer window plus GFW overlay proves the reveal route. Wrote docs,
  inventories, notebook and tests. Commit `8e24e7b`.
- 2026-11-23: Added the glossary, dataset contents and detailed work account. Verified the
  user-added `GRD_validation.csv` and `validation.tar` against the official SHA-1 checksums.
- 2026-11-23: LSEG/Eikon investigation. The desktop session works, and `.env` was secured.
  - Fields, history (whole days only, back to ≥ 2010), area search (latest positions only),
    limits and fishing coverage were measured.
  - Verdict: recent dates only, as an incomplete commercial-fleet layer.
- 2026-11-23: Restructured `context.md` (each source: contents, use, usefulness; every repository
  file explained; current status up front) and aligned the other docs.
- 2026-11-24. Audited the source registry, original data, probe receipts, notebooks and actual
  GSRAI loader families. Implemented separate catalogue, raster, training, position, registry
  and prediction readers. Only verified raster substitutes may complete missing bands or
  windows. The source and compatibility tables are in [the architecture guide](docs/data_layer.md).
- 2026-11-24. Added `data/loading.toml`, the pinned pilot manifest and the package CLI.
  Migrated the notebook, PC preview, LSEG lookup and GFW extraction. Updated the archive
  downloaders, transport, storage, READMEs, source registry and map assessment. Shapely is
  the added direct dependency. CSV and manifest Git attributes preserve pinned bytes across
  operating systems.
- 2026-11-24. Verified all training families and the explicit weak-label product. Both pre-existing
  GFW whole-scene extracts agreed with the publisher CSV on all seven lookup fields. In an
  80 × 80 overlap the stored Hainan crop and PC range read agreed in all 6,400 native samples
  for each band. Saved separate SHA-256 pins for the VV and VH crops. A fresh temporary
  checkout fetched the georeferenced windows, then replayed them using only its cache.
- 2026-11-24. The requested North Sea zone had partial raster coverage, a complete two-band
  preview and eight selected position reports. Hainan had six published predictions and an
  empty position query. Both studies returned insufficient AIS information. Required next
  evidence includes validated SCS radiometry, independent evaluation and entitled historical
  position observations with a defensible reception estimate.
- 2026-11-24. All 79 credential-independent tests passed. Ruff, Black for 39 Python files,
  mypy for 22 package files, the offline uv lock check and the whitespace check passed.
  The six inspection notebook code cells ran with local imagery and again using inventories
  only. The SSDD archive passed its recorded SHA-256. Live metadata rechecks confirmed
  Figshare, PC and the CDSE catalogue. The Workspace desktop proxy was unavailable.
