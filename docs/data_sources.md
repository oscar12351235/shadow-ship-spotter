# Data sources: what each is, what it contains, what it is for, whether it is useful

_Status verified on 2026-11-23._

The [2026-11-24 audit and product matrix](data_layer.md) records the latest live checks and
specifies which of these sources the implemented data layer can use.

**How this file relates to the others:**
- `context.md` §5 has the same per-source summary in the context of the whole project.
- This file adds **access mechanics, licences, technical details and citations**.
- Machine-readable registry (URLs, sizes, checksums, dates): [`data/sources.json`](../data/sources.json).
- Check results: [`validation_results.md`](validation_results.md).
- What the map and "Reveal" feature need: [`map_reveal_data_assessment.md`](map_reveal_data_assessment.md).
- LSEG evidence: [`lseg_shipping_access_assessment.md`](lseg_shipping_access_assessment.md).

## 0. The three data needs every source is judged against

| Need | What it means | Sources that meet it |
|---|---|---|
| **A. Training and evaluation** | Radar images with labelled vessels | xView3-SAR ✅ (primary), GFW detection tiles ✅ (classifier stage), SSDD ✅ (benchmark only) |
| **B. Initial AIS map** | Vessel positions with timestamps for the chosen area and moment | No complete SCS source verified. LSEG Workspace provides a licensed sample. GFW point-level API entitlement is unverified. Published GFW detections have a separate comparison layer. |
| **C. Reveal** | C1: the Sentinel-1 image and its acquisition time. C2: AIS close to that time for matching | C1: Planetary Computer ✅, CDSE ✅/📍. C2: LSEG (recent, partial) ✅, DMA raw AIS (Danish waters) 📍, GFW table as comparison ✅ |

✅ downloaded and validated, or access proven by an actual read · 📍 located, access route
verified, not downloaded · ❌ unavailable · ❓ unverified.

**Usefulness verdicts:** **Essential** · **Useful** · **Limited** · **Not useful now**.

---

## 1. xView3-SAR — **Essential** (Need A) — ✅ labels + 3 scenes downloaded and validated

**What it is.** The dataset of the 2021 xView3 challenge (US Defense Innovation Unit and Global
Fishing Watch) for detecting "dark" fishing vessels.
- 754 full Sentinel-1 IW GRDH scenes from 2020, around Europe and West Africa. **No South China Sea.**
- Partitions:
  - **train**: 554 scenes, AIS-derived labels;
  - **validation**: 50 scenes, human-reviewed labels;
  - **public**: 150 scenes, labels released after the challenge;
  - **tiny**: 7 scenes.

**What it contains.** Per scene, a folder with:
- `VV_dB.tif` and `VH_dB.tif`: calibrated radar brightness in dB, 10 m pixels, about 30,000 × 25,000
  px, UTM projection, float16, nodata −32768.
- Coarse 500 m ancillary rasters: `bathymetry.tif`, `owiMask.tif`, `owiWindSpeed.tif`,
  `owiWindDirection.tif`, `owiWindQuality.tif`.

Per partition, a label CSV with one row per object:
- position (`detect_lat`/`detect_lon` = **upper-left corner** of pixel `detect_scene_row`,
  `detect_scene_column`, verified to 0 m median error);
- box (`top`, `left`, `bottom`, `right`);
- `is_vessel`, `is_fishing`, `vessel_length_m`, `distance_from_shore_km` (9999.99 used as a
  placeholder), `confidence` (HIGH/MEDIUM/LOW) and `source` (`ais`, `manual`, `ais/manual`).

Each file we downloaded, in plain words:

| File | Content | Use | Useful? |
|---|---|---|---|
| `validation.csv` | 19,224 human-reviewed labels for the 50 validation scenes; 99 % have boxes | Ground truth for training and evaluation | **Essential** |
| `train.csv` | 64,113 AIS-only labels for 554 scenes. **No boxes.** `source` is always `ais`, and `confidence` restates `is_vessel` (HIGH ⇔ non-vessel, MEDIUM ⇔ vessel, LOW ⇔ unknown) | Extra, noisier labels if train scenes are downloaded | Useful with caution |
| `ESA_xView3_sceneName_mapping.csv` | xView3 scene id → ESA product name (which encodes the acquisition time) and partition | Acquisition times; finding the same image elsewhere | **Essential** |
| `GRD_train.csv`, `GRD_validation.csv` | SARFish's version of the labels, in the original ESA product's pixel grid | Only with SARFish imagery | Not useful now |
| `validation.tar` (= `shoreline/validation.tar.gz`) | 50 coastline arrays, one per validation scene, used by the xView3 metric to score near-shore detections | The official metric; coastline mask | Limited |
| Link lists (`*.txt`) | Personal signed scene URLs with SHA-1; **expire 2026-11-23 21:04 UTC; never commit** | Downloading more scenes | A tool |
| 3 scenes (`b1844cde847a3942v` Lagos, `fc2f57371370c521v` North Sea, `fe6a8d80fb5ebb8ev` Adriatic) | Full rasters as above (archives 1.26–1.49 GB each, SHA-1 verified; ~2.5 GB unpacked) | Model input, end-to-end tests | **Essential** |

**The labels have no timestamps and no AIS messages.** Acquisition times come from the ESA name,
to the second.

**What we can use it for:** training and evaluating the CFAR → classifier → full-pipeline chain on
the same satellite and product as the application.

**Is it useful?** **Essential.**
- It is the only dataset combining full Sentinel-1 scenes, human-reviewed labels and known
  location and time.
- **Limits:**
  - no SCS;
  - only 3 of 50 validation scenes are downloaded (the full set is ~123 GB);
  - small fishing vessels are faint in the imagery.

**Access:**
- **Site:** https://iuu.xview.us/. It is a Nuxt single-page app, static build 2023-09-29.
- **Why deep links 404:** links such as `/signup` or `/download-links` return HTTP 404 when opened
  directly, because the server has no route for them (routing happens in the browser). Navigating
  inside the app works.
- **Downloading:**
  - Login uses AWS Cognito. The download page then fetches per-user signed links from AWS API
    Gateway.
  - Label CSVs are direct downloads.
  - Imagery comes as per-scene `.tar.gz` with links valid for a few hours (aria2 lists).
- **Our download:** a team member logged in on 2026-11-23 and saved the files to `data/raw/xview3/`.
  All label SHA-1s equal the values on the download page.
- **Reference code:** https://github.com/DIUx-xView/xview3-reference.

**Licence:** CC BY-NC-SA 4.0 ("contains modified Copernicus Sentinel data (2020)").
- Non-commercial; do not redistribute data or download links.
- Row-level labels therefore go only to git-ignored `data/processed/`.
- The tracked artefacts are aggregate statistics and the overlay figures `docs/figures/xview3_*`.
  These are derived works under CC BY-NC-SA 4.0, attributed to xView3 / DIU / GFW.

**Alternative hosting:** SARFish (§12) mirrors all the imagery publicly. No public copy of the
xView3 labels was found on Hugging Face, GitHub code search or Zenodo. `xview3.org`, listed in a
TIB catalogue entry, does not resolve.

## 2. Official SSDD — **Limited** (Need A, benchmark only) — ✅ downloaded and validated

**What it is.** The *SAR Ship Detection Dataset*: 1,160 small radar image chips cut around ships,
with 2,587 ship boxes.
- Source satellites: RadarSat-2, TerraSAR-X and Sentinel-1, at 1–15 m resolution (per the paper).
- **The per-image sensor is not recorded.**

**What it contains.** The archive `Official-SSDD-OPEN.rar` holds four variants with
**byte-identical images**:
- `BBox_SSDD` (straight boxes; the one we use: `coco_style/{images/{train,test}, annotations/*.json}`,
  with VOC XML as a cross-check);
- `RBox_SSDD` (rotated boxes);
- `PSeg_SSDD` (polygons);
- `BBox_RBox_PSeg_SSDD` (all three).

**Never use:**
- `JPEGImages_*_GT` and `JPEGImages_PSeg_GT*`, which have the labels burnt into the pixels;
- the bundled `*.py` scripts and analysis PNGs (not executed by us).

**The official split:**
- Train 928 / test 232 (46 inshore + 186 offshore).
- Test images are those whose index ends in 1 or 9.
- The lists are in `voc_style/ImageSets/Main/`.

**Images and boxes:**
- Each image is 190–526 px tall and 214–668 px wide. Median box: 22 × 29 px; 158 boxes have a side
  under 8 px.
- The paper quotes 2,456 boxes; the released files contain 2,587.
- Every image contains at least one ship.

**What we can use it for.** A quick benchmark for descriptor-based ML vs CNN on small labelled
chips, comparable with published results.

**Is it useful?** **Limited.**
- It cannot be joined to AIS or placed on a map.
- It does not transfer automatically to raw Sentinel-1 scenes.
- **Its official split leaks:**
  - 22 exact-duplicate groups (47 images), 10 of them crossing train/test;
  - 4 cross-split near-duplicate pairs (dHash ≤ 4);
  - visually overlapping crops of the same harbour across the split (e.g. 000763 train vs 000729
    test).
- Our own split must group duplicates (`data/splits/README.md`).

**How it differs from xView3:**

| Aspect | xView3 | SSDD |
|---|---|---|
| Sensor | Sentinel-1 IW GRD only | Mix of RadarSat-2, TerraSAR-X, Sentinel-1 (**not recorded per image**) |
| Resolution | 10 m pixels | 1–15 m, varying, **not recorded per image** |
| Pixels | VV + VH, calibrated float dB | 8-bit lossy JPEG; 1,126 greyscale-as-RGB, **34 false-colour composites** |
| Extent | Full scenes ~280 × 240 km | Small crops (~500 × 350 px) centred on ships |
| Labels | Point + box + length + vessel/fishing classes + confidence | Box (also rotated box/polygon), class `ship` only |
| Location and time | UTM grid, acquisition time | **None** |
| Negatives | Many non-vessel labels and empty sea | No ship-free images |

**Access and licence:**
- **Source:** https://github.com/TianwenZhang0825/Official-SSDD, then Google Drive file
  `1glNJUGotrbEyk43twwB9556AdngJsynZ`. Baidu mirror, password 2021.
- **File checked:** 1,043,241,197 bytes, SHA-256 `daf79e02…3ad9`, downloaded 2026-11-23.
- **Licence:** Apache-2.0. Cite Zhang et al., *Remote Sens.* 13(18):3690, 2021.

## 3. LS-SSDD-v1.0 — **Not useful now** — ❓ not investigated in depth

**What it is:** large Sentinel-1 scenes (24,000 × 16,000 px) cut into 9,000 sub-images, with ship
boxes. https://github.com/TianwenZhang0825/LS-SSDD-v1.0-OPEN.

**Is it useful?** **Not now.** xView3 provides full scenes with richer labels. It is a fallback if
xView3 access is lost.

## 4. GFW / Paolo et al. (2024) public data on figshare — ✅ downloaded and validated

**Source:** Paolo et al., *Satellite mapping reveals extensive industrial activity at sea*,
Nature 625, 2024.
- Code: https://github.com/GlobalFishingWatch/paper-industrial-activity.
- Licence: **CC BY 4.0**; no login needed.
- Files verified against figshare MD5 (`data/raw/gfw_paolo2024/manifest.json`).

### 4a. GFW detection tiles — **Useful** (Need A, classifier stage)

**What it is.** GFW's training patches: small Sentinel-1 cut-outs labelled vessel or not vessel.
Training record: https://doi.org/10.6084/m9.figshare.24309469.

**What it contains** (`detection_tiles.zip`, 142,908,413 B, Zarr v2):
- 11,965 tiles of 80 × 80 × 2 (float16, values 0–255).
- `presence`: 6,574 vessel / 5,391 non-vessel.
- `length_m` (0 = unknown for 1,265 positives), sample `weight`, latitude/longitude.
- GFW's official cross-validation and test indices.
- `detect_id` = `<ESA product name>;<LON>;<LAT>`. **Longitude comes first**: verified, not stated
  in the README. It gives the parent scene (6,578 scenes) and the acquisition time (2017-01-01 →
  2021-07-15).

**What we can use it for.** Training and testing the classifier stage (candidate patch → vessel or
non-vessel) on real Sentinel-1 data with true negatives.

**Is it useful?** **Useful**, with caveats:
- Band order and the dB → 0–255 scaling are **not documented**.
- Only 23 tiles fall in the SCS box.
- GFW's train and test indices share 2 scenes.
- The labels are GFW's training annotations, human-reviewed per the paper but not re-verified by us.
- The tiles cannot evaluate full-scene detection.

### 4b. GFW SAR vessel detections 2017–2021 — **Useful** as a labelled comparison layer

**What it is.** The output of **GFW's own models**, run on Sentinel-1 imagery, joined to AIS by
**GFW's matching algorithm**.
- It is **not human ground truth and not raw AIS positions.**
- Analysis record: https://doi.org/10.6084/m9.figshare.24309475.

**What it contains** (`industrial_vessels_v20240102.csv.zip`, 1,728,747,413 B, 23,088,625 rows):
- Columns: `scene_id, timestamp, lat, lon, year, mmsi, matching_score, fishing_score, length_m,
  matched_category, overpasses_2017_2021`.
- `timestamp` is the scene acquisition time, identical for all detections of a scene.
- Coverage is limited to likely vessels inside GFW's study area (coastal waters, ≥ 15 % of the
  ocean).
- There is no footprint of where imaging occurred; footprints come from the Sentinel-1 catalogue.

**SCS box** (105–122°E, 0–25°N):
- 1,812,280 detections in 17,529 scenes, about 3,000–3,800 scenes per year.
- 56 % unmatched, 29 % matched_nonfishing, 10 % matched_fishing, 5 % matched_unknown.

**What we can use it for:**
- A comparison layer for historical SCS demo scenes: what GFW found and matched in that exact image.
- Choosing demo dates and areas.
- Real MMSIs present at a known time (used for the LSEG test).

**Is it useful?** **Useful**, if it is always labelled "GFW detections matched to AIS by GFW":
- AIS vessels that GFW did not detect are absent.
- SCS AIS reception before ~2022 was weak, which inflates "unmatched".
- Newer data (2017 → about 5 days ago) is on the GFW Data Download Portal
  (`public-sar-vessel-detections:v20231026`, login and terms).

## 5. Copernicus Data Space Ecosystem (CDSE) — verified catalogue, candidate C1 imagery source

**What it is:** the official European archive of all Sentinel products.

**What it contains:** every Sentinel-1 product, in both SAFE and `_COG.SAFE` form. The historical SCS
scenes cited by GFW (2017–2019) are online, 1.7–2.0 GB SAFE each.

The catalogue supplies product identity, footprints and acquisition times. Download entitlement,
calibration and grid compatibility must be verified before CDSE can supply pixels in this project.

The catalogue works anonymously at
`catalogue.dataspace.copernicus.eu/odata/v1/Products`.

Measured SCS coverage for Sep–Oct 2025 GRDH (unique acquisitions ≈ half the listed products):

| Box | Products |
|---|---|
| South of Spratly | ~6 |
| Paracel | ~9 |
| Gulf of Tonkin | ≥ 50 (query capped at 100) |
| Pearl River Delta coast | ~35 |

The open SCS is revisited roughly every 6–12 days, and coasts more often (S1A + S1C, S1D since
late 2025).

**Access:** downloads need a free CDSE account and an OAuth token. Neither has been set up or
tested.

## 6. Microsoft Planetary Computer, Sentinel-1 GRD — **Essential** (Need C1) — ✅ access proven

**What it is:** Microsoft's public catalogue hosting the global Sentinel-1 GRD archive as
cloud-optimised GeoTIFFs, readable without an account.

**What it contains:**
- The STAC collection `sentinel-1-grd`.
- Per item, one COG per polarisation (`vv`, `vh`): uint16 uncalibrated DN in radar geometry, with
  231 ground-control points (GCPs) for geolocation.
- Calibration and noise XML assets.
- **Item ids drop the 4-character product suffix** used in ESA and GFW names.

**What we can use it for.** Fetching just the needed window of the image for any SCS date and area,
and building the date selector.

**Proof of access:**
- 2017–2025 SCS scenes were found.
- A 3072 × 3072 VV+VH window of `S1B_IW_GRDH_1SDV_20190318T104813_…_01CDA6` was read by HTTP range
  requests in ~10 s.
- Script: `scripts/fetch_pc_s1_window.py`. Figure: `docs/figures/scs_reveal_feasibility.png`.

**Is it useful?** **Essential**: it is the only proven, account-free imagery route.

**Caveats:**
- Pixels must be calibrated to σ⁰ using the calibration look-up table.
- Thermal noise is visible in VH.
- Geolocation in radar geometry is through GCPs, accurate to tens of metres.
- It is a third-party service with its own terms.

**Access:** an anonymous SAS token from
`https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-grd`.

## 7. LSEG Workspace (Eikon) — selected historical reports and recent snapshots

**What it is.** The vessel data in our LSEG Workspace licence, read with the LSEG Data Library for
Python (`lseg-data` 2.1.1) through a desktop session. **The Workspace desktop app must be running
and logged in on the same machine**, and `EIKON_APP_KEY` must be in `.env`.

**What it contains:**
- **A search index of 426,024 vessels**, with LSEG id (RIC), name, IMO, MMSI, flag, type,
  dimensions and the **latest** position only.
- **Per-vessel `get_data` fields:**
  - position time (UTC, to the second) and latitude/longitude;
  - AIS speed, course, heading, status, destination and ETA;
  - static identity and dimensions.
- **History from at least 2010**, requested in whole-day steps. Recent data has a report about
  every 3 min; 2019–2020 data has about 4 reports per vessel-day, with course missing.

**What we can use it for:** an AIS layer and matching positions for **recent** images, by
reconstructing who was inside an area at time T.

**Is it useful?** **Limited:**
- There is no historical "vessels in area at time T".
- For the AIS-matched vessels in our scenes, an LSEG report within 30 min of acquisition existed
  for 6 of 112 (North Sea 2020) and 0 of 61 (Hainan 2019).
- It is a commercial-fleet subset (223 fishing-typed vessels in the whole SCS box).
- MMSIs are ambiguous.
- It cannot run on a server.
- Display rights are unverified.

**Limits:** 5 requests/s, 10,000/day, 50 MB/min, 5 GB/day.

**Licence:** licensed for individual use. Samples stay in git-ignored `data/raw/lseg/`.

**Full evidence:** [`lseg_shipping_access_assessment.md`](lseg_shipping_access_assessment.md).

## 8. LSEG Vessel Tracking API — **Not useful now** — 📍 not tested

**What it is:** a separate LSEG product,
`GET https://vtracking.rdms.refinitiv.com/api/v1/Shipping/History`, with the header
`Authorization: apikey-v1 <key>`.

**What it contains:** one vessel per call (IMO, RIC or ENI), **most recent 24 hours only**.

**Is it useful?** **Not now.**
- There is no `VESSEL_TRACKING_API_KEY`, and the endpoint answers 401 without one.
- 24 hours is too short for our imagery.

## 9. Global Fishing Watch API / Data Download Portal — **Probably useful** ❓ — 📍 token not requested

**What it is:** GFW's online services, with free self-service registration and a per-user token.
- Use must be **non-commercial (CC BY-NC 4.0)**.
- Limits: 50,000 requests/day, 1.5 M/month.
- Tokens must not be shared or embedded publicly
  (https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits).

**What it contains:**
- SAR vessel detections, from 2017 to about 5 days ago.
- AIS-based fishing effort and vessel presence (gridded, derived).
- Vessel identity and events.
- Point-by-point AIS tracks were **not confirmed** from the pages read.

**What we can use it for:** AIS context for the SCS at image times; recent GFW detections for
comparison.

**Is it useful?** **Probably**: it is the best candidate for SCS AIS, but unverified. GFW notes
that from ~2022 onboard AIS receivers "substantially improved" reception around China and Southeast
Asia, so earlier SCS coverage is weaker.

## 10. Danish Maritime Authority raw AIS — **Useful** for validating matching — 📍 not downloaded

**What it is:** raw AIS messages for Danish waters, at `http://aisdata.ais.dk/` (a public S3
listing, no login).

**What it contains:** one CSV row per message: timestamp, type of mobile, MMSI, latitude/longitude,
navigational status (including "Engaged in fishing"), SOG, COG, heading, IMO, call sign, name, ship
type and dimensions.
- 2020 data comes only as monthly zips (~15–17 GB each).
- Recent data comes as daily zips (~0.6–0.75 GB, e.g. 2026-10-01 → 2026-11-20).

**What we can use it for:** validating our matching procedure with genuine raw AIS against the
labelled xView3 North Sea scene `fc2f57371370c521v`.

**Is it useful?** **Useful** for method validation. It is not relevant to the SCS.

## 11. NOAA MarineCadastre AIS — **Not useful now** — 📍 located

**What it is:** raw AIS for US waters.
`https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2020/` (daily 2020 files listed).

**Is it useful?** **Not now.** None of our scenes are in US waters; it is a fallback for method
validation.

## 12. SARFish — **Limited** — 📍 located

**What it is:** https://huggingface.co/datasets/ConnorLuckettDSTG/SARFish (Apache-2.0, public,
ungated), plus a one-scene sample repo.

**What it contains:**
- The *original* ESA GRD and SLC products of all 753 xView3 scenes. GRD zips are about 0.5–1.2 GB
  each (673 GB GRD in total); the full dataset is about 3.3 TB.
- Its labels (`GRD_*.csv`, `SLC_*.csv`) are distributed **only** via the login-gated xView3 page.
  They refer to the SAFE pixel grid, not xView3's processed rasters.
- Third-party Hugging Face copies (vrajvasath, xuleijuly, tuyao10086, yurise) contain imagery only.

**What we can use it for:** more xView3 scenes without expiring links, or complex SLC data.

**Is it useful?** **Limited.** xView3's processed rasters are easier to use.

---

## Decision

1. **Primary modelling data: xView3-SAR** validation scenes, plus selected train scenes.
2. **SSDD** as a secondary benchmark for descriptor-vs-CNN, with a duplicate-aware split. Not used
   for geography.
3. **GFW detection tiles** for the classifier stage, once the band scaling is understood.
4. **Map/reveal demo:**
   - Planetary Computer imagery plus GFW detections of the same scene, labelled as GFW's
     AIS-matched detections.
   - LSEG Workspace for a **recent-image** demo, labelled as a partial layer.
   - Raw AIS needs either a GFW API token (SCS) or DMA (Danish waters, North Sea scene).

## Citations
- Paolo, F. et al. (2022). xView3-SAR. NeurIPS Datasets & Benchmarks. https://iuu.xview.us/
- Zhang, T. et al. (2021). SSDD: Official Release and Comprehensive Data Analysis. Remote Sens. 13(18), 3690.
- Paolo, F. S. et al. (2024). Satellite mapping reveals extensive industrial activity at sea. Nature 625, 85–91. Data: figshare 10.6084/m9.figshare.24309469 / .24309475 (CC BY 4.0).
- Luckett, C. et al. (2024). The SARFish Dataset and Challenge. WACV Workshops.
- Contains modified Copernicus Sentinel data (2017–2025).
