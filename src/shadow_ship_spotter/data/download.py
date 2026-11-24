"""Streaming archive downloads for the acquisition scripts using the standard HTTP library.

Features: atomic streamed downloads with bounded retries, HTTP Range during retries,
Google Drive large-file confirmation handling, and checksum verification.
"""

from __future__ import annotations

import hashlib
import html
import http.client
import re
import sys
import time
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from .contracts import SourceError, State
from .http import USER_AGENT, transfer
from .storage import staged_file

CHUNK = 1 << 20  # 1 MiB


def file_hash(path: Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=32)
def _snapshot_digest(path: Path, identity: tuple[int, int, int, int]) -> str:
    return file_hash(path)


def snapshot_sha256(path: Path) -> str:
    """Reuse a local digest only while file identity, size and timestamps still agree."""
    st = path.stat()
    return _snapshot_digest(path.resolve(), (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))


def _stream_to(resp, part: Path, append: bool, total: int | None) -> None:
    mode = "ab" if append else "wb"
    done = part.stat().st_size if append and part.exists() else 0
    t0, last = time.time(), 0.0
    with part.open(mode) as out:
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            out.write(block)
            done += len(block)
            now = time.time()
            if now - last > 2:
                last = now
                rate = done / max(now - t0, 1e-6) / 1e6
                pct = f"{100 * done / total:5.1f}%" if total else "  ?  "
                print(
                    f"\r  {pct} {done / 1e6:9.1f} MB  ({rate:5.1f} MB/s)", end="", file=sys.stderr
                )
    print(file=sys.stderr)


def download(
    url: str,
    dest: Path,
    expected_size: int | None = None,
    *,
    checksum: tuple[str, str] | None = None,
) -> Path:
    """Validate before publishing. Concurrent requests never append to a shared partial file."""

    def validate(path: Path) -> None:
        if expected_size is not None and path.stat().st_size != expected_size:
            raise SourceError(State.CORRUPT, f"{dest.name}: size mismatch")
        if checksum and file_hash(path, checksum[0]) != checksum[1]:
            raise SourceError(State.CORRUPT, f"{dest.name}: {checksum[0]} mismatch")

    if dest.exists():
        validate(dest)
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with staged_file(dest) as stage:

        def consume(resp: Any) -> None:
            start = stage.stat().st_size
            resume = resp.status == 206
            if resume and (
                not req.has_header("Range")
                or not resp.headers.get("Content-Range", "").startswith(f"bytes {start}-")
            ):
                raise SourceError(State.CORRUPT, "invalid Content-Range")
            length = resp.headers.get("Content-Length")
            total = (int(length) + (start if resume else 0)) if length else expected_size
            try:
                _stream_to(resp, stage, append=resume, total=total)
                if total is not None and stage.stat().st_size < total:
                    raise http.client.IncompleteRead(b"")
            finally:
                # Resume only with a strong entity validator; a changed object restarts with 200.
                etag = resp.headers.get("ETag", "")
                if etag and not etag.startswith("W/"):
                    req.add_header("Range", f"bytes={stage.stat().st_size}-")
                    req.add_header("If-Range", etag)
                else:
                    req.remove_header("Range")
                    req.remove_header("If-range")

        transfer(req, consume)
        validate(stage)
    return dest


def gdrive_direct_url(file_id: str) -> str:
    """Resolve the direct download URL for a public Google Drive file.

    Files larger than ~100 MB return an HTML "virus scan warning" page containing a form
    (id/export/confirm/uuid). We parse that form and build the confirmed URL.
    """
    base = "https://drive.usercontent.google.com/download"
    url = f"{base}?id={file_id}&export=download"
    page = transfer(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
        lambda resp: (
            resp.read(200_000).decode("utf-8", "replace")
            if resp.headers.get("Content-Type", "").startswith("text/html")
            else None
        ),
    )
    if page is None:
        return url
    fields = dict(re.findall(r'name="([a-z]+)" value="([^"]*)"', page))
    if "confirm" not in fields:
        raise RuntimeError("Google Drive did not return a download or confirmation form")
    fields = {k: html.unescape(v) for k, v in fields.items()}
    return f"{base}?{urllib.parse.urlencode(fields)}"


def verify(path: Path, sha256: str | None, size: int | None) -> str:
    """Return the sha256 of ``path``; raise if it does not match the recorded values."""
    if size is not None and path.stat().st_size != size:
        raise RuntimeError(f"{path.name}: size {path.stat().st_size} != recorded {size}")
    digest = file_hash(path, "sha256")
    if sha256 and digest != sha256:
        raise RuntimeError(f"{path.name}: sha256 {digest} != recorded {sha256}")
    return digest
