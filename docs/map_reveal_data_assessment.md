# Data assessment for the AIS map and the "Reveal hidden vessels" interaction

**What this file is.** The application's core interaction:
1. Show the AIS-visible vessels for a date and area.
2. Press "Reveal hidden vessels".
3. Show the satellite detections that AIS does not explain.

This file breaks that interaction into steps, says which data each step needs and whether we have
it, and describes realistic routes to a first real demonstration.

_Historical feasibility assessment, 2026-11-23. The implemented [data layer](data_layer.md)
records current routing and evidence. Sources and access details: [`data_sources.md`](data_sources.md). LSEG
evidence: [`lseg_shipping_access_assessment.md`](lseg_shipping_access_assessment.md)._

**Bottom line:**
- **Archived imagery access:** Planetary Computer supplied native radar DN and GCPs. Calibration
  and grid validation for the xView3 model domain remain open.
- **AIS at image time is not solved for the SCS:**
  - Historical GFW detections are a published comparison layer. The licensed historical
    position exports cover selected RICs and have unknown area reception.
  - For recent scenes LSEG Workspace gives a dense but partial commercial-fleet layer.
  - A GFW API token has not been requested yet.

## 1. What the interaction needs, step by step

| Step | Data needed | Temporal requirement | Status |
|---|---|---|---|
| Date selector shows available observations | S1 scene footprints + acquisition times per date | exact start/stop times | ✅ CDSE OData / PC STAC, anonymous queries work |
| Area of interest (zone or viewport) | footprint ∩ AOI | — | ✅ footprints in catalogue items (GeoJSON) |
| Initial AIS layer | AIS positions near the acquisition time (± minutes) | must bracket the image snapshot | Historical SCS reception is unknown. A successful LSEG export describes only its sampled RICs. |
| Reveal imagery | GRD rasters for the AOI | the selected acquisition | PC COG window read verified. CDSE catalogue verified, asset compatibility unverified. |
| Reveal: our detections | our pipeline on that imagery | — | 📋 pipeline not built yet |
| Matching | Time-aligned position evidence | Valid observations near image time | Historical SCS coverage is insufficient. Danish raw AIS would be a separate regional study. |
| Evidence panel | image patch, coordinates, acquisition time, model version, score, matching evidence | selected acquisition | Input preview and receipts implemented. Model and matching evidence pending. |
| Imagery availability | footprint intersection followed by valid pixels in the required bands | selected acquisition | Preview checks the joint valid-pixel mask. Vessel counts require inference. |

## 2. Three classes of information (never mix them up in the UI)

1. **Raw measurements**: Sentinel-1 GRD pixels (CDSE, PC); raw AIS messages (DMA, NOAA; GFW tracks
   via API if granted).
2. **Human annotations**: xView3 validation labels (human-reviewed, AIS-informed); SSDD boxes;
   GFW training tiles (per paper).
3. **Other organisations' model predictions**: GFW SAR vessel detections (`industrial_vessels`
   table / Data Download Portal / API) including their AIS matching and fishing scores. These
   are *not* ground truth and *not* an AIS feed.

## 3. Feasible routes to one real map demonstration

### Route A — Historical South China Sea imagery and published comparison
- **Imagery**: Planetary Computer `sentinel-1-grd` (anonymous SAS token; COG range reads). Proven
  on `S1B_IW_GRDH_1SDV_20190318T104813_…_01CDA6_F3BE` (off SE Hainan): 3072² px VV+VH window in ~10 s.
- The position layer uses time-filtered observations from entitled sources. With the available
  export, the example Hainan viewport returns zero reports and unknown population coverage.
- The separate comparison layer shows GFW predictions and GFW matching categories for the
  same ESA acquisition and viewport. The model layer requires SSS inference and a model receipt.
- **Candidate scenes**: `data/inventory/gfw_sar_scs_scenes.csv` (17,529 SCS scenes with counts by
  category; e.g. 2019-03-18 10:48:28Z off Hainan: 461 detections, 400 unmatched; 2018-05-09
  10:56:34Z off central Vietnam: 339 detections, 307 unmatched).
- **Limitation**: AIS reception in Chinese/SE Asian waters was markedly worse before ~2022 (GFW
  statement); an 87 % unmatched rate (Hainan example) is partly a *coverage* effect. These cases must
  be shown as "unmatched — AIS coverage uncertain", not "hidden vessel".

### Route B — GFW API access investigation
- Imagery: PC or CDSE (S1A + S1C, S1D since late 2025; open SCS revisit ~6–12 days, coasts more).
- AIS: GFW API (free registration, non-commercial CC BY-NC 4.0, per-user token, 50k req/day).
  Gridded presence/fishing effort are derived products; per-vessel tracks/events exist in the API
  but point-level access terms were not confirmed. GFW SAR detections (recent) also via portal/API.
- Blocker: someone on the team must register and create a token (do **not** commit it; use an
  environment variable / `.env` excluded by `.gitignore`).

### Route D — South China Sea, recent dates, LSEG Workspace AIS — tested, works with caveats

**Imagery:** a Sentinel-1 acquisition from the last few days over an SCS area, from PC or CDSE.

**AIS layer:** LSEG Workspace via our app key, through a desktop session (Workspace must be running).
The layer at the acquisition time T is reconstructed in three steps:
1. Find candidate vessels whose latest position is within a speed-based buffer around the area.
2. Read their history for the day(s) around T.
3. Keep the report nearest T within ±30 min, if it is inside the area.

This is implemented in `scripts/probe_lseg_shipping.py`, `recent_reconstruction()`.

**Measured:**
- Recent reports arrive about every 3 min.
- Off Hainan, only **9 vessels** were inside a 3° × 2° box at T.
- LSEG's universe is a commercial-fleet subset: 223 fishing-typed vessels in the whole SCS box.

**Limitations:**
- Unsuitable for historical scenes: there is no historical area query, and 2019/2020 history is
  sparse.
- The desktop session cannot run on a server.
- Display rights are unverified.
- The layer must be labelled "LSEG Workspace AIS (subset)", and LSEG absence must never be read as
  "hidden".

### Route C — Danish waters, raw AIS, method validation
- xView3 scene `fc2f57371370c521v` (2020-09-28 17:18:00–17:18:31Z, 55–57°N 4–9°E) already
  downloaded with human-reviewed labels; DMA raw AIS for September 2020 exists only as one
  ~16 GB monthly zip (a recent scene + daily DMA file of ~0.7 GB is lighter).
- Lets us validate *our matching procedure* with genuine raw AIS and known labels, outside the SCS.

## 4. Matching rules implied by the data (to implement later)

- Use scene acquisition start/stop (from product name or catalogue) as the observation time; the
  ~25–30 s scene duration is negligible versus AIS gaps but azimuth time per pixel can be computed
  from annotation XML if needed.
- Only AIS messages within a window around acquisition (e.g. ±30 min) may be used, interpolated /
  dead-reckoned to the acquisition time; record the time gap used for each match.
- Status per detection: **matched** (AIS position within distance gate after interpolation),
  **unmatched** (no candidate although AIS coverage in the area/time is adequate),
  **insufficient AIS information** (no AIS data source for the area/time, or reception known to be
  poor, or nearest AIS fix too old). Coverage adequacy must be estimated (e.g. AIS message density
  in surrounding cells in the same hour), not assumed.
- Missing imagery for a date/AOI ⇒ "No imagery available" (from footprints), never "0 hidden
  vessels". Partial footprint coverage ⇒ report the covered fraction.

## 5. Not possible with the data at hand

- Joining SSDD crops to AIS (no coordinates, timestamps or scene ids).
- Treating xView3 labels as AIS tracks (labels are AIS-informed but carry no AIS messages/times).
- Treating GFW's matched SAR detections as a full AIS vessel picture.

## 6. Concrete next steps for the map work

1. Connect the date selector to the implemented `scenes` workflow and its footprint evidence.
2. Decide Route A demo scene(s) from `gfw_sar_scs_scenes.csv` (prefer open-sea scenes with a mix
   of matched and unmatched rows, and dates ≥ 2021 where AIS coverage is better).
3. Request a GFW API token (Route B) and check whether point-level tracks are available for the
   SCS at acquisition times; if not, document the limitation in the UI.
4. Implement radiometric calibration (σ⁰ from PC calibration XML) before running any detector on
   PC/CDSE data, so that inputs resemble xView3's dB rasters.
