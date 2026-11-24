from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from shadow_ship_spotter.data import http
from shadow_ship_spotter.data.contracts import SourceError, State
from shadow_ship_spotter.data.download import download
from shadow_ship_spotter.data.storage import BlobCache, publish_directory, staged_file


class Response(io.BytesIO):
    def __init__(self, data, status=200, **headers):
        super().__init__(data)
        self.status = status
        self.headers = headers


def test_interruption_does_not_publish_or_replace(tmp_path):
    dest = tmp_path / "immutable"
    dest.write_bytes(b"previous")
    with pytest.raises(OSError), staged_file(dest) as work:
        work.write_bytes(b"cut off")
        raise OSError("interrupted")
    assert list(tmp_path.iterdir()) == [dest] and dest.read_bytes() == b"previous"

    def fail(stage):
        (stage / "partial").touch()
        raise OSError("interrupted")

    with pytest.raises(OSError):
        publish_directory(tmp_path / "scene", fail, lambda p: (p / "complete").is_file())
    assert not (tmp_path / "scene").exists()
    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(SourceError, match="incomplete extraction"):
        publish_directory(broken, fail, lambda p: False)


def test_concurrent_cache_writers_keep_distinct_and_complete_objects(tmp_path):
    cache = BlobCache(tmp_path / "nested/cache.sqlite")

    def put(i):
        cache.put(str(i), str(i).encode() * 100)
        cache.put("shared", str(i).encode() * 100)

    with ThreadPoolExecutor(6) as workers:
        list(workers.map(put, range(12)))
    assert all(cache.get(str(i)) == str(i).encode() * 100 for i in range(12))
    assert cache.get("shared") in [str(i).encode() * 100 for i in range(12)]


def test_range_resume_checks_entity_and_integrity_before_publish(tmp_path, monkeypatch):
    dest = tmp_path / "source.zip"
    calls = []

    def serve(req, timeout):
        assert timeout > 0
        calls.append(dict(req.header_items()))
        if len(calls) == 1:
            return Response(b"abc", **{"Content-Length": "6", "ETag": '"v1"'})
        return Response(b"def", 206, **{"Content-Length": "3", "Content-Range": "bytes 3-5/6"})

    monkeypatch.setattr(urllib.request, "urlopen", serve)
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    digest = hashlib.sha256(b"abcdef").hexdigest()
    assert download("https://example.org/archive", dest, 6, checksum=("sha256", digest)) == dest
    assert calls[1]["Range"] == "bytes=3-" and calls[1]["If-range"] == '"v1"'
    with pytest.raises(SourceError, match="mismatch"):
        download("https://example.org/archive", dest, 6, checksum=("sha256", "0" * 64))
    assert dest.read_bytes() == b"abcdef"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: Response(b"bad"))
    with pytest.raises(SourceError, match="mismatch"):
        download("https://example.org/archive", tmp_path / "bad", checksum=("sha256", digest))
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize(
    ("status", "wait", "attempts", "state"),
    [
        (401, None, 1, State.ACCESS),
        (403, None, 1, State.ACCESS),
        (429, "99", 1, State.UNAVAILABLE),
        (429, "0", 3, State.UNAVAILABLE),
        (503, None, 3, State.UNAVAILABLE),
    ],
)
def test_bounded_http_failures_are_sanitised(monkeypatch, status, wait, attempts, state):
    calls = []
    url = "https://example.org/?secret=never-print"

    def fail(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError(
            url, status, "blocked", {"Retry-After": wait} if wait else {}, io.BytesIO()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    monkeypatch.setattr(http.time, "sleep", lambda _: None)
    with pytest.raises(SourceError) as err:
        http.get_json(url)
    assert err.value.state == state and "never-print" not in str(err.value)
    assert len(calls) == attempts


def test_bad_json_is_a_data_error(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: Response(b"<html>"))
    with pytest.raises(SourceError) as err:
        http.get_json("https://example.org/")
    assert err.value.state == State.CORRUPT
