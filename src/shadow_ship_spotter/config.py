"""Minimal, dependency-free loader for local secrets in the repository's ``.env`` file.

The file is git-ignored. Values are never printed or logged by this module; callers should
only report *whether* a variable is set (see :func:`describe_env`).
"""

from __future__ import annotations

import os
from pathlib import Path

from shadow_ship_spotter.paths import REPO_ROOT

DOTENV_PATH = REPO_ROOT / ".env"


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines (``export`` prefix, comments and single/double quotes allowed)."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key.isidentifier():
            values[key] = value
    return values


def load_dotenv(path: Path = DOTENV_PATH, override: bool = False) -> list[str]:
    """Load ``path`` into ``os.environ``; existing variables win unless ``override``.

    Returns the names (not values) of the variables that were set.
    """
    if not path.is_file():
        return []
    loaded = []
    for key, value in parse_dotenv(path.read_text(encoding="utf-8")).items():
        if override or key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def get_secret(name: str) -> str | None:
    """Return a non-empty secret from the environment (after loading ``.env``), else ``None``."""
    load_dotenv()
    value = os.environ.get(name, "").strip()
    return value or None


def describe_env(names: list[str]) -> dict[str, bool]:
    """Report which of ``names`` are set, without exposing any value."""
    load_dotenv()
    return {name: bool(os.environ.get(name, "").strip()) for name in names}
