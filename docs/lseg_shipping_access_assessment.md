# LSEG Workspace (Eikon) shipping data — access and suitability assessment

_Investigated 2026-11-23 with real API calls. Numbers below come from the final probe run
`data/raw/lseg/probe_20261123T170033Z/assessment.json` (git-ignored), produced by
`scripts/probe_lseg_shipping.py`. Two earlier runs that day gave the same results._

**Question.** Can our existing LSEG access supply two things?
- (a) The initial **AIS map layer**: vessels visible via AIS in a chosen area at the observation time.
- (b) **AIS positions for matching** against our SAR detections.

The detector itself never uses AIS.

**Short answer.** **Partially, and only for recent observation times.**
- **Recent times work technically.** Recent positions are dense (one report about every 3 min) and
  can be reconstructed for an area at a recent time T.
- **The vessel universe is a commercial-fleet subset, not a complete AIS feed.** Off Hainan only 9
  vessels were reconstructed inside a 3° × 2° box at T.
- **Historical times are unsuitable.** For our 2019 Hainan and 2020 North Sea scenes there is no
  query for "vessels in this area at that time", and per-vessel history is too sparse. Only 6 of
  the 112 AIS-matched vessels in the North Sea scene had an LSEG position within 30 min of the
  acquisition time. None of the 61 at Hainan did.
- **LSEG absence is not evidence.** A vessel missing from LSEG must never be treated as hidden.

## 1. Access route and session requirements

| Item | Finding | Status |
|---|---|---|
| SDK | **LSEG Data Library for Python** `lseg-data` 2.1.1, the current successor of `eikon`/`refinitiv-data`. Added as optional dependency group `lseg` in `pyproject.toml`. The repo had no previous LSEG integration. | ✅ tested |
| Session type | **Desktop session**: `lseg.data.open_session(app_key=…)` → `DesktopSession`, name `workspace`, state `Opened`. | ✅ tested |
| Runtime requirement | The **Workspace desktop app (Refinitiv Workspace 1.26.843) must be running and logged in on the same machine**. Requests go through its local *Data API Proxy* at `127.0.0.1:9000`. The port is read from `~/Library/Application Support/Data API Proxy/.portInUse`; `GET /api/status` returns `ST_PROXY_READY`, proxy 3.12.0. | ✅ tested |
| Credential | `EIKON_APP_KEY` in the git-ignored `.env`, loaded by `src/shadow_ship_spotter/config.py`, a stdlib loader that never overrides existing environment variables and never prints values. The key is never logged; exception text is scrubbed. `.env` had been staged in Git with an empty value; it is now unstaged and git-ignored, and `.env.example` lists the names only. | ✅ |
| Platform session (RDP credentials, no desktop app) | Not available to us and not tested. A server-side deployment would need it or an equivalent licence. **The desktop session cannot back a hosted app.** | 📍 documented, not tested |
| `VESSEL_TRACKING_API_KEY` | **Absent** from `.env`. | — |

**Failure classes implemented in the probe.** Each class is reported separately:
- no key → exit 2;
- proxy unreachable or not ready (Workspace closed or logged out) → exit 3;
- session open failure → exit 4;
- per-request or per-cell `rate_limited`, `entitlement_denied` (codes 403/906), `invalid_field` (414),
  `no_data` (415), `bad_request` (400/234), `timeout`, `connection`.

Exits 2–4 were **not exercised**, because Workspace was running and we did not close the user's app.
In particular, a missing desktop session and an entitlement restriction show up differently:
- **Missing or broken desktop session:** proxy status not ready, or the session never reaches `Opened`.
- **Entitlement restriction:** per-request or per-cell 403/906 on an open session.

## 2. Fields actually retrieved (get_data, vessel RICs `C}…`)

| Field | Returned as | Example / note | History (SDate/EDate) |
|---|---|---|---|
| `TR.AssetLocationDate` | ISO-8601 **with `Z` (UTC)**, second precision | `2026-11-23T16:38:46Z` | ✅ |
| `TR.AssetLocationLatitude` / `…Longitude` | float degrees | valid in 100 % of the 377 historical rows and 730 snapshot rows | ✅ |
| `TR.AssetSpeed` | "AIS Speed", knots | `12.8` | ✅ (filled in history) |
| `TR.AssetCourse` | "AIS Course over Ground", ° | `191` | ⚠️ **empty in all 2019/2020 rows** (0/64 in windows); filled recently (9/9) |
| `TR.AssetHeading` | "AIS Heading", ° | `511` = not available (AIS convention); mapped to null | ✅ |
| `TR.AssetLocationStatus` | AIS navigational status | `At Anchor` | ✅ |
| `TR.AssetDestination`, `TR.AssetETA` | AIS voyage data | `SANYA [Sanya]` | latest only (not tested in history) |
| `TR.AssetName`, `TR.AssetIMO`, `TR.AssetMMSI`, `TR.AssetCallSign`, `TR.AssetFlag` | static | `BEI HAI XIN XI WANG`, `9910521`, `413279130`, `BOPO3`, `China` | static; with dates, returned only on the first row |
| `TR.AssetType`, `TR.AssetSubType`, `TR.AssetHullType`, `TR.AssetStatus` | static | `Tankers`, `Oil Tankers`, `Double Hull`, `IN SERVICE/COMMISSION` | — |
| `TR.AssetLOA`, `TR.AssetBeam`, `TR.AssetDWT` | static dimensions | `137`, `22`, `15731` (`0` = unknown for AIS-only units) | — |
| `TR.AssetOwner` | static | empty for all 3 test vessels | — |
| `TR.AssetLocationType` | "Polygon Location Type" | `Within Zone`, `Entry`: a geofence relation, **not** a position-quality flag | — |

**Behaviours to know:**
- **Unrecognised field names make the whole request fail** with code 414. This happened for
  `TR.AssetLocationSpeed`, `TR.AssetDraft`, `TR.AssetBuildYear` and `TR.AssetLocationSource`.
  In a larger mixed request they were instead dropped silently, while the location fields came back
  with code 906 "Permission Denied to parameter 'Dur'". That 906 never recurred with the validated
  field lists, so we attribute it to how the request was built, not to an entitlement limit.
- **An invalid RIC** (`C}XX0000000000`) returns an empty row with no error, which looks exactly like
  "no data". Identifiers must therefore be resolved via Search first.
- **No quality indicator.** There is no per-position source (terrestrial vs satellite AIS), no
  quality flag, and no "estimated or interpolated" flag. The Search `Source` property is `NDA_SDI`
  for every row (dataset-level). All LSEG rows are therefore stored as `position_kind = "reported"`.
  Our own interpolations are labelled `interpolated_by_probe` and are kept separate.
- **The timestamp is the position time, not the retrieval time.** It differs per vessel and is
  earlier than the request time. It equals the Search `LocationTimestamp` for the same report, and
  historical requests return 2010–2020 values.

## 3. Identifiers (MMSI ≠ IMO ≠ RIC)

The Search API view `VesselPhysicalAssets` (426,024 vessels, including broken-up ones) resolves
`MMSI in (…)` and `IMO eq …` to RICs. Tested with the MMSIs that GFW matched to AIS in our two
scenes:

| Scene (acquisition, UTC) | GFW AIS-matched MMSIs | resolved in LSEG | of which `matched_fishing` | RICs returned |
|---|---|---|---|---|
| Hainan S1B 2019-03-18 10:48:28 | 61 | **16 (26 %)** | 2 / 18 | 43 |
| North Sea S1A 2020-09-28 17:18:16 | 112 | **63 (56 %)** | 23 / 43 | 65 |

- **MMSI is not unique.** For example, MMSI `808663912` maps to 25 RICs (AIS-only "Miscellaneous
  Vessel" units with no IMO).
- **MMSI changes over time.** MMSI `305078000`, matched by GFW off Hainan in 2019, now resolves to an
  Antigua-flag cargo ship. LSEG's 2019 track for that ship is in the Baltic, about 8,700 km away.
- **Consequence:** a cross-source or historical identifier join must be confirmed by position and
  time consistency. Never assume one.

## 4. Historical depth and temporal precision

- **Date parameters:** `SDate`/`EDate` are supported for the location and dynamic fields, but at
  **day resolution only**.
  - Quoted intraday bounds (`'2026-11-22T03:00:00'`) return the same 22 rows as the whole day.
  - Unquoted times give error 234 (formula parse error).
  - Callers must request whole days and filter locally, and this inflates volume.
- **Historical retrieval is real.** All 377 historical positions fell inside the requested days;
  0 were outside and none were duplicates.
- **Earliest data:** at least **2010**. A June 2010 week returned 4 positions for 1 of 5 test
  vessels; 2012–2018 weeks returned 25–92 positions. Earlier years were not probed.
- **History is sparse, and the cadence depends on age:**

| Period | Positions per vessel-day | Median interval between reports | Source |
|---|---|---|---|
| 2019-03-18 (Hainan sample, 3 vessels) | 4–10 | ~42 min | scene probe |
| 2020-09-28 (North Sea, 41 vessels) | median 4 (q90 29) | median 39 min (q90 102 min) | scene probe |
| 2026-11-23 (recent, 396 vessels) | ~250 | **3.0 min** | recent probe |

- **Closeness to the acquisition time.** Window ±3 h, North Sea, 2020:
  - Only 13 of 65 RICs had any report in the window, all inside the scene area.
  - Nearest-report gaps: median 38 min; 6 within 30 min; 10 within 60 min.
  - Only 2 vessels could be interpolated (a report ≤ 30 min on each side). Those 2 interpolated
    positions lay **25 m and 752 m** from GFW's SAR detections, which is consistent but a tiny sample.
  - The nearest raw reports (≤ 30 min) were a median 2.0 km away, which is vessel motion during
    the gap.
- **Hainan 2019:** only 2 RICs had reports in the window, and **both were elsewhere** (identity
  mismatch, see §3). That leaves **0 usable**.

## 5. Discovery by area and time

| Capability | Finding | Status |
|---|---|---|
| Bounding-box query | Search filters on `Latitude`/`Longitude` (numeric, filterable, sortable), e.g. `Latitude ge 17.5 and Latitude le 19.5 and Longitude ge 108.5 and Longitude le 111.5`. The view's metadata lists them as plain `Double` properties, with no geographic-type property, so we found no polygon or distance operator. A polygon AOI would be its bounding box plus a client-side filter. | ✅ tested (latest position only) |
| Time filter in Search | `LocationTimestamp ge 2026-11-22T00:00:00Z` works, but filters only the **latest** report. | ✅ tested |
| **Historical geographic filtering** | **None.** The index holds each vessel's latest position only. | ❌ unavailable |
| Paging | `top + skip ≤ 10,000` per query (error 400 beyond that). The SCS box has 54,899 vessels, so the area must be split into smaller boxes. | ✅ tested |
| Index freshness | In one direct comparison, Search `LocationTimestamp` trailed the get_data latest by ~36 min. "Fresh in the last hour" counts are lower bounds. | ✅ observed once |
| Staleness | In the Hainan box, 730 vessels have their latest position inside, but the median age is **~13 months**. Only 28 reported in the last 24 h and 1 in the last hour. | ✅ |

**Turning a map viewport into a request.** For a recent time T, this works and is implemented in
`recent_reconstruction()`:
1. Search for candidates. A candidate's latest indexed position lies inside the viewport box
   expanded by `v_max × (now − T + 1 h)`, with v_max = 25 kn, and it reported after T − 1 h.
2. Call `get_data` with the history fields for those RICs, over the whole day(s) containing T ± 30 min.
3. Keep each vessel's report nearest to T within ±30 min, and keep it only if it is inside the
   viewport.

Result for T = 2026-11-23 14:00 UTC (3 h before the run) off Hainan:
- 396 candidates, 4 requests, 105,488 rows returned;
- 337 vessels reported within ±30 min of T;
- **9 vessels were inside the box at T**;
- only 1 of those 9 is still in the box's 1-hour snapshot now.

So current presence is no proxy for presence at T.

For **historical** T (years ago) the buffer becomes global, so the candidate set is the whole
426k-vessel universe. That would mean thousands of requests and GB-scale whole-day pulls per date,
against caps of 10,000 requests and 5 GB per day. It is **not practical per map interaction**.

## 6. Fishing-vessel coverage

The counts below include every vessel whose latest indexed position is in the box. "Fresh" means
it reported within that time.

| Region | latest in box | fresh 1 h | fresh 24 h | type `Fishing Vessel` (fresh 24 h) | AIS status "Engaged In Fishing" |
|---|---|---|---|---|---|
| South China Sea 105–122°E, 0–25°N | 54,899 | 1,232 | 7,523 | **223 (74)**: Taiwan 111, China 26, Mongolia 8, Vietnam 8 … | 91 |
| Hainan box 108.5–111.5°E, 17.5–19.5°N | 730 | 1 | 28 | 1 | — |
| North Sea, xView3 scene area | 243 | 17 | 183 | 44 (30): Norway 13, Netherlands 9, Denmark 8 … | 21 |
| Singapore Strait (reference) | 3,315 | 122 | 1,482 | 21 (1) | 2 |
| Dover Strait (reference) | 130 | 34 | 111 | 40 (39) | 29 |

- **Globally**, 33,833 of the 426,024 vessels are typed `Fishing Vessel`. A further 117,497 are
  `Miscellaneous Vessel`: AIS-only units, usually without IMO or type, which may include small
  fishing boats.
- **Fishing vessels are therefore included, not filtered out.** No entitlement or fleet-category
  error was seen.
- **In the SCS, coverage is very small compared with the known fishing activity there.** One GFW
  scene off Hainan has 461 SAR detections, 61 of them AIS-matched; LSEG's universe has 223 SCS
  fishing-typed vessels in total.
- **Coverage is thin even in dense commercial straits**, so the feed is a subset everywhere.
- **The cause cannot be established from the API.** It could be source coverage (e.g. restricted
  sharing of Chinese terrestrial AIS) or our licence scope. ❓ Ask LSEG.
- **Consequence:** in the SCS, an SAR detection with no LSEG match is "unmatched against an
  incomplete commercial-fleet AIS subset". It is never "hidden".

## 7. Request limits and usage restrictions

- **Local throttling endpoint** (`GET 127.0.0.1:9000/api/throttling/limits`, no credential):
  - `request_max` 5 per 1 s;
  - `daily_request_max` 10,000;
  - `volume_max` 50,000 per 60 s and `daily_volume_max` 5,000,000 (consistent with 50 MB/min and
    5 GB/day).
- These match LSEG's published guideline (5 req/s, 10,000 req/day, 50 MB/min, 5 GB/day). The
  guideline says the figures are not contractual. 429 means rate-limited.
- **One full probe run costs** 62 requests and ~10 MB, mostly the whole-day pulls of the recent
  reconstruction. The probe paces calls at ≥ 0.3 s and retries once only on 429.
- **Licence:** Eikon/Workspace data is "licensed for individual use" (LSEG usage guideline).
  - Samples stay in git-ignored `data/raw/lseg/` and must not be committed or redistributed.
  - **Showing LSEG positions to other users in our app requires checking display/redistribution
    rights first.** ❓

## 8. Dedicated Vessel Tracking API (separate product)

Documented by LSEG, Sept 2026 article and sample repo:
- `GET https://vtracking.rdms.refinitiv.com/api/v1/Shipping/History`;
- header `Authorization: apikey-v1 <key>`;
- one IMO, RIC or ENI per call;
- optional `FromDateTime`/`ToDateTime`. The sample notebook uses `FromDate`/`ToDate`, which
  conflicts with the article; the probe tries both when a key exists.
- Positions come from the **most recent 24 hours only**. No area endpoint is documented. A
  WebSocket live interface exists (Part 2, URL not found).

Our test, sending no credential, got **HTTP 401**. The endpoint is reachable and needs its own key.

Notes:
- **Not tested with a key**, because `VESSEL_TRACKING_API_KEY` is absent.
- We did not send the Eikon app key to it. Per the task brief, the Eikon key is not assumed to work there.
- The 24-hour limit applies to this API only. Workspace get_data history went back to 2010 (§4).
- Python's bundled CA store failed TLS verification for this host. The probe uses `certifi`.

## 9. Summary by category

1. **Confirmed accessible and tested:**
   - desktop session;
   - Search vessel universe with bbox, latest-time, type, flag and status filters, MMSI/IMO → RIC
     resolution, and navigators;
   - latest positions plus AIS speed, course, heading, status and destination;
   - static identity and dimensions;
   - historical positions back to at least 2010, at day resolution, with verified timestamps;
   - throttling endpoint;
   - recent area reconstruction.
2. **Documented by the provider, not tested with our account:**
   - Vessel Tracking API History (24 h) and its WebSocket interface;
   - platform session.
3. **Blocked by connection or session setup:** nothing at present. Everything **depends on a
   logged-in Workspace desktop app on the same machine**, so this route cannot run on a server.
4. **Restricted by entitlement:** nothing observed for the validated fields. Whether our licence
   limits the AIS source is unknown.
5. **Unavailable or unsuitable for the required workflow:**
   - historical "vessels in area at time T";
   - intraday date filtering;
   - dense history for 2019/2020 (≈ 4 reports per vessel-day);
   - course in old history;
   - per-position source or quality flags;
   - complete SCS fishing coverage;
   - unambiguous MMSI identity over time.

**Verdict:**
- **AIS map:** usable only for **recent** dates, and labelled as an incomplete commercial-fleet layer.
- **Satellite matching:** technically usable for **recent** imagery in a bounded AOI, with
  the same caveat.
- **Our historical demo scenes:** neither.

## 10. Recommended next integration step

1. **Recent-scene demo.** Use Planetary Computer STAC to find a Sentinel-1 acquisition over an SCS
   AOI from the last few days. Run the recent-reconstruction method at its acquisition time, and
   **persist** the pulled positions locally (git-ignored) for reproducibility. Never query live
   during a demo. Label the layer "LSEG Workspace AIS (subset)".
2. **Historical scenes.** Keep GFW's AIS-matched detections as the labelled comparison layer.
   - For SCS AIS, request a GFW API token.
   - For raw-AIS validation of the North Sea xView3 scene, use DMA raw AIS (Danish waters, 2020).
3. **Ask LSEG** (account manager):
   - AIS source and entitlement scope (terrestrial/satellite; China coverage);
   - any historical by-area product (bulk AIS or Shipping Analytics);
   - a platform-session licence for a server;
   - a Vessel Tracking API key;
   - display and redistribution rights in our app.
4. **Engineering.** Promote `shadow_ship_spotter/data/lseg.py` into an "AIS provider" interface
   with a cache. Matching must check position and time consistency, never rely on MMSI alone.

## Reproduce

```bash
uv sync --all-groups                      # includes the `lseg` group (lseg-data)
# Workspace desktop running + logged in; .env contains EIKON_APP_KEY=...
uv run python -I scripts/probe_lseg_shipping.py
uv run python -I scripts/probe_lseg_shipping.py --scene <ESA name> --window-hours 3 \
    --mmsi 244577000 --imo 9580376 --bbox 108.5 17.5 111.5 19.5 --recent-lag-hours 3
```

**Outputs** (git-ignored), written to `data/raw/lseg/probe_<UTC>/`:
- `assessment.json`;
- `resolved_*.csv`, `history_*.csv`, `history_match_*.csv`;
- `area_snapshot_latest.csv`, `recent_reconstructed_layer.csv`, `request_log.csv`;
- `data/raw/lseg/assessment_latest.json` (a copy of the latest assessment).

GFW scene detections used as identifier sources are cached in `data/processed/gfw_scenes/`.
