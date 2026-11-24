"""Small, dependency-free download helpers (stdlib only) used by the acquisition scripts.

Features: streamed download with progress, resume of partial files via HTTP Range,
Google Drive large-file confirmation handling, and checksum verification.
"""

from __future__ import annotations

import hashlib
import html
import http.client
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "shadow-ship-spotter-data-fetch/0.1"
CHUNK = 1 << 20  # 1 MiB


def file_hash(path: Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _open(url: str, start: int = 0) -> http.client.HTTPResponse:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if start:
        req.add_header("Range", f"bytes={start}-")
    return urllib.request.urlopen(req, timeout=120)  # noqa: S310 (fixed https URLs)


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


def download(url: str, dest: Path, expected_size: int | None = None) -> Path:
    """Download ``url`` to ``dest`` (resuming ``dest.part`` if present)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  exists, skipping download: {dest}", file=sys.stderr)
        return dest
    part = dest.with_name(dest.name + ".part")
    start = part.stat().st_size if part.exists() else 0
    resp = _open(url, start)
    resumed = start > 0 and resp.status == 206
    length = resp.headers.get("Content-Length")
    total = (int(length) + (start if resumed else 0)) if length else expected_size
    if start and not resumed:
        print("  server ignored Range; restarting download", file=sys.stderr)
    _stream_to(resp, part, append=resumed, total=total)
    if expected_size is not None and part.stat().st_size != expected_size:
        raise RuntimeError(
            f"size mismatch for {dest.name}: got {part.stat().st_size}, expected {expected_size}"
        )
    shutil.move(part, dest)
    return dest


def gdrive_direct_url(file_id: str) -> str:
    """Resolve the direct download URL for a public Google Drive file.

    Files larger than ~100 MB return an HTML "virus scan warning" page containing a form
    (id/export/confirm/uuid). We parse that form and build the confirmed URL.
    """
    base = "https://drive.usercontent.google.com/download"
    url = f"{base}?id={file_id}&export=download"
    resp = _open(url)
    ctype = resp.headers.get("Content-Type", "")
    if not ctype.startswith("text/html"):
        resp.close()
        return url
    page = resp.read(200_000).decode("utf-8", "replace")
    resp.close()
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
