"""Small, bounded HTTPS reads. Diagnostics never contain request URLs, tokens or bodies."""

from __future__ import annotations

import http.client
import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from .contracts import SourceError, State

USER_AGENT = "shadow-ship-spotter/1"
LOG = logging.getLogger(__name__)


def retry_delay(value: str | None, attempt: int) -> float:
    if value is None:
        return 0.25 * 2**attempt
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return 0.25 * 2**attempt


def transfer[T](request: urllib.request.Request, consume: Callable[[Any], T]) -> T:
    for attempt in range(3):
        delay = 0.25 * 2**attempt
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return consume(response)
        except urllib.error.HTTPError as exc:
            code = exc.code
            delay = retry_delay(exc.headers.get("Retry-After"), attempt)
            exc.close()
            if code in (401, 403):
                raise SourceError(State.ACCESS, f"HTTP {code}") from None
            if code not in (408, 429, 500, 502, 503, 504):
                state = State.UNAVAILABLE if code in (404, 410) else State.INCOMPATIBLE
                raise SourceError(state, f"HTTP {code}") from None
            detail = f"HTTP {code}"
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            socket.gaierror,
            http.client.IncompleteRead,
        ) as exc:
            detail = type(exc).__name__
        if attempt == 2 or delay > 5:
            raise SourceError(State.UNAVAILABLE, f"provider request failed ({detail})")
        LOG.info("retry %d after %s", attempt + 1, detail)
        time.sleep(delay)
    raise AssertionError("unreachable")


def get_json(url: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
    )

    def decode(response: Any) -> dict:
        raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise SourceError(State.CORRUPT, "metadata response exceeded size limit")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SourceError(State.CORRUPT, "invalid metadata JSON") from None
        if not isinstance(value, dict):
            raise SourceError(State.CORRUPT, "expected an object as provider metadata")
        return value

    return transfer(request, decode)
