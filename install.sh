#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required but not installed." >&2
  exit 1
fi

uv sync --python 3.12 --all-groups

echo "Installed. Try: uv run pytest"
