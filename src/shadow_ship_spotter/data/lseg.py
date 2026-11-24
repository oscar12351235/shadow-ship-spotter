"""Helpers for probing vessel data in LSEG Workspace via the LSEG Data Library for Python.

Access route verified on 2026-11-23: *desktop session* (``lseg.data.open_session(app_key=...)``),
which tunnels requests through the "Data API Proxy" of a running, logged-in Workspace desktop
application on 127.0.0.1 (port written to ``.portInUse``). No platform (RDP) credentials are used.

Everything in this module is network-free except :func:`discover_proxy` and
:func:`throttling_limits` (local proxy only), so the parsing/validation logic is unit-testable.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# --- Field sets (verified by actual responses; see docs/lseg_shipping_access_assessment.md) ----
LOCATION_FIELDS = [
    "TR.AssetLocationDate",  # position timestamp, ISO-8601 with "Z" (UTC), second precision
    "TR.AssetLocationLatitude",
    "TR.AssetLocationLongitude",
]
DYNAMIC_FIELDS = [
    "TR.AssetSpeed",  # "AIS Speed" (knots)
    "TR.AssetCourse",  # "AIS Course over Ground" (deg)
    "TR.AssetHeading",  # "AIS Heading" (deg; 511 = not available, AIS convention)
    "TR.AssetLocationStatus",  # "AIS Status" (navigational status)
    "TR.AssetDestination",  # "AIS Destination"
    "TR.AssetETA",
]
STATIC_FIELDS = [
    "TR.AssetName",
    "TR.AssetIMO",
    "TR.AssetMMSI",
    "TR.AssetCallSign",
    "TR.AssetFlag",
    "TR.AssetType",
    "TR.AssetSubType",
    "TR.AssetLOA",  # overall length (m)
    "TR.AssetBeam",  # (m)
    "TR.AssetDWT",
    "TR.AssetStatus",
    "TR.AssetHullType",
    "TR.AssetOwner",
    "TR.AssetLocationType",  # "Polygon Location Type" (geofence relation, not position quality)
]
# Plausible names that are NOT recognised by the backend (request fails with code 414 if sent).
UNRECOGNISED_FIELDS = [
    "TR.AssetLocationSpeed",
    "TR.AssetDraft",
    "TR.AssetBuildYear",
    "TR.AssetLocationSource",
]
SEARCH_SELECT = (
    "RIC,AssetName,IMO,MMSI,RCSAssetTypeLeaf,RCSFlagLeaf,Latitude,Longitude,LocationTimestamp,"
    "LocationSpeed,Heading,AISStatus,VesselStatus,LOA,Beam,Source,DataProviderName"
)
SEARCH_WINDOW_MAX = 10_000  # Search API: (top + skip) must not exceed 10,000
HEADING_NOT_AVAILABLE = 511
KNOT_KMH = 1.852

ERROR_CLASSES = (
    "credential_missing",
    "desktop_unavailable",
    "session_open_failed",
    "connection",
    "rate_limited",
    "entitlement_denied",
    "invalid_field",
    "invalid_identifier",
    "bad_request",
    "no_data",
    "timeout",
    "other",
)


# --- Local Workspace proxy ----------------------------------------------------------------------
def proxy_port_files() -> list[Path]:
    """Known locations of the Data API Proxy port file (macOS, Windows)."""
    files = [Path.home() / "Library" / "Application Support" / "Data API Proxy" / ".portInUse"]
    if appdata := os.environ.get("APPDATA"):
        files.append(Path(appdata) / "Data API Proxy" / ".portInUse")
    return files


def _get_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (localhost only)
        return json.loads(resp.read().decode())


def discover_proxy(default_ports: Sequence[int] = (9000, 9060)) -> dict[str, Any]:
    """Locate the Workspace Data API Proxy and read its status (no credential involved)."""
    ports: list[int] = []
    port_file = None
    for f in proxy_port_files():
        if f.is_file():
            try:
                ports.append(int(f.read_text().strip()))
                port_file = str(f)
                break
            except ValueError:
                pass
    ports += [p for p in default_ports if p not in ports]
    last_error = None
    for port in ports:
        try:
            status = _get_json(f"http://127.0.0.1:{port}/api/status")
            return {
                "reachable": True,
                "port": port,
                "port_file": port_file,
                "status_code": status.get("statusCode"),
                "proxy_version": status.get("version"),
                "ready": status.get("statusCode") == "ST_PROXY_READY",
            }
        except (OSError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    return {"reachable": False, "ports_tried": ports, "port_file": port_file, "error": last_error}


def throttling_limits(port: int) -> dict[str, Any] | None:
    """Remaining request/volume quota reported by the local proxy (desktop session)."""
    try:
        return _get_json(f"http://127.0.0.1:{port}/api/throttling/limits")
    except (OSError, ValueError, urllib.error.HTTPError):
        return None


# --- Errors ---------------------------------------------------------------------------------------
def classify_error(message: str, code: int | None = None) -> str:
    """Map an LSEG error (exception text and/or backend code) to one of ``ERROR_CLASSES``."""
    t = (message or "").lower()
    if code == 429 or "too many requests" in t or "throttl" in t:
        return "rate_limited"
    if code in (403, 906) or any(
        s in t for s in ("permission denied", "not entitled", "not allowed", "entitlement")
    ):
        return "entitlement_denied"
    if code == 414 or "unable to collect data for all requested fields" in t:
        return "invalid_field"
    if code == 415 or "unable to collect data for some field" in t:
        return "no_data"
    if any(s in t for s in ("invalid ric", "invalid identifier", "unable to resolve")):
        return "invalid_identifier"
    if code in (400, 234) or "unexpected in formula" in t or "invalid result window" in t:
        return "bad_request"
    if "timed out" in t or "timeout" in t:
        return "timeout"
    if any(s in t for s in ("connection", "refused", "proxy", "session is not opened", "closed")):
        return "connection"
    return "other"


# --- Data-cloud (get_data) responses ----------------------------------------------------------
def parse_adc(raw: Any) -> tuple[list[str], list[list[Any]], list[dict[str, Any]]]:
    """Return (field headers, rows, per-cell errors) from a fundamental_and_reference raw reply."""
    raw = raw[0] if isinstance(raw, list) else raw
    header_rows = raw.get("headers") or [[]]
    headers = [str(h.get("field") or h.get("displayName")) for h in header_rows[0]]
    return headers, raw.get("data") or [], raw.get("error") or []


def parse_utc(value: Any) -> datetime | None:
    """Parse a provider timestamp carrying an explicit UTC offset."""
    if value in (None, ""):
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return None if dt.tzinfo is None else dt.astimezone(UTC)


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def positions_from_adc(headers: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    """Normalise get_data rows into reported positions (rows without a timestamp are dropped)."""
    idx = {h.upper(): i for i, h in enumerate(headers)}

    def col(row: list[Any], field: str) -> Any:
        i = idx.get(field.upper())
        return row[i] if i is not None and i < len(row) else None

    out = []
    for row in rows:
        t = parse_utc(col(row, "TR.AssetLocationDate"))
        if t is None:
            continue
        heading = _num(col(row, "TR.AssetHeading"))
        out.append(
            {
                "ric": row[0],
                "time_utc": t,
                "lat": _num(col(row, "TR.AssetLocationLatitude")),
                "lon": _num(col(row, "TR.AssetLocationLongitude")),
                "speed_kn": _num(col(row, "TR.AssetSpeed")),
                "course_deg": _num(col(row, "TR.AssetCourse")),
                "heading_deg": None if heading == HEADING_NOT_AVAILABLE else heading,
                "nav_status": col(row, "TR.AssetLocationStatus") or None,
                "position_kind": "reported",  # as delivered by LSEG; no provider quality flag
            }
        )
    return out


def valid_coord(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None or math.isnan(lat) or math.isnan(lon):
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)  # "null island"


def validate_positions(
    positions: list[dict[str, Any]], start: datetime, end: datetime
) -> dict[str, Any]:
    """Check coordinates and that every timestamp lies inside the *requested* interval."""
    times = [p["time_utc"] for p in positions]
    keys = {(p["ric"], p["time_utc"]) for p in positions}
    inside = [start <= t <= end for t in times]
    return {
        "n_positions": len(positions),
        "n_vessels": len({p["ric"] for p in positions}),
        "n_valid_coords": sum(valid_coord(p["lat"], p["lon"]) for p in positions),
        "n_inside_requested_interval": sum(inside),
        "n_outside_requested_interval": len(inside) - sum(inside),
        "n_duplicate_ric_time": len(positions) - len(keys),
        "min_time_utc": min(times).isoformat() if times else None,
        "max_time_utc": max(times).isoformat() if times else None,
    }


# --- Geometry / time -------------------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_position(
    track: list[dict[str, Any]], t: datetime
) -> tuple[dict[str, Any] | None, float | None]:
    """Reported position closest in time to ``t`` and the absolute gap in seconds."""
    best = min(track, key=lambda p: abs((p["time_utc"] - t).total_seconds()), default=None)
    if best is None:
        return None, None
    return best, abs((best["time_utc"] - t).total_seconds())


def interpolate_position(
    track: list[dict[str, Any]], t: datetime, max_gap_s: float
) -> dict[str, Any] | None:
    """Linear lat/lon interpolation between the reports bracketing ``t``.

    Returned only if both neighbours exist and are each within ``max_gap_s`` of ``t``. Marked
    ``position_kind = "interpolated_by_probe"`` so it is never confused with a reported fix.
    """
    pts = sorted((p for p in track if valid_coord(p["lat"], p["lon"])), key=lambda p: p["time_utc"])
    before = [p for p in pts if p["time_utc"] <= t]
    after = [p for p in pts if p["time_utc"] >= t]
    if not before or not after:
        return None
    a, b = before[-1], after[0]
    if (
        any(p["ric"] != a["ric"] for p in pts)
        or abs(a["lon"] - b["lon"]) > 180
        or any(
            len({(p["lat"], p["lon"]) for p in pts if p["time_utc"] == endpoint["time_utc"]}) > 1
            for endpoint in (a, b)
        )
    ):
        return None
    ga, gb = (t - a["time_utc"]).total_seconds(), (b["time_utc"] - t).total_seconds()
    if ga > max_gap_s or gb > max_gap_s:
        return None
    span = ga + gb
    w = 0.0 if span == 0 else ga / span
    return {
        "ric": a["ric"],
        "time_utc": t,
        "lat": a["lat"] + w * (b["lat"] - a["lat"]),
        "lon": a["lon"] + w * (b["lon"] - a["lon"]),
        "gap_before_s": ga,
        "gap_after_s": gb,
        "position_kind": "interpolated_by_probe",
    }


def median_interval_s(track: list[dict[str, Any]]) -> float | None:
    ts = sorted({p["time_utc"] for p in track})
    gaps = sorted((b - a).total_seconds() for a, b in zip(ts, ts[1:], strict=False))
    return gaps[len(gaps) // 2] if gaps else None


def day_params(start: datetime, end: datetime) -> dict[str, str]:
    """SDate/EDate for get_data. The backend's date filter has *day* resolution (time-of-day
    components are ignored), so callers must filter the returned rows to the exact interval."""
    return {"SDate": start.strftime("%Y-%m-%d"), "EDate": end.strftime("%Y-%m-%d")}


# --- Search filters -------------------------------------------------------------------------------
BBox = tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max


def bbox_filter(bbox: BBox) -> str:
    lo, la, hi, ha = bbox
    if lo > hi or la > ha:
        raise ValueError("bbox must be lon_min, lat_min, lon_max, lat_max (no antimeridian wrap)")
    return f"Latitude ge {la} and Latitude le {ha} and Longitude ge {lo} and Longitude le {hi}"


def buffer_bbox(bbox: BBox, km: float) -> BBox:
    lo, la, hi, ha = bbox
    dlat = km / 111.32
    dlon = km / (111.32 * max(math.cos(math.radians(max(abs(la), abs(ha)))), 0.05))
    return (max(lo - dlon, -180), max(la - dlat, -90), min(hi + dlon, 180), min(ha + dlat, 90))


def split_bbox(bbox: BBox) -> list[BBox]:
    lo, la, hi, ha = bbox
    mx, my = (lo + hi) / 2, (la + ha) / 2
    return [(lo, la, mx, my), (mx, la, hi, my), (lo, my, mx, ha), (mx, my, hi, ha)]


def in_bbox(lat: float | None, lon: float | None, bbox: BBox) -> bool:
    if not valid_coord(lat, lon):
        return False
    lo, la, hi, ha = bbox
    return la <= lat <= ha and lo <= lon <= hi  # type: ignore[operator]


def in_filter(prop: str, values: Iterable[str]) -> str:
    vals = " ".join(f"'{v}'" for v in values)
    return f"{prop} in ({vals})"


def search_datetime(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunks(seq: Sequence[Any], n: int) -> Iterator[Sequence[Any]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def normalise_mmsi(value: Any) -> str | None:
    """Keep a supplied nine-digit MMSI. Lost leading digits cannot be reconstructed."""
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return value if len(value) == 9 else None
    f = _num(value)
    if f is None or f <= 0 or not float(f).is_integer():
        return None
    digits = str(int(f))
    return digits if len(digits) == 9 else None


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def hours(h: float) -> timedelta:
    return timedelta(hours=h)
