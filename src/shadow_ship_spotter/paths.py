"""Canonical repository paths. All data paths are relative to the repository root."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # original downloads + extracted archives (git-ignored)
PROCESSED_DIR = DATA_DIR / "processed"  # generated patches/features (git-ignored)
SPLITS_DIR = DATA_DIR / "splits"  # partition assignments (tracked)
INVENTORY_DIR = DATA_DIR / "inventory"  # machine-readable inventories (tracked, small)
SOURCES_FILE = DATA_DIR / "sources.json"  # registry of sources, sizes, checksums (tracked)
FIGURES_DIR = REPO_ROOT / "docs" / "figures"
