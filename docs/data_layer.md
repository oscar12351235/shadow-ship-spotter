# Shadow Ship Spotter data layer

The usable workflow starts with a labelled sample or a named satellite acquisition. A sample
returns pixels, an annotation, its split and its origin. A scene review returns a georeferenced
preview, the outcome of the position query, and a separately labelled published comparison.
The checkout has enough data to compare classifiers on fixed inputs. It has no local SCS
scene with both independently reviewed vessel labels and measured AIS reception.

## Source inventory and access evidence

The locations below are relative to `data/`. Times are acquisition or report times unless
labelled otherwise. File IDs, original checksums and download commands are in
[`sources.json`](../data/sources.json) and the [acquisition guide](../data/README.md).

| Product and role | Acquisition, local format and identity | Coverage, semantics and access limits |
|---|---|---|
| xView3 scene imagery and context | Personal account, manual CSVs and expiring signed archive URLs with publisher SHA-1. `raw/xview3/scenes/<alias>/<alias>/` holds 10 m UTM VV/VH float16 dB GeoTIFFs, nodata −32768. The mapping CSV links the alias to the full ESA name. The 500 m bathymetry, mask and wind rasters have their own grids. | Mapping has 554 train, 50 validation and 150 public entries from 2020 around Europe and West Africa. Local rasters cover Lagos, the North Sea and the Adriatic. Context rasters need an explicit resampling policy before feature use. Fixed research release, CC BY-NC-SA with attribution and access terms. [xView3](https://iuu.xview.us/) |
| xView3 annotations | `raw/xview3/{train,validation}.csv`, keyed by scene and detection ID. Native-grid row/column, lon/lat at the pixel upper-left, vessel/fishing flags, length, source, confidence and optional inclusive box edges. The reader consumes the original validation CSV. | 64,113 training labels are AIS-derived and lack boxes. Confidence encodes vessel class there. The reviewed validation partition contains 19,224 mixed-source labels, including AIS-only rows. The three local scenes have 2,307 annotations. Missing class/length stays unknown. No message timestamps or AIS tracks. SARFish `GRD_*.csv` uses a different pixel grid. The coastline TAR is for the evaluation metric. [Validation measurements](validation_results.md) |
| SSDD benchmark | Publisher's Google Drive RAR, SHA-256 in registry. Original `raw/ssdd/extracted/Official-SSDD-OPEN/BBox_SSDD/coco_style` RGB JPEGs. Pinned per-image and COCO-box inventories, six-digit image IDs and per-JPEG MD5. VOC is a cross-check with different box rounding. | 1,160 images, 2,587 ship boxes, no ship-free images, 34 false-colour crops. Mixed sensors and display scaling. Per-crop parent, time, bands, calibration and geolocation are unknown, so SCS coverage cannot be established. The official split crosses duplicate and overlapping crops. All SSDD samples belong to the separate benchmark in v1. Publisher repository lists Apache-2.0. [Official SSDD](https://github.com/TianwenZhang0825/Official-SSDD) |
| GFW presence/length training tiles | Public Figshare training article v3, file 45487110. `raw/gfw_paolo2024/training/detection_tiles.zip` contains Zarr arrays. Access uses the ZIP central directory and individual Zarr chunks. IDs encode ESA product, longitude and latitude. | 11,965 dual-channel 80 × 80 float16 tiles across 6,578 scenes, 2017-01 to 2021-07. Only 23 tiles in the rough SCS box. Release presence, length and sample weight are classifier targets. Channel order and scaling to physical backscatter are undocumented. GFW's own train/test partitions share two parent scenes. CC BY 4.0. [Training release](https://doi.org/10.6084/m9.figshare.24309469) |
| GFW published SAR predictions | Public Figshare analysis article v4, file 43882980. ZIP/CSV of 23,088,625 detections from 2017–2021. The offline ETL clips rows to 105–122°E, 0–25°N and writes `processed/gfw_sar_detections_scs.parquet`. Filter by full ESA ID and WGS84 area. | 1,812,280 rows across 17,529 scenes in that rectangle. Timestamp, coordinates, matching category, scores and estimated length describe GFW's predictions and matching. Some rows carry a matched MMSI. A reference count covers published rows only. It cannot measure AIS reception, train an independent label set, or supply SSS predictions. CC BY 4.0. [Analysis release](https://doi.org/10.6084/m9.figshare.24309475) |
| Planetary Computer Sentinel-1 GRD | Anonymous STAC and short-lived server-side Azure SAS. Exact full ESA identity comes from the measurement path. Native radar-grid uint16 DN COG, one asset per polarisation with WGS84 GCPs. `raw/planetary_computer/<short-id>/` contains the previous 3,072² crop off Hainan on 2019-03-18. | The old crop TIFFs omit GCPs. Their sidecar records offsets, parent dimensions and GCP count. New remote reads retain the actual GCPs. Acquisition start/stop can be subsecond. Raw DN requires a validated calibration and grid transformation before a calibrated-dB model can use it. Search is online by opt-in. Attribution follows Copernicus and PC terms. [PC collection](https://planetarycomputer.microsoft.com/dataset/sentinel-1-grd) and [asset access](https://planetarycomputer.microsoft.com/docs/concepts/sas/) |
| Copernicus Data Space Sentinel-1 | Anonymous STAC collection and OData exact-product lookup passed. No local CDSE pixel assets. Native product and COG_SAFE distributions have distinct processing/packaging metadata. | One catalogue record matched the historical Hainan SAFE name. Authenticated asset access, conversion and equality to a particular PC grid have not been demonstrated here. A catalogue hit enables discovery only. [STAC](https://documentation.dataspace.copernicus.eu/APIs/STAC.html), [OData](https://documentation.dataspace.copernicus.eu/APIs/OData.html), [COG_SAFE](https://documentation.dataspace.copernicus.eu/Data/Others/Sentinel1_COG.html) |
| LSEG Workspace historical position reports | Local logged-in Workspace plus an app key. The existing acquisition probe requests day-level history by resolved vessel RIC. Named `raw/lseg/probe_<UTC>/history_S1*.csv` and matching `assessment.json` are the offline inputs. UTC report time, lon/lat, speed in kn, course/heading in degrees and status. | The selected run contains 20 Hainan-day and 357 North-Sea-day reports, including reports outside those areas. It sampled identifiers originally selected using GFW. Previous probing found per-identifier history back to at least 2010 for some vessels and a sparse 2019/2020 sample. It did not verify a historical area query or a complete fishing fleet. No per-report receiver or quality flag. Licensed, individual access, redistribution/display rights unresolved. [Local access assessment](lseg_shipping_access_assessment.md) and [LSEG SDK](https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python) |
| LSEG Search, registry and derived probe files | `area_snapshot_latest.csv` and `resolved_S1*.csv` are dated Search exports. `read_search_export` reads a named run, keeps identity candidates and filters the delivered location columns by their own `LocationTimestamp`. | In the 730-row area snapshot, just 639 MMSI strings have nine digits. The reader preserves malformed strings separately. RIC, IMO and MMSI are different identifiers. A present-day registry resolution cannot establish who had an MMSI in 2019. `recent_reconstructed_layer.csv`, `history_match_*.csv` and request logs describe probe processing and diagnostics. They are excluded from observed history. |
| Additional candidates | Separate LSEG Vessel Tracking API, GFW API/portal, Danish historical AIS, US MarineCadastre AIS, SARFish original SAFE imagery and LS-SSDD. These are documented candidates, without local operating adapters for these routes. | The separate LSEG key and GFW token were absent. A gridded presence layer is a derived statistic. Point-level rights, fishing fleet scope and depth need product-specific verification. Danish and US archives support different regions. SARFish imagery needs matching SARFish-grid labels. LS-SSDD is a separate benchmark. [GFW API caveats](https://api-doc.globalfishingwatch.org/our-apis/documentation/docs/v3/general-api-doc/data-caveats), [Danish AIS](https://www.dma.dk/safety-at-sea/navigational-information/ais-data), [MarineCadastre](https://marinecadastre.gov/ais/), [SARFish](https://huggingface.co/datasets/ConnorLuckettDSTG/SARFish), [LS-SSDD](https://github.com/TianwenZhang0825/LS-SSDD-v1.0-OPEN) |

## Why route by product

The inspected GSRAI `ChainedLoader.load` visits **all** enabled children. It adds columns,
fills missing cells on common dates using priority, and appends new weekday rows. Its portfolio,
macro and diversifier families use separate configurations and snapshots. CSV range filtering,
per-provider adapters and explicit ordering transfer well.

SSS has different units of missing work. A raster can be missing a polarisation or part of a
rectangle. A position export samples some identifiers. An empty inference result requires a model
to have run. Combining these as columns would erase their meaning. SSS uses one small ordered
resolver for interchangeable raster reads. Catalogue, training, position, registry and published
prediction readers have their own typed contracts. Only the study boundary composes their results.

GSRAI's base loader forward-fills, periodically refreshes, temporarily changes its start date,
and looks up and prunes previous caches by class. Optional snapshot readers can return empty
frames on exceptions. Portfolio loaders can return proxy history under an instrument name and
unresolved chain references can disappear. None of those semantics is appropriate for dated
observations. Here requests are frozen, checks use exact source identities, and unexpected code
exceptions propagate.

## Product compatibility and priority

Read the table from the requested product to the offered product. The product gate lives in
[`compatibility.py`](../src/shadow_ship_spotter/data/compatibility.py). Identity, extent, units and
grid checks run at read time. A conditional relationship without a verified adapter is rejected.
All unlisted cross-product replacements are rejected.

| Request ← offer | Relationship | Conditions, priority and evidence |
|---|---|---|
| Native historical window ← identical local source or cached PC COG pixels | Equivalent | Full ESA suffix, product, processing revision, band, parent grid and support must agree. A verified cache overlap can be sliced on the native grid. Each read retains source, parent, offset, band, mask and original retrieval timestamp where known. Age alone cannot expire historical pixels. |
| Native DN ← legacy PC crop | Conditional | Verify the full parent, per-band SHA-256, TIFF tags, shape, uint16 type and recorded offsets. Use only the intersection. An 80 × 80 overlap in each installed band matched the original COG range read pixel for pixel. A geographic request requires actual control points. The crop has priority over the COG for eligible pixels. |
| Native DN ← CDSE GRD from the same overpass | Conditional, unsupported | Establish exact ESA product and processing baseline, sample units, polarisation, grid registration and transform/nodata equivalence with test pixels first. CDSE discovery cannot trigger a fallback download. |
| xView3 dB ← GRD DN, log-amplitude display, GFW tiles or SSDD RGB | Incompatible | A display logarithm and release-scaled pixels have no verified conversion to the xView3 product. The dB route accepts the exact xView3 scene/grid only. |
| SAR ← optical | Alternative workflow | Different sensor, preprocessing and model. Requires an explicit new product and evaluation. |
| A selected scene/time ← another acquisition, nearby date or different full suffix | Incompatible | Catalogue search never chooses a substitute date. Grouping two products for split isolation does not make their pixels equivalent. |
| Position reports ← complementary position exports | Complement | Read configured runs in order, filter by actual UTC time and WGS84 area. Merge identical reports by namespaced identifier, instant **and all values**. Preserve all source rows. Keep differing variants at the same key and flag conflict. Priority orders presentation, without resolving a conflict by fiat. |
| Historical reported positions ← a registry, reconstructed layer, xView3 AIS-informed label or GFW match | Complement for registry context, otherwise incompatible | Registry enriches identity candidates. Search location columns can supply separate reported fixes only at their actual timestamps. Publication matches and interpolations never enter the report reader. Raw AIS messages and provider-reported locations are different products. |
| Our model output ← GFW predictions | Complement for comparison | Same ESA scene and requested AOI, with explicit upstream source, matching algorithm and study period. Never fills a missing model output or reviewed label. |
| Reviewed scene labels ← weak labels, tile classes, SSDD boxes or SARFish-grid boxes | Complementary training tasks or incompatible grid | The release and target meaning travel with each example. Pixel transforms are explicit. Weak labels cannot silently enter reviewed evaluation, and original-grid boxes cannot label a reprojected raster. |
| SCS area/time evidence ← Danish/US observations or a different area/date | Alternative research workflow, incompatible replacement | A regional methods study can use a different source and geography explicitly. Its absence or success says nothing about SCS reception. |

The resolver subtracts each successful rectangle from the requested band. The next eligible
source gets the remaining strips. A wholly failed read leaves its whole support outstanding.
The result exposes both the missing rectangles and the ordered attempts. Nodata is a separate
pixel mask. A complete read can contain masked pixels.

## Running the data layer

Run commands from the repository root after the platform installer. A fresh clone has the
inventories, configuration and lock manifest. Raw samples require the corresponding downloads.
`uv run python run.py` and `uv run python -m shadow_ship_spotter` use the same CLI.

```sh
uv run python run.py training gfw-tiles --split test
uv run python run.py training xview3 --split validation
uv run python run.py training xview3 --product xview3-ais-derived-labels --split train
uv run python run.py training ssdd --split benchmark
uv run python run.py scenes --date 2019-03-18 --zone 110.42 18.42 110.48 18.48
uv run python run.py --online study --date 2019-03-18 --bbox 110.42 18.42 110.48 18.48 --scene S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE --product s1-grd-dn
uv run python run.py --no-online study --date 2019-03-18 --bbox 110.42 18.42 110.48 18.48 --scene S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE --product s1-grd-dn
uv run python run.py window --scene S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE --product s1-grd-dn --window 16141 3963 32 32 --bands VV --pixel-only
```

For model code, hold the dataset open across examples. A centre-labelled xView3 chip describes
one annotated object. Other objects in the chip may also be present.
The default xView3 product includes the `manual` and `ais/manual` annotation sources.
Use the explicit weak product for `ais` rows. Filter on `annotation_source == "manual"`
when an evaluation needs labels without recorded AIS involvement. Unknown class targets
remain null. Located samples expose WGS84 longitude/latitude and the sensing interval.

```python
from shadow_ship_spotter.data.training import TrainingSet
from shadow_ship_spotter.paths import DATA_DIR

with TrainingSet(DATA_DIR, "xview3") as dataset:
    example = next(dataset.examples("validation"))
    sample = dataset.read(example.id)
    pixels, target = sample.pixels, example.presence
    # Both experiments consume this same masked C,H,W array and split.
```

[`training-v1.json`](../data/splits/training-v1.json) pins input bytes and split policy.
Hashes are checked on first use in a dataset session. SSDD checks each JPEG against the pinned
inventory. GFW opens the pinned ZIP directly. xView3 reads a native window from each pinned
band. Split assignment is deterministic by platform, absolute orbit and datatake, across datasets
and processing variants. Three explicit group assignments keep each local xView3 scene in its
own partition. This is a three-scene pilot. It cannot establish SCS model performance. SSDD's
unknown parents preclude a claim of scene-independent evaluation, even after duplicate grouping.

[`loading.toml`](../data/loading.toml) selects the ordered raster sources, enabled network
access, required layers and named LSEG runs. Unknown keys, misspelled references, duplicate
providers, unsupported products and network-before-local ordering fail validation. `--data`
selects another data root and `--config` selects another policy. Online access is opt-in.
An explicit zone takes precedence over the viewport. Both use west, south, east, north in
EPSG:4326. Split a viewport crossing the antimeridian into two requests. Times use explicit
offsets, normalized to UTC, and half-open windows.

## Storage, failure handling and evidence

- `catalog.py` filters actual PC polygons and xView3 raster envelopes. It reports which kind
  intersected the AOI. The envelope includes nodata. Offline search describes indexed assets
  only. Online enumeration follows STAC pages and preserves partial hits if a later page fails.
- `imagery.py` reads bounded windows. `geo.py` uses projected affine transforms or the
  parent radar GCPs. GCP positions are approximate. Pixel masks, raw units and band order stay
  explicit. Exported PC previews carry shifted GCPs and versioned source/window identity.
  Grid discovery reads metadata alone and can replay the parent grid from any cached window
  for the exact band. The study reports joint valid pixels across the requested bands.
- `storage.py` stages files and extracted trees in the destination filesystem. Archive digests
  are checked before publication. A PC cache transaction publishes bytes, SHA-256, receipt
  and rectangle index together. The key includes the reader version, source, product, complete
  scene, native rectangle and band. A cache hit retains the remote retrieval time. A different
  revision is a different key. Separate source datasets are never pruned together.
- `http.py` sets timeouts and retries transient transport/HTTP failures up to three attempts.
  It honours bounded Retry-After delays and surfaces longer waits to the caller. Access denials
  are terminal for that source. Only a strong ETag permits resuming a transfer during a retry.
  PC signs in the server process. Restricted rows, app keys, xView3 lists and SAS tokens stay
  out of public summaries and version control.
- `reference.py` uses Parquet predicate and column pushdown. New derivatives carry the source
  release, clip and processing version in their footer. The earlier derived file is accepted
  by its recorded SHA-256. A different unversioned file must be rebuilt from the pinned archive.
  The LSEG acquisition probe uses a separate whole-scene projection for selecting lookup
  candidates. The two earlier scene extracts were compared against the global release and
  pinned. A regional derivative is eligible only when it covers the full scene footprint.
- `observations.py` verifies the named probe's assessment, row counts, field names, time
  envelope, coordinates and row kind. A run start and an individual provider retrieval are
  different facts. Unknown retrieval/update timestamps stay null. Loading performs no
  interpolation. The separate LSEG diagnostic may interpolate between two same-RIC bracketing
  reports within its per-side limit. It labels the estimate and retains the two gaps.
  New probe exports use the full scene identifier. A legacy truncated filename is accepted
  only when exactly one identifier in the run receipt could refer to it.
- `study.py` returns serializable evidence for a selected acquisition. Its raster check covers
  a bounded preview of the intersection. The response reports footprint coverage and preview
  quality separately. A partial footprint keeps the study partial even when every preview
  pixel is valid. `inputs_ready` requires coverage and successful reads for the configured
  inputs. A successful empty query returns zero. An unavailable or failed layer returns a
  null count and the reason. Optional failures stay in the response.
  The private Python readers expose individual records. The application summary exposes counts
  and provenance. A model-generated evidence panel will need the model version, score, pixel
  window and scene, linked to the input receipts and the matching evidence.

## Verification on 2026-11-24

The deterministic suite uses temporary files, synthetic measurements and fake HTTP responses.
Run `uv run pytest`, `uv run ruff check .`, `uv run black --check .` and `uv run mypy src`.
The live metadata check is a separate command, `uv run python -I scripts/check_source_access.py`.
All 79 offline tests passed. Ruff passed, Black checked 39 Python files and mypy checked 22
package files. All six notebook code cells executed in both the full checkout and an
inventories-only checkout. The uv lockfile passed its offline consistency check.

| Actual run | Observed result |
|---|---|
| Read one sample from every local family | Masked xView3 VV/VH 2 × 80 × 80, GFW release channels 2 × 80 × 80, original SSDD RGB 3 × 323 × 416. In train/validation/test order, xView3 has 715/489/1,076 reviewed annotations and 7/17/3 AIS-only annotations. GFW has 8,820/1,533/1,612 tiles. SSDD has 1,160 benchmark samples. |
| Hainan date/viewport above | Online STAC search returned the exact acquisition. Both preview bands had 6,400 valid DN samples and 231 parent GCPs. The offline replay read both bands from the verified cache. The viewport contained six published GFW predictions and zero LSEG reports in the selected interval. Population coverage was unknown. |
| Existing preview script | An offline 80-pixel preview wrote GeoTIFFs, metadata and a figure. Its pixel window is smaller than the study viewport. It contained zero of the six published viewport predictions. |
| North Sea on 2020-09-28 | The raster covered part of the zone 3.8–8.9°E, 54.7–57.3°N. Both xView3 dB bands had 6,400 valid preview pixels. The selected export supplied eight report variants near acquisition with unknown population coverage. The SCS reference layer reported that this scene was outside its extent. |
| Whole-scene extracts used by the LSEG probe | All seven lookup fields for 461 Hainan and 128 North Sea GFW prediction rows agreed with the original global CSV. These are the original probe's sampling frame. |
| Release and access checks | Figshare returned the recorded MD5s for both files. The local 1.7 GB analysis ZIP matched. All six local xView3 label/mapping/shoreline SHA-1 checks matched their publisher entries. CDSE returned one exact SAFE catalogue record. Workspace proxy unreachable with an app key configured. No fresh LSEG, authenticated CDSE download or GFW AIS API result is claimed. |

Remaining evidence gaps are calibrated, grid-validated SCS model inputs, independently evaluated
SCS predictions, an entitled position source for the chosen historical area/time, and a measured
reception policy for assessing unmatched detections. The current output reports
`model=not_run` and `matching=insufficient_ais_information`. An unmatched record alone
establishes neither nationality, illegal activity nor deliberate AIS disablement.
