# Data assessment for the AIS map and the "Reveal hidden vessels" interaction

_Verified 2026-11-23. Sources and access details: [`data_sources.md`](data_sources.md)._

## 1. What the interaction needs, step by step

| Step | Data needed | Temporal requirement | Status |
|---|---|---|---|
| Date selector shows available observations | S1 scene footprints + acquisition times per date | exact start/stop times | ✅ CDSE OData / PC STAC, anonymous queries work |
| Area of interest (zone or viewport) | footprint ∩ AOI | — | ✅ footprints in catalogue items (GeoJSON) |
| Initial AIS layer | AIS positions near the acquisition time (± minutes) | must bracket the image snapshot | ⚠️ see §3 |
| Reveal: imagery | GRD rasters for the AOI | the selected acquisition | ✅ PC COG window read proven (no account); CDSE SAFE with account |
| Reveal: our detections | our pipeline on that imagery | — | 📋 pipeline not built yet |
| Matching | AIS interpolated to acquisition time; distance/time gates | AIS within e.g. ±10–30 min, interpolated | ⚠️ needs raw AIS or GFW-matched proxy |
| Evidence panel | image patch, coords, timestamp, model version, score, match status | — | ✅ all derivable once pipeline exists |
| "No imagery" vs "no vessels" | footprint coverage of AOI on that date | — | ✅ from catalogue footprints |

## 2. Three classes of information (never mix them up in the UI)

1. **Raw measurements**: Sentinel-1 GRD pixels (CDSE, PC); raw AIS messages (DMA, NOAA; GFW tracks
   via API if granted).
2. **Human annotations**: xView3 validation labels (human-reviewed, AIS-informed); SSDD boxes;
   GFW training tiles (per paper).
3. **Other organisations' model predictions**: GFW SAR vessel detections (`industrial_vessels`
   table / Data Download Portal / API) including their AIS matching and fishing scores. These
   are *not* ground truth and *not* an AIS feed.

## 3. Feasible routes to one real map demonstration

### Route A — South China Sea, historical (2017–2021), no account needed — **recommended first demo**
- **Imagery**: Planetary Computer `sentinel-1-grd` (anonymous SAS token; COG range reads). Proven
  on `S1B_IW_GRDH_1SDV_20190318T104813_…_01CDA6_F3BE` (off SE Hainan): 3072² px VV+VH window in ~10 s.
- **"AIS-visible" layer**: GFW `industrial_vessels_v20240102` rows with `matched_category =
  matched_*` for the **same `scene_id`** (hence the same acquisition instant). Must be labelled
  **"Vessels detected by GFW in this image and matched to AIS (GFW model + matching)"** — it is
  *not* a complete AIS position feed: AIS vessels outside GFW's study area, below detection size,
  or simply not detected are absent.
- **Reveal layer**: our detections on the same imagery; compare with (i) GFW matched detections
  (→ "consistent with an AIS-broadcasting vessel per GFW"), (ii) GFW unmatched detections
  (→ independent corroboration of a non-matched object), (iii) neither.
- **Candidate scenes**: `data/inventory/gfw_sar_scs_scenes.csv` (17,529 SCS scenes with counts by
  category; e.g. 2019-03-18 10:48:28Z off Hainan: 461 detections, 400 unmatched; 2018-05-09
  10:56:34Z off central Vietnam: 339 detections, 307 unmatched).
- **Limitation**: AIS reception in Chinese/SE Asian waters was markedly worse before ~2022 (GFW
  statement); an 87 % unmatched rate (Hainan example) is partly a *coverage* effect. These cases must
  be shown as "unmatched — AIS coverage uncertain", not "hidden vessel".

### Route B — South China Sea, recent dates, raw AIS — needs a GFW API token
- Imagery: PC or CDSE (S1A + S1C, S1D since late 2025; open SCS revisit ~6–12 days, coasts more).
- AIS: GFW API (free registration, non-commercial CC BY-NC 4.0, per-user token, 50k req/day).
  Gridded presence/fishing effort are derived products; per-vessel tracks/events exist in the API
  but point-level access terms were not confirmed. GFW SAR detections (recent) also via portal/API.
- Blocker: someone on the team must register and create a token (do **not** commit it; use an
  environment variable / `.env` excluded by `.gitignore`).

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

1. Build a scene index for the demo AOI/date range from PC STAC (id, start/stop, footprint) →
   powers the date selector and the "no imagery" state.
2. Decide Route A demo scene(s) from `gfw_sar_scs_scenes.csv` (prefer open-sea scenes with a mix
   of matched and unmatched rows, and dates ≥ 2021 where AIS coverage is better).
3. Request a GFW API token (Route B) and check whether point-level tracks are available for the
   SCS at acquisition times; if not, document the limitation in the UI.
4. Implement radiometric calibration (σ⁰ from PC calibration XML) before running any detector on
   PC/CDSE data, so that inputs resemble xView3's dB rasters.
