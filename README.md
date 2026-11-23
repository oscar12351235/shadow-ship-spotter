# SSS: Shadow Ship Spotter

University ML project: detect vessels in Sentinel-1 radar imagery, compare them with AIS, and
reveal detections that cannot be matched to available AIS records — on an interactive map
("start with the AIS-visible picture, then reveal what satellite imagery adds"). Target region:
South China Sea fishing activity. An unmatched detection does **not** establish nationality,
illegal fishing or deliberate AIS disabling.

**Project status and full context for new contributors/agents: [`context.md`](context.md).**

## Setup

macOS/Linux: `./install.sh` · Windows: `.\install.bat` (both run `uv sync --python 3.12 --all-groups`).

## Data (step 2 — acquisition and validation)

- What we use and why: [`docs/data_sources.md`](docs/data_sources.md)
- Validation results: [`docs/validation_results.md`](docs/validation_results.md)
- Data for the AIS map / "Reveal hidden vessels": [`docs/map_reveal_data_assessment.md`](docs/map_reveal_data_assessment.md)
- Layout + reproduction commands: [`data/README.md`](data/README.md); registry: [`data/sources.json`](data/sources.json)
- Inspection notebook: [`notebooks/01_data_inspection.ipynb`](notebooks/01_data_inspection.ipynb)

Large data lives in `data/raw/` and `data/processed/` and is never committed. xView3 requires a
personal account; its signed download links must never be committed or shared.

## Common commands

```bash
uv run pytest
uv run black .
uv run ruff check .
uv run mypy src
```
