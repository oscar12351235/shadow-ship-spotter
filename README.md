# SSS: Shadow Ship Spotter

A university machine-learning project that is meant to become a working application.
- **Input:** satellite radar images (Sentinel-1 SAR) of the sea, where ships appear as bright
  points whatever the weather or time of day.
- **Project goal:** detect ships, compare them with timestamped position reports and show the
  matching evidence on an interactive map.
- **The interaction:** start with the AIS-visible picture, then press "Reveal hidden vessels" to
  see what the satellite adds.
- **Target:** fishing activity in the South China Sea, for fisheries authorities deciding where to
  focus limited monitoring.

An unmatched detection does **not** prove illegal fishing, nationality, or a deliberately disabled
transponder. AIS coverage may simply be poor, or the boat too small to carry AIS.

**Full project context** (status, every data source explained, every file explained, decisions,
next steps): [`context.md`](context.md).

## Using the data layer

After installation, run `uv run python run.py --help`. The default is offline.
With the corresponding raw files installed, these commands load real inputs:

```sh
uv run python run.py training xview3 --split validation
uv run python run.py training gfw-tiles --split test
uv run python run.py scenes --date 2019-03-18 --zone 110.42 18.42 110.48 18.48
```

The [data-layer guide](docs/data_layer.md) includes the source inventory, enforced compatibility
matrix, configuration, archived scene review, live checks and offline replay. The review returns
input evidence and AIS coverage limitations. Model training, inference, matching and the map UI
are subsequent stages.

## Where the project is now (2026-11-24)

- ✅ **Step 2 (data foundation):**
  - training/evaluation data downloaded and validated: xView3-SAR scenes and labels, SSDD, GFW
    detection tiles;
  - satellite imagery access for the South China Sea proven (Planetary Computer, no account);
  - GFW's AIS-matched detections available as a comparison layer.
- ✅ **Position-source investigation:** LSEG Workspace returned selected-vessel historical
  reports and a dated commercial-fleet snapshot. Historical area coverage in the South China
  Sea remains unknown.
- The versioned pilot split and native chip readers work for training and evaluation. The
  archived Hainan scene can be reviewed by date and viewport. Its native DN preview still needs
  validated calibration before use by a model trained on xView3 dB imagery.

## Setup

- macOS/Linux: `./install.sh`
- Windows: `.\install.bat`

Both run `uv sync --python 3.12 --all-groups` and require [uv](https://docs.astral.sh/uv/).

Local secrets (e.g. the LSEG app key) go in a git-ignored `.env`; see `.env.example`.

## Where to find things

| You want to know… | Read |
|---|---|
| Everything, from scratch | [`context.md`](context.md) |
| Loading policy, verified workflows and product compatibility | [`docs/data_layer.md`](docs/data_layer.md) |
| What each data source contains, what it is for, whether it is useful, licences | [`docs/data_sources.md`](docs/data_sources.md) |
| What was checked on each dataset and the results | [`docs/validation_results.md`](docs/validation_results.md) |
| What the map and "Reveal hidden vessels" need, and realistic demo routes | [`docs/map_reveal_data_assessment.md`](docs/map_reveal_data_assessment.md) |
| Whether LSEG Workspace (Eikon) can supply AIS | [`docs/lseg_shipping_access_assessment.md`](docs/lseg_shipping_access_assessment.md) |
| Data folder layout and exact reproduction commands | [`data/README.md`](data/README.md); registry [`data/sources.json`](data/sources.json) |
| A visual look at the data | [`notebooks/01_data_inspection.ipynb`](notebooks/01_data_inspection.ipynb), [`docs/figures/`](docs/figures/) |

**Rules for data and secrets:**
- Large data lives in `data/raw/` and `data/processed/` and is never committed.
- xView3 requires a personal account; its signed download links must never be committed or shared.
- LSEG data samples are licensed and stay local.

## Common commands

```bash
uv run pytest          # unit tests
uv run black .         # format
uv run ruff check .    # lint
uv run mypy src        # type-check
```
