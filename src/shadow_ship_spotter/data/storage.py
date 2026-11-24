"""Atomic publication of files and a transactional, exact-request cache for bounded reads."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from .contracts import SourceError, State, Window


@contextmanager
def staged_file(dest: Path) -> Iterator[Path]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    os.close(fd)
    stage = Path(name)
    try:
        yield stage
        with stage.open("rb") as f:
            os.fsync(f.fileno())
        os.replace(stage, dest)
    finally:
        stage.unlink(missing_ok=True)


def write_json(dest: Path, obj: object) -> None:
    with staged_file(dest) as stage:
        stage.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def publish_directory(
    dest: Path, build: Callable[[Path], None], validate: Callable[[Path], bool]
) -> None:
    """Build out of sight. An interrupted or incomplete previous tree never counts as a hit."""

    def check(path: Path) -> None:
        if not validate(path):
            raise SourceError(State.CORRUPT, f"incomplete extraction: {dest.name}")

    if dest.exists():
        check(dest)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{dest.name}-", dir=dest.parent) as tmp:
        root = Path(tmp) / "tree"
        root.mkdir()
        build(root)
        check(root)
        try:
            root.rename(dest)
        except OSError:
            if not dest.is_dir():
                raise
            check(dest)  # a concurrent builder published first


class BlobCache:
    """A row publishes identity, receipt, digest and bytes in one SQLite transaction."""

    def __init__(self, path: Path):
        self.path = path

    def get(self, key: str) -> bytes | None:
        if not self.path.is_file():
            return None
        try:
            with closing(
                sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            ) as db:
                # A first writer may be creating the database concurrently.
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='objects'").fetchone():
                    return None
                row = db.execute(
                    "SELECT digest,payload FROM objects WHERE identity=?", (key,)
                ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise self._error(exc) from None
        if row is None:
            return None
        digest, payload = row
        if hashlib.sha256(key.encode() + payload).hexdigest() != digest:
            raise SourceError(State.CORRUPT, "cache entry failed SHA-256 verification")
        return bytes(payload)

    @staticmethod
    def _error(exc: sqlite3.DatabaseError) -> SourceError:
        state = State.UNAVAILABLE if isinstance(exc, sqlite3.OperationalError) else State.CORRUPT
        return SourceError(state, f"window cache: {getattr(exc, 'sqlite_errorname', 'IO error')}")

    def first_window(self, family: str) -> str | None:
        return self._window_key(
            "SELECT identity FROM windows WHERE family=? "
            "ORDER BY (x1-x0)*(y1-y0),identity LIMIT 1",
            (family,),
        )

    def overlap(self, family: str, w: Window) -> str | None:
        return self._window_key(
            "SELECT identity FROM windows WHERE family=? AND x0<? AND x1>? "
            "AND y0<? AND y1>? ORDER BY "
            "(min(x1,?)-max(x0,?))*(min(y1,?)-max(y0,?)) DESC, "
            "(x1-x0)*(y1-y0), identity LIMIT 1",
            (family, w.right, w.col, w.bottom, w.row, w.right, w.col, w.bottom, w.row),
        )

    def _window_key(self, sql: str, params: tuple) -> str | None:
        if not self.path.is_file():
            return None
        try:
            with closing(
                sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
            ) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='windows'").fetchone():
                    return None
                row = db.execute(sql, params).fetchone()
                return row[0] if row else None
        except sqlite3.DatabaseError as exc:
            raise self._error(exc) from None

    def put(self, key: str, payload: bytes, *, coverage: tuple[str, Window] | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(key.encode() + payload).hexdigest()
        try:
            with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS objects "
                    "(identity TEXT PRIMARY KEY, digest TEXT NOT NULL, payload BLOB NOT NULL)"
                )
                db.execute("INSERT OR REPLACE INTO objects VALUES (?,?,?)", (key, digest, payload))
                if coverage:
                    family, w = coverage
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS windows (identity TEXT PRIMARY KEY, "
                        "family TEXT,x0 INTEGER,y0 INTEGER,x1 INTEGER,y1 INTEGER)"
                    )
                    db.execute("CREATE INDEX IF NOT EXISTS family_extent ON windows(family,x0,x1)")
                    db.execute(
                        "INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?)",
                        (key, family, w.col, w.row, w.right, w.bottom),
                    )
        except sqlite3.DatabaseError as exc:
            raise self._error(exc) from None
