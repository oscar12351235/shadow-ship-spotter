# SSS: Shadow Ship Spotter — Project Context

> Living document: lets another developer or coding agent continue without the original
> conversation. Update after meaningful milestones. Status labels:
> ✅ done & verified · 🔄 in progress · 📋 planned · ❌ attempted, failed · ❓ unverified.
> New readers: start with §14 (glossary), §15 (what each downloaded dataset contains) and §16
> (detailed account of work done). Detailed material is referenced, not copied: `docs/data_sources.md`, `docs/validation_results.md`,
> `docs/map_reveal_data_assessment.md`, `data/README.md`, `data/sources.json`.

_Last updated: 2026-11-23 (end of step 2 work session)_

## 1. Purpose and users

University ML project intended to become a functioning application. Detect vessels in satellite
radar (Sentinel-1 SAR) imagery and compare positions with AIS (Automatic Identification System)
data, revealing vessels detected in imagery that cannot be matched to available AIS records.

- Target geography: **South China Sea (SCS)**, particularly fishing activity. Modelling may use
  labelled imagery from other regions; SCS application requires separate validation.
- Users: fisheries authorities prioritising monitoring/investigations under a limited budget.
- An unmatched detection does **not** establish nationality, illegal fishing or deliberate AIS
  disabling. Always distinguish: (a) reliable AIS match, (b) unmatched under a documented
  matching process, (c) matching information unavailable/insufficient.

## 2. Central user journey (final application — NOT implemented yet)

1. Open an interactive map. 2. Select a date (selector exposes available acquisitions and their
times; "no imagery available" when none). 3. Choose an area: draw/select a zone or just pan/zoom —
explicit zone takes precedence, otherwise the viewport is the AOI. 4. Map shows AIS-visible
vessels for that area and observation time. 5. Prominent **"Reveal hidden vessels"** button.
6. App retrieves suitable SAR imagery and runs our pipeline, or loads clearly identified previous
results. 7. Compares detections with AIS and reveals additional candidates in a distinct colour
(AIS layer retained; layers toggleable). 8. Clicking a detection shows: image patch, coordinates,
acquisition timestamp, model name/version, score, AIS matching status + supporting info,
computed-on-demand vs loaded-from-previous-run.

Counts shown: AIS-visible vessels, satellite detections, matched, unmatched candidates,
insufficient-information cases. Changing date/area updates or invalidates results. Rules:
AIS and detections must refer to compatible observation times (an image is a snapshot); missing
imagery ⇒ "no imagery available", never "no hidden vessels"; insufficient AIS coverage must not
turn detections into confirmed unmatched vessels; a layer built from AIS-matched SAR detections
(e.g. GFW) must be labelled as such, not as an AIS feed. Real data + real pipeline outputs;
loading/progress/error/no-data states.

## 3. Scope, modelling plan, architecture

- Step 1 (scope) ✅ done before this file existed.
- **Step 2 (data + reproducible foundation) — this session.** No model training, no large feature
  set, no final split (deliberately).
- Modelling plan 📋: CFAR-style candidate detector → classifier; compare (A) traditional ML on
  descriptors (local contrast, brightness stats, texture, shape) vs (B) CNN on patches, with
  identical train/val/test partitions; then evaluate the complete pipeline on held-out scenes.
- Architecture 📋: Python backend (data access, pipeline, matching, API), React frontend map
  (MapLibre/Leaflet); Node.js only if useful.

## 4. Repository and environment

- Python 3.12 via **uv** (`./install.sh` / `install.bat` → `uv sync --python 3.12 --all-groups`).
  Dependencies added this session: `rasterio` (GDAL 3.12 wheels), `zarr` 3, `pyarrow`; dev:
  `ipykernel`. Tools: pytest, black, ruff (config moved to `[tool.ruff.lint]`), mypy.
- macOS dev machine (Apple silicon). RAR extraction relies on libarchive `tar` (macOS/Windows 10+).
- Layout:
  ```
  src/shadow_ship_spotter/paths.py           canonical data paths
  src/shadow_ship_spotter/data/download.py   stdlib download/resume/Google-Drive/checksum helpers
  src/shadow_ship_spotter/data/ssdd.py       SSDD COCO/VOC parsing, IoU matching, dHash
  scripts/download_ssdd.py                   SSDD download + sha256 + extract
  scripts/validate_ssdd.py                   SSDD inventory/validation/overlays
  scripts/download_xview3_scenes.py          xView3 scenes from user's signed link lists (SHA-1)
  scripts/validate_xview3.py                 xView3 label files + scene/label correspondence
  scripts/download_gfw_paolo2024.py          GFW figshare files (MD5)
  scripts/validate_gfw_tiles.py              GFW detection tiles inventory/validation
  scripts/summarise_gfw_sar_detections.py    GFW SAR detections → SCS subset + per-scene counts
  scripts/fetch_pc_s1_window.py              Planetary Computer S1 window + GFW overlay (feasibility)
  notebooks/01_data_inspection.ipynb         inspection notebook (executes cleanly)
  data/{sources.json,README.md,inventory/,splits/}   tracked; data/raw, data/processed ignored
  docs/{data_sources,validation_results,map_reveal_data_assessment}.md, docs/figures/*.png
  tests/test_data_helpers.py                 unit tests for helpers (6 tests pass)
  ```

## 5. Data sources — status summary (details: `docs/data_sources.md`)

| Source | Status | Serves | Local path |
|---|---|---|---|
| **xView3-SAR** labels (train, validation, scene mapping, SARFish GRD_train + GRD_validation, shoreline validation archive) | ✅ downloaded, SHA-1 = official (shoreline not yet extracted) | training/eval | `data/raw/xview3/` |
| **xView3-SAR** scenes b1844cde847a3942v, fc2f57371370c521v, fe6a8d80fb5ebb8ev (validation) | ✅ downloaded + validated | training/eval | `data/raw/xview3/scenes/`, archives kept |
| **Official SSDD** (`Official-SSDD-OPEN.rar`, 1.04 GB, sha256 daf79e02…) | ✅ downloaded + validated | benchmark only | `data/raw/ssdd/` |
| **GFW detection tiles** (figshare, CC BY 4.0) | ✅ downloaded + validated | classifier stage | `data/raw/gfw_paolo2024/training/` |
| **GFW SAR detections 2017–2021** (`industrial_vessels_v20240102`, CC BY 4.0) | ✅ downloaded; SCS subset extracted | map/reveal comparison layer (GFW predictions + GFW AIS matching) | `data/raw/gfw_paolo2024/analysis/`, `data/processed/gfw_sar_detections_scs.parquet` |
| **Planetary Computer** `sentinel-1-grd` | ✅ anonymous access proven (window read) | reveal imagery | `data/raw/planetary_computer/` |
| **CDSE** | ✅ catalogue (anonymous) / 📍 download needs account | imagery archive, footprints | — |
| **SARFish** (HF, public) | 📍 imagery mirror of all xView3 scenes; labels only via xView3 login | training/eval | — |
| **GFW API / Data Download Portal** | 📍 needs free token; non-commercial | AIS map (SCS), recent SAR detections | — |
| **DMA raw AIS** (Danish waters) | 📍 public S3; 2020 monthly ~16 GB, recent daily ~0.7 GB | raw-AIS matching validation | — |
| NOAA MarineCadastre AIS (US) | 📍 listing verified | raw AIS (US) | — |
| LS-SSDD-v1.0 | ❓ not investigated (not needed now) | — | — |

Disk use: data/raw ≈ 16 GB (xView3 12 GB incl. 3.9 GB of archives), data/processed ≈ 70 MB.

## 6. Key findings (verified this session)

- **xView3 access works with an account**. The site is a Nuxt SPA; direct deep links (`/signup`,
  `/download-links`) return 404 from the server — likely the earlier "error pages". A team member
  logged in on 2026-11-23 and saved labels + signed link lists (expire after hours). An automated
  probe of the authenticated download API by the agent was (rightly) blocked; nothing was done
  with credentials by the agent.
- **xView3 data facts**: VV/VH float16 dB GeoTIFFs in UTM, 10 m, ~28k×24k px; labels carry no
  timestamps and no raw AIS; acquisition time from ESA name mapping; `detect_lat/lon` is the
  **upper-left corner** of the labelled pixel (0 m median error); train.csv has **no boxes**,
  source always `ais`, and its `confidence` is a deterministic function of `is_vessel`;
  validation labels are human-reviewed with boxes. All 2,307 labels of the 3 scenes are in-raster,
  boxes valid.
- **SSDD**: 1,160 images / 2,587 boxes (COCO == VOC exactly); official split 928/232 by id
  suffix; four variants share byte-identical images; `*_GT` folders have labels burnt in
  (excluded); **22 exact-duplicate groups (47 images), 10 across the official split, + 4
  cross-split near-duplicates** → official split leaks; 34 false-colour images; no georeference,
  sensor or parent-scene metadata → cannot be joined to AIS; benchmark only.
- **GFW detection tiles**: `detect_id = scene;LON;LAT` (lon first, undocumented); 6,578 parent
  scenes; band order/scaling undocumented; only 23 tiles in SCS; GFW train/test share 2 scenes.
- **GFW SAR detections**: 23.1 M rows; SCS box 1.81 M rows / 17,529 scenes, 56 % unmatched;
  timestamp = scene acquisition time. These are GFW model predictions, not ground truth/raw AIS.
- **Reveal route proven**: historical SCS scenes referenced by GFW exist on PC and CDSE; PC COG
  window read anonymously in ~10 s; GFW detections overlay small bright targets
  (`docs/figures/scs_reveal_feasibility.png`). In that Hainan window 65/66 GFW detections are
  unmatched — GFW states AIS reception around China/SE Asia improved markedly only ~2022, so
  "unmatched" there is partly a coverage effect.

## 7. Decisions (and alternatives)

| Decision | Why | Alternatives considered |
|---|---|---|
| xView3 validation scenes are the primary modelling data | same sensor/product as application, full scenes, human-reviewed labels, real geo/time | SSDD only (no geo, mixed sensors), SARFish (labels gated anyway) |
| Keep SSDD as secondary benchmark (BBox, COCO) with duplicate-aware split | small, quick, literature comparability for descriptor-vs-CNN | drop SSDD; LS-SSDD |
| Add GFW detection tiles for the classifier stage | real S1, global, scene-grouped, vessel/non-vessel | — |
| Demo Route A: PC imagery + GFW SAR table (same scene) | no account needed, SCS coverage, exact time alignment | CDSE (account), GFW API (token) |
| Downloaded 3 scenes, not full partitions | avoid 123+ GB; prove access/format | full validation set |
| Row-level xView3 labels never committed | xView3 terms (no redistribution); repo has a GitHub remote | committing inventories |
| Stdlib downloader instead of gdown/requests | fewer deps, resumable, checksum-verified | gdown, aria2 |

## 8. Files created/modified this session (and why)

- Modified: `.gitignore` (ignore `data/raw/`, `data/processed/`, `*.part`), `pyproject.toml`
  (deps rasterio/zarr/pyarrow, dev ipykernel, description, ruff lint section), `uv.lock`,
  `README.md` (project description + data docs links).
- Created: everything listed in §4 plus `docs/*.md`, `docs/figures/*`, `data/inventory/*`,
  `data/sources.json`, `data/README.md`, `data/splits/README.md`.
- Persistent agent memory (outside repo): never add AI co-author lines to commits; commit only
  for significant changes.

## 9. Reproduction

See `data/README.md` (exact commands for every download/extraction/validation step).

## 10. Checks performed (actual results in `docs/validation_results.md`)

✅ SSDD structural + COCO/VOC + split + duplicate + channel checks; overlays reviewed visually.
✅ xView3 label-file checks; per-scene raster/label correspondence; all 3 overlays reviewed by eye
(Lagos and North Sea clear; Adriatic: small ~20–27 m fishing vessels are barely separable from
clutter, and in one crop the brightest VH return sits just below the labelled box). ✅ GFW tiles checks + gallery.
✅ GFW detection table summary. ✅ PC window read + overlay. ✅ `pytest` 6/6, `ruff`, `mypy src`
clean; notebook executes via nbconvert.

## 11. Problems encountered

- xView3 pages 404 on direct URL → diagnosed as SPA routing; resolved by in-app login (user).
- Agent's probe of xView3 authenticated API blocked by permission policy → not retried.
- GFW tile ids parsed as lat;lon gave 238° errors → discovered lon;lat order → fixed.
- xView3 pixel→geo check showed constant 7.09 m with pixel centres → corner convention → fixed.
- Polars → parquet needed pyarrow → added. zarr 3 string dtype cast error → fixed in script.
- Planetary Computer id lookups failed with the ESA suffix → PC ids drop it → fixed.

## 12. Remaining uncertainties / blockers

- GFW tile band order / dB scaling; GFW matching algorithm specifics; AIS reception quality in SCS
  by year (needed for "insufficient information" status).
- PC data are uncalibrated DN in radar geometry: calibration (σ⁰) and geocoding steps needed
  before applying anything trained on xView3 dB rasters.
- Raw AIS for the SCS requires a GFW API token (someone must register; never commit the token);
  point-level track availability via the API not yet confirmed.
- xView3 signed links expire (2026-11-23 21:04 UTC for the current lists); more scenes need a fresh
  login + new link lists. SARFish/xView3 `public` labels not downloaded.

## 13. Next steps (concrete)

1. **Inspection**: review more xView3 chips per class/confidence (small fishing vessels are faint);
   decide SSDD false-colour handling; manually review SSDD near-duplicate clusters.
2. **Splitting** (step 3): SSDD duplicate-cluster grouping → `data/splits/ssdd_groups.csv` and a
   versioned split; xView3 scene-level split (decide whether to fetch more validation scenes and/or
   selected train scenes while links are valid); GFW tiles grouped by scene.
3. **Pipeline foundations**: chip extraction from xView3 (positives from labels, negatives from
   sea areas away from labels), CFAR baseline on dB rasters with land masking (bathymetry/owiMask).
4. **Map/reveal**: build a PC STAC scene index for a chosen SCS AOI/date range; pick Route A demo
   scene(s) from `data/inventory/gfw_sar_scs_scenes.csv` (prefer dates with better AIS coverage);
   implement σ⁰ calibration for PC data; request a GFW API token for Route B.

## 14. Glossary — acronyms and technical terms

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

## 15. Downloaded datasets — what each one is and what it contains

All of this lives under the git-ignored `data/raw/` (about 16 GB in total). Sizes are on-disk.

### 15.1 xView3-SAR — `data/raw/xview3/` (12 GB)

**What it is.** The official xView3 challenge dataset (DIU + GFW, 2021; CC BY-NC-SA 4.0). It covers 754 Sentinel-1 IW GRDH scenes from 2020, around Europe (North Sea, Adriatic, Norway, Iceland) and West Africa. Each object label is AIS-informed, and in the validation partition also human-reviewed. There is no SCS coverage. Obtained via a team member's login on 2026-11-23.

| File | Content |
|---|---|
| `train.csv` (11 MB, 64,113 rows, 554 scenes) | One row per object, labels derived from AIS only. **No boxes.** `confidence` duplicates `is_vessel` (HIGH = non-vessel, MEDIUM = vessel, LOW = unknown). |
| `validation.csv` (3.5 MB, 19,224 rows, 50 scenes) | Human-reviewed labels with boxes for 99%. The best-quality labels we have. |
| `ESA_xView3_sceneName_mapping.csv` (754 rows) | Maps the xView3 scene id (e.g. `fc2f57371370c521v`; the last letter t/v/p = train/validation/public) to the ESA product name and partition (554 train, 50 validation, 150 public). **The only source of acquisition times.** |
| `GRD_train.csv` (64,054 rows), `GRD_validation.csv` (19,222 rows) | SARFish versions of the same labels, expressed in the pixel grid of the *original ESA GRD product* (`GRD_product_identifier`) and with two distance-from-shore columns. Only usable with SARFish imagery, which we have not downloaded. `GRD_validation.csv` was added by the user later; its SHA-1 matches. |
| `validation.tar` (83.9 MB) | This is `shoreline/validation.tar.gz` (gzip despite the name; SHA-1 matches). It holds 50 `<scene>_shoreline.npy` files, one per validation scene, which the xView3 metric uses to score close-to-shore detections. **Not extracted or inspected yet.** |
| `tiny.txt`, `validation.txt`, `train.txt` | Personal **signed download links** (aria2 format: one URL line plus a `checksum=sha-1=` line per scene). They expire, and must never be committed or shared. |
| `archives/<scene>.tar.gz` (3 files, 3.9 GB) | Original scene archives, kept for provenance; SHA-1 verified. Can be deleted to save space. |
| `scenes/<scene>/<scene>/*.tif` (8 GB) | Extracted scene rasters (see below). |

Label columns (`train.csv` / `validation.csv`):

| Column | Meaning |
|---|---|
| `scene_id` | xView3 scene identifier. |
| `detect_id` | Unique object id. |
| `detect_lat`, `detect_lon` | WGS84 position; **= upper-left corner of the labelled pixel** (we verified this). |
| `detect_scene_row`, `detect_scene_column` | Pixel position in the scene's `VV_dB.tif` / `VH_dB.tif`. |
| `top`, `left`, `bottom`, `right` | Box in pixels (validation only). |
| `is_vessel`, `is_fishing` | True / False / empty. |
| `vessel_length_m` | Length in metres, mostly from AIS where available. |
| `distance_from_shore_km` | Distance to shore; 9999.99 is used as a placeholder in some rows. |
| `confidence` | HIGH / MEDIUM / LOW. |
| `source` | Where the label came from: `ais`, `manual`, or `ais/manual`. |

There are no timestamps and no AIS messages in the labels.

Per-scene rasters, all in the same UTM projection per scene, float16, nodata −32768:

| File | Resolution | Content |
|---|---|---|
| `VV_dB.tif`, `VH_dB.tif` | 10 m, about 30,000 × 25,000 px (1.4 GB each) | Radar backscatter in dB for the two polarisations. The main inputs. |
| `bathymetry.tif` | 500 m | Sea depth / land elevation (source per xView3 docs, not re-checked). |
| `owiMask.tif` | 500 m | Sentinel-1 OCN land/ice/validity mask. Code meanings not inspected yet. |
| `owiWindSpeed.tif`, `owiWindDirection.tif`, `owiWindQuality.tif` | 500 m | OCN wind field. Wind drives sea clutter, which is useful context for CFAR. |

Downloaded scenes (all from the validation partition):

| Scene | Place | Acquisition (UTC) | CRS | Labels | Vessel / fishing / non-vessel / unknown |
|---|---|---|---|---|---|
| `b1844cde847a3942v` | Lagos coast, Nigeria | 2020-01-26 05:29:56–05:30:25 | EPSG:32631 | 722 | 489 / 5 / 226 / 2 |
| `fc2f57371370c521v` | North Sea, Danish/German waters | 2020-09-28 17:18:00–17:18:31 | EPSG:32632 | 1,079 | 287 / 38 / 751 (visually, largely clusters at offshore wind farms) / 3 |
| `fe6a8d80fb5ebb8ev` | Adriatic | 2020-05-20 05:11:17–05:11:42 | EPSG:32633 | 506 | 362 / 50 / 80 / 14 |

In this table, "vessel" means non-fishing or unclassified vessels.

### 15.2 Official SSDD — `data/raw/ssdd/` (2.1 GB: 1.0 GB RAR + extracted copy)

**What it is.** SAR Ship Detection Dataset, official release (Zhang et al., Remote Sensing 2021; Apache-2.0). It has 1,160 small SAR image chips (about 500 × 350 px, 8-bit JPEG) containing 2,587 ships. Per the paper, the chips come from RadarSat-2, TerraSAR-X and Sentinel-1 at 1–15 m resolution; the per-image sensor is not recorded. It has **no coordinates, no timestamps and no parent-scene ids**, so it serves only as a modelling benchmark.

- `download/Official-SSDD-OPEN.rar`: the original archive (1,043,241,197 B, sha256 recorded in `data/sources.json`).
- `extracted/Official-SSDD-OPEN/` contains four label variants of the **same 1,160 images**:
  - `BBox_SSDD/`: boxes, in `coco_style/` (`annotations/{train,test,test_inshore,test_offshore}.json` + `images/{train,test,...}/NNNNNN.jpg`) and `voc_style/`. **This is the one we use.**
  - `RBox_SSDD/`: rotated boxes (VOC `<rotated_bndbox>` with centre, width, height, angle θ and 4 corners).
  - `PSeg_SSDD/`: polygon outlines of ships, plus mask images.
  - `BBox_RBox_PSeg_SSDD/`: all three label types together (COCO + VOC).
- `voc_style/` layout:
  - `Annotations/` (all) and `Annotations_{train,test,test_inshore,test_offshore}/`: one XML per image.
  - `JPEGImages*/`: the original images, split the same ways.
  - `JPEGImages_*_GT*/`: **copies with labels drawn onto the pixels. Never train on these.**
  - `ImageSets/Main/*.txt`: the official split lists.
  - `*_labels.csv`: text dumps of all box types.
  - `*.py` analysis scripts and `*.png` statistics plots from the authors. We have not run them.
- Official split: 928 train / 232 test (46 inshore, i.e. near coast or port, and 186 offshore). An image is in test when its id ends in 1 or 9.
- Our findings: COCO and VOC agree exactly. 22 groups of byte-identical images (47 files), 10 of them straddling the official split, plus 4 near-duplicate pairs across the split, so **the official split leaks**. 34 images are false-colour composites. Median box is 22 × 29 px.

### 15.3 GFW detection tiles — `data/raw/gfw_paolo2024/training/` (145 MB zip + 187 MB extracted)

**What it is.** Training data from GFW's Nature 2024 paper (Paolo et al.; figshare, CC BY 4.0). It is a Zarr store `detection_tiles_v4.zarr` with 11,965 small Sentinel-1 patches, each labelled vessel / not vessel. It suits our classifier stage: deciding whether a candidate patch is a vessel.

| Array | Shape / type | Meaning |
|---|---|---|
| `tiles` | (11965, 80, 80, 2) float16, values 0–255 | Two radar bands. **Band order and scaling are undocumented.** |
| `presence` | int8 | 1 = vessel (6,574), 0 = no vessel (5,391). |
| `length_m` | float16 | Vessel length; 0 for 1,265 positives (unknown). |
| `weight` | float16 | Training sample weight. |
| `detect_lat`, `detect_lon` | float32 | Position of the tile centre. |
| `detect_id` | string | `<ESA product name>;<LON>;<LAT>`. **Longitude comes first**; this gives the parent scene and acquisition time. |

- `detection_tiles_v4.zarr.index` holds GFW's own partitions: `test/base`, `test/null`, `train/0..4` (5 cross-validation folds), `train/all`, `train/null`. The meaning of "null" is not documented. GFW's train and test indices share 2 scenes.
- Coverage: global, 6,578 scenes, 2017-01-01 to 2021-07-15. Only 23 tiles fall in the SCS box.

### 15.4 GFW SAR vessel detections 2017–2021 — `data/raw/gfw_paolo2024/analysis/` (1.6 GB zip)

**What it is.** `industrial_vessels_v20240102.csv`: 23,088,625 vessel detections that **GFW's own models** found in Sentinel-1 images, each joined to AIS by **GFW's matching algorithm** (figshare, CC BY 4.0). It is neither ground truth nor raw AIS. It covers GFW's study area (coastal waters, about 15% of the ocean) from 2017 to 2021.

| Column | Meaning |
|---|---|
| `scene_id` | ESA product name. |
| `timestamp` | Scene acquisition time, the same for every detection in a scene. |
| `lat`, `lon` | Detection position. |
| `year` | Year of detection. |
| `mmsi` | AIS id of the matched vessel; empty when unmatched. |
| `matching_score` | Strength of the AIS match. |
| `fishing_score` | 0–1 likelihood of being a fishing vessel. |
| `length_m` | Length estimated by GFW's model. |
| `matched_category` | `matched_fishing` / `matched_nonfishing` / `matched_unknown` / `unmatched`. |
| `overpasses_2017_2021` | Number of Sentinel-1 images of that spot over the period. |

- Our SCS subset is `data/processed/gfw_sar_detections_scs.parquet`: 1,812,280 rows in 17,529 scenes, 56% unmatched.
- The per-scene summary is `data/inventory/gfw_sar_scs_scenes.csv`, used to choose demo dates and areas.
- Both GFW records also include a `README.md` describing every file.

### 15.5 Planetary Computer feasibility window — `data/raw/planetary_computer/S1B_IW_GRDH_1SDV_20190318T104813_…_01CDA6/` (16 MB)

**What it is.** A 3072 × 3072 px (about 30 km) cut-out of a real 2019-03-18 Sentinel-1 scene off south-east Hainan (centred 18.45°N, 110.45°E). It was read anonymously from Planetary Computer to prove the reveal route works.

| File | Content |
|---|---|
| `window_vv.tif`, `window_vh.tif` | uint16 DN in radar geometry. Not calibrated and not georeferenced; geolocate via the item's GCPs. |
| `window_meta.json` | Window offsets, full-scene size, GCP count. |
| `item.json` | STAC metadata: footprint, times, orbit, asset links (unsigned). |

### 15.6 Not downloaded (located only)

SARFish imagery (Hugging Face), CDSE products (account needed), GFW API data (token needed), DMA raw AIS (Danish waters), NOAA AIS (US waters), LS-SSDD. See §5 and `docs/data_sources.md`.

## 16. What has been done so far — detailed account (step 2, 2026-11-23)

1. **Repository and set-up.** Inspected the repo: a bare uv scaffold with no data conventions. Created `context.md`. Stored the agent memory rule (no AI co-author lines, few commits). Created the `data/`, `scripts/`, `notebooks/` and `docs/` layout, and git-ignored `data/raw` and `data/processed`.
2. **xView3 access investigation.**
   - The homepage works, but deep links return 404. Reading the site's JavaScript showed a single-page app with Cognito login, and download links generated per user by an AWS API.
   - The agent's direct probe of that authenticated API was blocked by permissions and not retried.
   - Searched Hugging Face, GitHub code search, Zenodo, the reference-repo issues and other mirrors. Found SARFish: a public copy of all xView3 imagery, but with login-gated labels. No public copy of the labels exists.
3. **SSDD acquisition.**
   - Wrote a resumable, checksum-verified Google Drive downloader.
   - Downloaded `Official-SSDD-OPEN.rar` (995 MB), recorded its SHA-256, and extracted it with the system's libarchive `tar`.
   - Inspected the real archive structure: four variants with identical images, and the `_GT` folders with drawn labels.
4. **Map/reveal data investigation.**
   - Queried the CDSE catalogue anonymously and measured SCS coverage for Sep–Oct 2025.
   - Confirmed Planetary Computer's anonymous access and SCS items.
   - Read GFW's datasets, API-terms and SAR-release pages.
   - Found the CC BY 4.0 figshare records of the GFW paper, which need no login.
   - Located the DMA and NOAA raw AIS archives and checked their structure and sizes.
5. **SSDD validation.** `scripts/validate_ssdd.py` produces the inventory, the per-box table and the validation report, and draws overlays. It found the split leakage, the false-colour images and that there are no negatives. The overlays were reviewed by eye.
6. **xView3 downloads**, after the user logged in and saved labels and link lists:
   - Verified all label SHA-1s against the values published on the download page.
   - Chose 3 validation scenes for regional variety and label quality.
   - Downloaded them with a script that verifies each SHA-1 before safe extraction (about 4.1 GB of archives).
7. **GFW downloads.** Downloaded the detection tiles and the 1.7 GB detections table with MD5 verification. Validated the tiles, discovering the lon-first id order. Extracted the SCS subset and per-scene summary of the detections.
8. **xView3 validation.**
   - Checked the label files: found no boxes in train and the confidence/is_vessel artefact.
   - Checked every label of the 3 scenes against its raster: found the upper-left-corner convention, with 0 labels outside and 0 bad boxes.
   - Drew overlays for all 3 scenes and reviewed them; small Adriatic fishing boats are hard to see.
9. **Reveal feasibility.**
   - Confirmed that historical SCS scenes cited by GFW exist on both Planetary Computer and CDSE.
   - Read a 30 km window anonymously and overlaid GFW's detections for the same scene. The circles fall on real targets.
   - The 65/66 unmatched rate there illustrates the AIS-coverage caveat.
10. **Documentation and code quality.**
    - Wrote `docs/data_sources.md`, `docs/validation_results.md`, `docs/map_reveal_data_assessment.md`, `data/README.md`, `data/splits/README.md`, `data/sources.json` and the inspection notebook.
    - Added unit tests; ruff, black, mypy and pytest pass.
    - Kept row-level xView3 labels out of Git for licence reasons.
11. **Commit.** A single commit on branch `step2-data-foundation`, not pushed and without AI attribution. It was amended to include this explanatory addition, so the commit count stays at one.

**Deliberately not done yet:**
- No model training, feature engineering or train/val/test split.
- No CFAR or pipeline code, no backend or frontend.
- No CDSE account or GFW token used.
- Shoreline `.npy` files not extracted.

## Progress log

- 2026-11-23 — Created `context.md`. Repo was a bare uv scaffold. Saved agent memory rule about commits.
- 2026-11-23 — xView3 site analysed: SPA deep-link 404s; Cognito login; signed links. SARFish
  imagery mirror found (public HF), labels gated. No public label copies found.
- 2026-11-23 — SSDD downloaded (sha256 recorded), extracted, validated; duplicate leakage found.
- 2026-11-23 — CDSE catalogue (anonymous) and Planetary Computer (anonymous SAS) verified for SCS.
- 2026-11-23 — GFW figshare data found (CC BY 4.0, no login): detection tiles + SAR detections
  table downloaded (MD5), validated, SCS subset extracted.
- 2026-11-23 — User logged in to xView3 and saved labels + link lists; 3 validation scenes
  downloaded (SHA-1), validated (pixel corner convention found).
- 2026-11-23 — PC window read + GFW overlay proves Route A; docs, inventories, notebook, tests written.
- 2026-11-23 — Added glossary (§14), dataset contents (§15), detailed work account (§16). Verified user-added `GRD_validation.csv` and `validation.tar` (= shoreline/validation.tar.gz) against official SHA-1.
