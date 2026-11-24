"""Bounded probe of LSEG Workspace vessel data (positions, identifiers, history, area search,
fishing coverage) for the Shadow Ship Spotter AIS map layer and SAR-detection matching.

Requires: LSEG Workspace desktop app running and logged in on this machine (desktop session via
the local Data API Proxy) and ``EIKON_APP_KEY`` in the git-ignored ``.env``. The key is never
printed or written. Optional ``VESSEL_TRACKING_API_KEY`` enables a test of the separate Vessel
Tracking API; without it only an unauthenticated reachability check is made.

Usage (repository root):
    uv sync --group lseg            # lseg-data (already included by ./install.sh)
    uv run python -I scripts/probe_lseg_shipping.py
    uv run python -I scripts/probe_lseg_shipping.py \
        --scene S1A_IW_GRDH_1SDV_20200928T171800_20200928T171831_034562_0405EA_F164 \
        --window-hours 3 --max-vessels 40 --mmsi 244577000 --imo 9580376 \
        --bbox 108.5 17.5 111.5 19.5 --recent-lag-hours 3

Vessel identifiers come from GFW's AIS-matched SAR detections of the same Sentinel-1 scenes
(``data/processed``; Paolo et al. 2024) and/or --mmsi/--imo/--ric. MMSI/IMO are resolved to LSEG
vessel RICs (``C}...``) through the Search API; they are never assumed interchangeable.

Outputs (git-ignored; LSEG data is licensed for individual use, do not commit/redistribute):
    data/raw/lseg/probe_<UTC stamp>/assessment.json   all results and summary statistics
    data/raw/lseg/probe_<UTC stamp>/*.csv             small samples (positions, resolution, ...)
    data/raw/lseg/assessment_latest.json              copy of the latest assessment
Exit codes: 0 ok, 2 credential missing, 3 desktop session unavailable, 4 session open failed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
import zipfile
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from shadow_ship_spotter.config import describe_env, get_secret
from shadow_ship_spotter.data import lseg as L
from shadow_ship_spotter.paths import PROCESSED_DIR, RAW_DIR

SCENES = [
    "S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE",  # Hainan / SCS
    "S1A_IW_GRDH_1SDV_20200928T171800_20200928T171831_034562_0405EA_F164",  # North Sea (xView3)
]
DEFAULT_BBOX = (108.5, 17.5, 111.5, 19.5)  # lon_min, lat_min, lon_max, lat_max: off Hainan
COVERAGE_REGIONS = {
    "south_china_sea": (105.0, 0.0, 122.0, 25.0),
    "north_sea_xview3_scene": (3.8, 54.7, 8.9, 57.2),
    # dense-traffic references, to tell feed-wide sparsity from regional gaps
    "singapore_strait_ref": (103.5, 1.0, 104.5, 1.5),
    "dover_strait_ref": (1.0, 50.8, 2.0, 51.3),
}
GFW_ZIP = RAW_DIR / "gfw_paolo2024" / "analysis" / "industrial_vessels_v20240102.csv.zip"
GFW_SCS = PROCESSED_DIR / "gfw_sar_detections_scs.parquet"
GFW_COLS = ["scene_id", "timestamp", "lat", "lon", "mmsi", "matched_category", "length_m"]
VT_HISTORY_URL = "https://vtracking.rdms.refinitiv.com/api/v1/Shipping/History"
HISTORY_FIELDS = L.LOCATION_FIELDS + [
    "TR.AssetSpeed",
    "TR.AssetCourse",
    "TR.AssetHeading",
    "TR.AssetLocationStatus",
]
MATCH_GAP_S = 30 * 60  # max gap to each neighbour for interpolation / "close in time"


def jsonable(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [jsonable(v) for v in obj]
    if isinstance(obj, float) and obj != obj:  # NaN
        return None
    return obj


def quantiles(values: Sequence[float], qs: Sequence[float] = (0, 0.25, 0.5, 0.75, 0.9, 1)) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {}
    s = pd.Series(vals, dtype=float)
    return {f"q{int(q * 100)}": round(float(s.quantile(q)), 3) for q in qs}


# --- LSEG calls with pacing, error classification and a request log -----------------------------
class Probe:
    def __init__(self, key: str, min_interval_s: float = 0.3) -> None:
        self.key = key
        self.min_interval_s = min_interval_s
        self.log: list[dict[str, Any]] = []
        self._last = 0.0

    def clean(self, text: Any) -> str:
        return str(text).replace(self.key, "***")

    def _call(self, kind: str, label: str, fn: Callable[[], Any], n: int = 0) -> tuple[Any, Any]:
        for attempt in (1, 2):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            t0 = time.monotonic()
            self._last = t0
            entry = {"kind": kind, "label": label, "n_instruments": n, "attempt": attempt}
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = fn()
                entry.update(status="ok", seconds=round(time.monotonic() - t0, 2))
                self.log.append(entry)
                return res, None
            except Exception as exc:  # noqa: BLE001 - classify every backend failure
                code = getattr(exc, "code", None)
                msg = self.clean(exc)[:400]
                cls = L.classify_error(msg, code if isinstance(code, int) else None)
                entry.update(status="error", error_class=cls, code=code, message=msg)
                entry["seconds"] = round(time.monotonic() - t0, 2)
                self.log.append(entry)
                if cls == "rate_limited" and attempt == 1:
                    time.sleep(5)  # one polite retry only
                    continue
                return None, {"class": cls, "code": code, "message": msg}
        return None, {"class": "rate_limited", "code": 429, "message": "retry exhausted"}

    def adc(
        self, label: str, rics: Sequence[str], fields: list[str], params: dict | None = None
    ) -> tuple[tuple[list[str], list[list[Any]], list[dict]] | None, dict | None]:
        from lseg.data.content import fundamental_and_reference as fr

        res, err = self._call(
            "get_data",
            label,
            lambda: fr.Definition(universe=list(rics), fields=fields, parameters=params).get_data(),
            len(rics),
        )
        return (L.parse_adc(res.data.raw), None) if res is not None else (None, err)

    def search(self, label: str, **kw: Any) -> tuple[dict | None, dict | None]:
        from lseg.data.content import search

        res, err = self._call(
            "search",
            label,
            lambda: search.Definition(view=search.Views.VESSEL_PHYSICAL_ASSETS, **kw).get_data(),
        )
        return (res.data.raw, None) if res is not None else (None, err)


def cell_error_summary(errors: list[dict], headers: list[str]) -> list[dict]:
    c: Counter = Counter()
    for e in errors:
        col = e.get("col")
        field = headers[col] if isinstance(col, int) and col < len(headers) else None
        c[(e.get("code"), e.get("message"), field)] += 1
    return [
        {
            "code": k[0],
            "message": k[1],
            "field": k[2],
            "class": L.classify_error(str(k[1]), k[0]),
            "count": v,
        }
        for k, v in c.items()
    ]


def navigators(raw: dict) -> dict[str, list[tuple[str, int]]]:
    return {
        name: [(b.get("Label"), b.get("Count")) for b in nav.get("Buckets", [])]
        for name, nav in (raw.get("Navigators") or {}).items()
    }


# --- GFW scene detections (identifier source) -----------------------------------------------
def gfw_scene(scene_id: str) -> pd.DataFrame:
    cache = PROCESSED_DIR / "gfw_scenes" / f"{scene_id}.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    df = pd.DataFrame(columns=GFW_COLS)
    if GFW_SCS.exists():
        df = pd.read_parquet(GFW_SCS, columns=GFW_COLS)
        df = df[df.scene_id == scene_id]
    if df.empty and GFW_ZIP.exists():
        print(f"  scanning GFW detections zip for {scene_id} (~30 s) ...")
        parts = []
        with zipfile.ZipFile(GFW_ZIP) as zf:
            member = next(m for m in zf.namelist() if m.endswith(".csv"))
            with zf.open(member) as fh:
                for chunk in pd.read_csv(fh, chunksize=2_000_000, usecols=GFW_COLS):
                    parts.append(chunk[chunk.scene_id == scene_id])
        df = pd.concat(parts, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df.timestamp, utc=True, format="mixed")
    if not df.empty:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache, index=False)
    return df


def scene_time(scene_id: str, gfw: pd.DataFrame) -> datetime:
    if not gfw.empty:
        return pd.Timestamp(gfw.timestamp.iloc[0]).to_pydatetime().astimezone(UTC)
    m = re.search(r"_(\d{8}T\d{6})_(\d{8}T\d{6})_", scene_id)
    if not m:
        raise SystemExit(f"cannot parse acquisition time from {scene_id}")
    a, b = (datetime.strptime(x, "%Y%m%dT%H%M%S").replace(tzinfo=UTC) for x in m.groups())
    return a + (b - a) / 2


# --- Sections ---------------------------------------------------------------------------------
def preflight() -> dict[str, Any]:
    return {
        "env_vars_present": describe_env(["EIKON_APP_KEY", "VESSEL_TRACKING_API_KEY"]),
        "proxy": L.discover_proxy(),
    }


def open_desktop_session(key: str) -> dict[str, Any]:
    import lseg.data as ld

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            s = ld.open_session(app_key=key)
        state = getattr(s.open_state, "name", str(s.open_state))
        return {
            "ok": state == "Opened",
            "session_class": type(s).__name__,
            "session_name": getattr(s, "name", None),
            "open_state": state,
            "lseg_data_version": ld.__version__,
        }
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).replace(key, "***")[:400]
        return {"ok": False, "error_class": L.classify_error(msg), "message": msg}


def global_universe(p: Probe) -> dict[str, Any]:
    raw, err = p.search(
        "universe: all vessels",
        top=0,
        navigators="RCSAssetTypeLeaf(buckets:15),VesselStatus(buckets:6),AISStatus(buckets:8)",
    )
    if err:
        return {"error": err}
    assert raw is not None
    return {"total_vessels": raw.get("Total"), "navigators": navigators(raw)}


def coverage_region(p: Probe, name: str, bbox: L.BBox, now: datetime) -> dict[str, Any]:
    base = L.bbox_filter(bbox)
    out: dict[str, Any] = {"bbox": bbox}
    raw, err = p.search(
        f"coverage {name}: latest position in bbox",
        filter=base,
        top=0,
        navigators="RCSAssetTypeLeaf(buckets:12),RCSFlagLeaf(buckets:12),AISStatus(buckets:8)",
    )
    if err:
        return {"bbox": bbox, "error": err}
    assert raw is not None
    out["total_latest_in_bbox"] = raw.get("Total")
    out["navigators"] = navigators(raw)
    variants = {
        "fresh_1h": f" and LocationTimestamp ge {L.search_datetime(now - timedelta(hours=1))}",
        "fresh_24h": f" and LocationTimestamp ge {L.search_datetime(now - timedelta(hours=24))}",
        "type_fishing_vessel": " and RCSAssetTypeLeaf eq 'Fishing Vessel'",
        "ais_status_engaged_in_fishing": " and AISStatus eq 'Engaged In Fishing'",
        "type_fishing_vessel_fresh_24h": " and RCSAssetTypeLeaf eq 'Fishing Vessel' and "
        f"LocationTimestamp ge {L.search_datetime(now - timedelta(hours=24))}",
    }
    for key, extra in variants.items():
        r, e = p.search(f"coverage {name}: {key}", filter=base + extra, top=0)
        out[key] = e if e else (r or {}).get("Total")
    r, e = p.search(
        f"coverage {name}: fishing vessels by flag",
        filter=base + " and RCSAssetTypeLeaf eq 'Fishing Vessel'",
        top=0,
        navigators="RCSFlagLeaf(buckets:10)",
    )
    out["fishing_vessel_flags"] = e if e else navigators(r or {}).get("RCSFlagLeaf")
    return out


def area_snapshot(p: Probe, bbox: L.BBox, now: datetime, out_dir: Path) -> dict[str, Any]:
    raw, err = p.search(
        "area snapshot: latest positions in bbox",
        filter=L.bbox_filter(bbox),
        select=L.SEARCH_SELECT,
        top=1000,
        order_by="LocationTimestamp desc",
        navigators="RCSAssetTypeLeaf(buckets:15),Source,DataProviderName",
    )
    if err:
        return {"error": err}
    assert raw is not None
    hits = raw.get("Hits") or []
    df = pd.DataFrame(hits)
    if not df.empty:
        df.to_csv(out_dir / "area_snapshot_latest.csv", index=False)
    ts = [L.parse_utc(h.get("LocationTimestamp")) for h in hits]
    ages = [(now - t).total_seconds() / 3600 for t in ts if t]
    res: dict[str, Any] = {
        "bbox": bbox,
        "total_latest_in_bbox": raw.get("Total"),
        "rows_returned": len(hits),
        "rows_note": "sorted by LocationTimestamp desc; total may exceed returned rows",
        "age_hours_of_returned_rows": quantiles(ages),
        "navigators": navigators(raw),
        "imo_missing_in_returned": int(sum(1 for h in hits if not h.get("IMO"))),
        "mmsi_missing_in_returned": int(sum(1 for h in hits if not h.get("MMSI"))),
        "coords_valid_in_returned": int(
            sum(L.valid_coord(h.get("Latitude"), h.get("Longitude")) for h in hits)
        ),
    }
    for label, h in (("fresh_1h", 1), ("fresh_24h", 24), ("fresh_7d", 168)):
        r, e = p.search(
            f"area snapshot: {label}",
            filter=L.bbox_filter(bbox)
            + f" and LocationTimestamp ge {L.search_datetime(now - timedelta(hours=h))}",
            top=0,
        )
        res[label] = e if e else (r or {}).get("Total")
    res["fresh_rics"] = [
        h["RIC"]
        for h in hits
        if h.get("IMO") and (t := L.parse_utc(h.get("LocationTimestamp"))) and now - t < L.hours(6)
    ][:3]
    return res


def field_probe(p: Probe, rics: list[str], out_dir: Path) -> dict[str, Any]:
    res: dict[str, Any] = {"reference_rics": rics, "groups": {}}
    for name, fields in (
        ("static", L.STATIC_FIELDS),
        ("location_dynamic_latest", L.LOCATION_FIELDS + L.DYNAMIC_FIELDS),
    ):
        data, err = p.adc(f"fields: {name}", rics, fields)
        if err:
            res["groups"][name] = {"error": err}
            continue
        assert data is not None
        headers, rows, errors = data
        returned = [h.upper() for h in headers[1:]]
        fill = {
            f: sum(1 for r in rows if r[i + 1] not in (None, "")) for i, f in enumerate(headers[1:])
        }
        res["groups"][name] = {
            "requested": fields,
            "returned_headers": headers[1:],
            "silently_dropped": [f for f in fields if f.upper() not in returned],
            "non_empty_count_per_field": fill,
            "n_rows": len(rows),
            "cell_errors": cell_error_summary(errors, headers),
            "sample_rows": rows[:3],
        }
    res["unrecognised_field_tests"] = {}
    for f in L.UNRECOGNISED_FIELDS:
        data, err = p.adc(f"fields: candidate {f}", rics[:1], L.LOCATION_FIELDS + [f])
        res["unrecognised_field_tests"][f] = err["class"] if err else "accepted"
    data, err = p.adc("invalid identifier", ["C}XX0000000000"], L.LOCATION_FIELDS)
    if err:
        res["invalid_identifier_test"] = err
    else:
        assert data is not None
        res["invalid_identifier_test"] = {
            "rows": data[1],
            "cell_errors": cell_error_summary(data[2], data[0]),
        }
    # Date-parameter resolution: quoted intraday bounds vs whole day, same vessel and day.
    day = (L.utc_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    counts = {}
    for label, prm in (
        ("whole_day", {"SDate": day, "EDate": day}),
        ("intraday_03_06", {"SDate": f"'{day}T03:00:00'", "EDate": f"'{day}T06:00:00'"}),
        ("unquoted_iso_time", {"SDate": f"{day}T03:00:00", "EDate": f"{day}T06:00:00"}),
    ):
        data, err = p.adc(f"date resolution: {label}", rics[:1], L.LOCATION_FIELDS, prm)
        if err:
            counts[label] = {"error_class": err["class"], "message": err["message"][:160]}
        else:
            assert data is not None
            pos = L.positions_from_adc(data[0], data[1])
            counts[label] = {
                "n": len(pos),
                "min": min((x["time_utc"] for x in pos), default=None),
                "max": max((x["time_utc"] for x in pos), default=None),
            }
    res["date_parameter_resolution"] = {"day": day, **counts}
    return res


def resolve_identifiers(
    p: Probe, mmsis: list[str], imos: list[str], label: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    hits: list[dict] = []
    errors = []
    for prop, values in (("MMSI", mmsis), ("IMO", imos)):
        for chunk in L.chunks(sorted(set(values)), 40):
            raw, err = p.search(
                f"resolve {label}: {prop} x{len(chunk)}",
                filter=L.in_filter(prop, chunk),
                select=L.SEARCH_SELECT,
                top=200,
            )
            if err:
                errors.append(err)
                continue
            for h in (raw or {}).get("Hits") or []:
                h["_matched_on"] = prop
                hits.append(h)
    df = pd.DataFrame(hits)
    found_mmsi = set(df.MMSI.dropna().astype(str)) if not df.empty and "MMSI" in df else set()
    found_imo = set(df.IMO.dropna().astype(str)) if not df.empty and "IMO" in df else set()
    multi = int(df.groupby("MMSI").RIC.nunique().gt(1).sum()) if not df.empty else 0
    return df, {
        "n_mmsi_queried": len(set(mmsis)),
        "n_mmsi_resolved": len(set(mmsis) & found_mmsi),
        "n_imo_queried": len(set(imos)),
        "n_imo_resolved": len(set(imos) & found_imo),
        "n_rics": int(df.RIC.nunique()) if not df.empty else 0,
        "mmsi_with_multiple_rics": multi,
        "errors": errors,
    }


def scene_history(
    p: Probe,
    scene_id: str,
    gfw: pd.DataFrame,
    resolved: pd.DataFrame,
    window_h: float,
    out_dir: Path,
) -> dict[str, Any]:
    t0 = scene_time(scene_id, gfw)
    start, end = t0 - L.hours(window_h), t0 + L.hours(window_h)
    day_start = start.replace(hour=0, minute=0, second=0)
    day_end = end.replace(hour=23, minute=59, second=59)
    rics = sorted(resolved.RIC.unique()) if not resolved.empty else []
    res: dict[str, Any] = {
        "acquisition_time_utc": t0,
        "window_utc": [start, end],
        "requested_day_interval_utc": [day_start, day_end],
        "n_rics_requested": len(rics),
    }
    if not rics:
        return res
    positions, errors, cell_errs = [], [], []
    for chunk in L.chunks(rics, 50):
        data, err = p.adc(
            f"history {scene_id[:25]} x{len(chunk)}",
            chunk,
            HISTORY_FIELDS,
            L.day_params(start, end),
        )
        if err:
            errors.append(err)
            continue
        assert data is not None
        positions += L.positions_from_adc(data[0], data[1])
        cell_errs += cell_error_summary(data[2], data[0])
    res["request_errors"] = errors
    res["cell_errors"] = cell_errs
    res["validation_vs_requested_days"] = L.validate_positions(positions, day_start, day_end)
    in_win = [x for x in positions if start <= x["time_utc"] <= end]
    res["validation_vs_window"] = L.validate_positions(in_win, start, end)
    res["field_fill_in_window"] = {
        k: sum(1 for x in in_win if x[k] is not None)
        for k in ("speed_kn", "course_deg", "heading_deg", "nav_status")
    }
    if positions:
        pd.DataFrame(positions).to_csv(out_dir / f"history_{scene_id[:32]}.csv", index=False)

    lo, la, hi, ha = (
        gfw.lon.min() - 0.1,
        gfw.lat.min() - 0.1,
        gfw.lon.max() + 0.1,
        gfw.lat.max() + 0.1,
    )
    scene_bbox = (float(lo), float(la), float(hi), float(ha))
    gfw_by_mmsi = {m: r for r in gfw.itertuples() if (m := L.normalise_mmsi(r.mmsi))}
    rows = []
    for ric in rics:
        track = [x for x in positions if x["ric"] == ric]
        win = [x for x in track if start <= x["time_utc"] <= end]
        near, gap = L.nearest_position(win, t0)
        interp = L.interpolate_position(win, t0, MATCH_GAP_S)
        meta = resolved[resolved.RIC == ric].iloc[0]
        det = gfw_by_mmsi.get(str(meta.get("MMSI")))
        row = {
            "ric": ric,
            "mmsi": meta.get("MMSI"),
            "imo": meta.get("IMO"),
            "lseg_type": meta.get("RCSAssetTypeLeaf"),
            "flag": meta.get("RCSFlagLeaf"),
            "gfw_category": getattr(det, "matched_category", None),
            "n_obs_day": len(track),
            "n_obs_window": len(win),
            "nearest_gap_min": None if gap is None else round(gap / 60, 2),
            "median_interval_min": (
                None if (mi := L.median_interval_s(win)) is None else round(mi / 60, 2)
            ),
            "n_obs_window_in_scene_bbox": sum(
                L.in_bbox(x["lat"], x["lon"], scene_bbox) for x in win
            ),
            "interpolated": interp is not None,
            "currently_in_scene_bbox": L.in_bbox(
                meta.get("Latitude"), meta.get("Longitude"), scene_bbox
            ),
        }
        if det is not None and near is not None and L.valid_coord(near["lat"], near["lon"]):
            row["dist_nearest_to_gfw_m"] = round(
                L.haversine_m(near["lat"], near["lon"], det.lat, det.lon)
            )
        if det is not None and interp is not None:
            row["dist_interp_to_gfw_m"] = round(
                L.haversine_m(interp["lat"], interp["lon"], det.lat, det.lon)
            )
        rows.append(row)
    vdf = pd.DataFrame(rows)
    vdf.to_csv(out_dir / f"history_match_{scene_id[:32]}.csv", index=False)
    gaps = vdf.nearest_gap_min.dropna()
    close = vdf[vdf.nearest_gap_min.le(MATCH_GAP_S / 60) & vdf.n_obs_window_in_scene_bbox.gt(0)]
    res.update(
        scene_bbox=scene_bbox,
        n_rics_with_any_obs_in_requested_days=int((vdf.n_obs_day > 0).sum()),
        n_rics_with_obs_in_window=int((vdf.n_obs_window > 0).sum()),
        n_rics_with_obs_in_window_in_scene_bbox=int((vdf.n_obs_window_in_scene_bbox > 0).sum()),
        n_rics_with_obs_in_window_only_outside_scene_bbox=int(
            ((vdf.n_obs_window > 0) & (vdf.n_obs_window_in_scene_bbox == 0)).sum()
        ),
        obs_per_vessel_day=quantiles(list(vdf.n_obs_day[vdf.n_obs_day > 0])),
        nearest_gap_minutes=quantiles(list(gaps)),
        n_gap_le={f"{m}min": int(gaps.le(m).sum()) for m in (5, 10, 30, 60, 180)},
        median_report_interval_minutes=quantiles(list(vdf.median_interval_min.dropna())),
        n_interpolated_within_30min_each_side=int(vdf.interpolated.sum()),
        dist_nearest_to_gfw_m_when_gap_le_30min_in_bbox=quantiles(
            list(close.get("dist_nearest_to_gfw_m", pd.Series(dtype=float)).dropna())
        ),
        dist_interp_to_gfw_m=quantiles(
            list(vdf.get("dist_interp_to_gfw_m", pd.Series(dtype=float)).dropna())
        ),
        n_resolved_currently_in_scene_bbox=int(vdf.currently_in_scene_bbox.sum()),
        by_gfw_category=vdf.groupby(vdf.gfw_category.fillna("none"))
        .agg(n=("ric", "size"), with_obs_window=("n_obs_window", lambda s: int((s > 0).sum())))
        .to_dict(orient="index"),
        lseg_types=vdf.lseg_type.value_counts().head(10).to_dict(),
    )
    return res


def history_depth(p: Probe, rics: list[str], years: Sequence[int]) -> dict[str, Any]:
    out: dict[str, Any] = {"rics": rics, "per_probe_week": {}}
    for y in years:
        s = datetime(y, 6, 15, tzinfo=UTC)
        e = s + timedelta(days=6)
        data, err = p.adc(f"history depth {y}", rics, L.LOCATION_FIELDS, L.day_params(s, e))
        if err:
            out["per_probe_week"][str(y)] = {"error_class": err["class"]}
            continue
        assert data is not None
        pos = L.positions_from_adc(data[0], data[1])
        out["per_probe_week"][str(y)] = {
            "week": [s.date().isoformat(), e.date().isoformat()],
            "n_positions": len(pos),
            "n_vessels_with_data": len({x["ric"] for x in pos}),
            "n_outside_week": sum(1 for x in pos if not s <= x["time_utc"] <= e + L.hours(24)),
        }
    with_data = [int(y) for y, v in out["per_probe_week"].items() if v.get("n_positions")]
    out["earliest_probe_year_with_data"] = min(with_data) if with_data else None
    return out


def recent_reconstruction(
    p: Probe, bbox: L.BBox, now: datetime, lag_h: float, max_candidates: int, out_dir: Path
) -> dict[str, Any]:
    """Who was in ``bbox`` at T = now - lag? Candidates: vessels whose *latest* indexed position
    lies within bbox buffered by v_max * (now - T + 1 h) and that reported since T - 1 h."""
    v_max_kn, tol = 25.0, timedelta(minutes=30)
    t = now - L.hours(lag_h)
    buffer_km = v_max_kn * L.KNOT_KMH * (lag_h + 1)
    cand_box = L.buffer_bbox(bbox, buffer_km)
    flt = L.bbox_filter(cand_box) + f" and LocationTimestamp ge {L.search_datetime(t - L.hours(1))}"
    raw, err = p.search(
        "recent: candidates",
        filter=flt,
        select="RIC,Latitude,Longitude,LocationTimestamp",
        top=10000,
    )
    res: dict[str, Any] = {
        "reference_time_utc": t,
        "tolerance_min": tol.total_seconds() / 60,
        "assumed_max_speed_kn": v_max_kn,
        "candidate_bbox": cand_box,
        "target_bbox": bbox,
    }
    if err:
        res["error"] = err
        return res
    assert raw is not None
    cands = [h["RIC"] for h in raw.get("Hits") or [] if h.get("RIC")]
    res["candidates_total"] = raw.get("Total")
    res["candidates_used"] = min(len(cands), max_candidates)
    res["candidates_truncated"] = len(cands) > max_candidates
    cands = cands[:max_candidates]
    positions = []
    for chunk in L.chunks(cands, 100):
        data, e = p.adc(
            f"recent: history x{len(chunk)}", chunk, HISTORY_FIELDS, L.day_params(t - tol, t + tol)
        )
        if e:
            res.setdefault("request_errors", []).append(e)
            continue
        assert data is not None
        positions += L.positions_from_adc(data[0], data[1])
    near = [x for x in positions if abs(x["time_utc"] - t) <= tol]
    per: dict[str, dict] = {}
    for x in near:
        cur = per.get(x["ric"])
        if cur is None or abs(x["time_utc"] - t) < abs(cur["time_utc"] - t):
            per[x["ric"]] = x
    inside = [x for x in per.values() if L.in_bbox(x["lat"], x["lon"], bbox)]
    pd.DataFrame(inside).to_csv(out_dir / "recent_reconstructed_layer.csv", index=False)
    snap, e2 = p.search(
        "recent: current snapshot fresh 1h",
        filter=L.bbox_filter(bbox)
        + f" and LocationTimestamp ge {L.search_datetime(now - L.hours(1))}",
        select="RIC",
        top=5000,
    )
    snap_rics = {h["RIC"] for h in (snap or {}).get("Hits") or []}
    in_rics = {x["ric"] for x in inside}
    by_ric: dict[str, list[dict]] = {}
    for x in positions:
        by_ric.setdefault(x["ric"], []).append(x)
    intervals = [m for tr in by_ric.values() if (m := L.median_interval_s(tr)) is not None]
    res.update(
        n_positions_returned=len(positions),
        median_report_interval_minutes=quantiles([m / 60 for m in intervals]),
        n_vessels_with_report_within_tol=len(per),
        n_vessels_in_target_bbox_at_T=len(inside),
        gap_minutes_of_used_reports=quantiles(
            [abs((x["time_utc"] - t).total_seconds()) / 60 for x in inside]
        ),
        n_current_fresh_snapshot_in_bbox=len(snap_rics) if not e2 else e2,
        overlap_T_vs_now=len(in_rics & snap_rics),
        in_bbox_at_T_but_not_now=len(in_rics - snap_rics),
    )
    return res


def ssl_context() -> ssl.SSLContext:
    """CA bundle from certifi (the bundled Python store lacks the Sectigo R46 root used by
    vtracking.rdms.refinitiv.com, giving CERTIFICATE_VERIFY_FAILED)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def vessel_tracking_api(imo: str | None) -> dict[str, Any]:
    key = get_secret("VESSEL_TRACKING_API_KEY")
    out: dict[str, Any] = {"endpoint": VT_HISTORY_URL, "key_present": bool(key)}
    headers = {"Accept": "application/json", "User-Agent": "shadow-ship-spotter-probe/0.1"}
    if not key:
        # Reachability only: no credential of any kind is sent.
        req = urllib.request.Request(VT_HISTORY_URL + "?IMO=9617698", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as r:  # noqa: S310
                out["unauthenticated_http_status"] = r.status
        except urllib.error.HTTPError as exc:
            out["unauthenticated_http_status"] = exc.code
        except OSError as exc:
            out["unauthenticated_error"] = f"{type(exc).__name__}: {exc}"
        out["tested_with_key"] = False
        return out
    auth = key if key.lower().startswith("apikey") else f"apikey-v1 {key}"
    headers["Authorization"] = auth
    now = L.utc_now()
    tests = {
        "default_latest_24h": {"IMO": imo or "9617698"},
        "from_to_3_days_ago": {
            "IMO": imo or "9617698",
            "FromDateTime": L.search_datetime(now - timedelta(days=3, hours=6)),
            "ToDateTime": L.search_datetime(now - timedelta(days=3)),
        },
        "from_to_alt_names_3_days_ago": {  # sample notebook uses FromDate/ToDate
            "IMO": imo or "9617698",
            "FromDate": L.search_datetime(now - timedelta(days=3, hours=6)),
            "ToDate": L.search_datetime(now - timedelta(days=3)),
        },
    }
    for name, params in tests.items():
        url = VT_HISTORY_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:  # noqa: S310
                body = json.loads(r.read().decode())
            recs = [dict(zip(x["fieldNames"], x["fieldValues"], strict=False)) for x in body]
            times = sorted(t for x in recs if (t := L.parse_utc(x.get("TimestampPosition"))))
            out[name] = {"http": 200, "n": len(recs), "min": times[:1], "max": times[-1:]}
        except urllib.error.HTTPError as exc:
            out[name] = {"http": exc.code, "class": L.classify_error(str(exc), exc.code)}
        except (OSError, ValueError, KeyError) as exc:
            out[name] = {"error": f"{type(exc).__name__}"}
    out["tested_with_key"] = True
    return out


# --- Main -------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scene", action="append", help="ESA product name (repeatable)")
    ap.add_argument("--window-hours", type=float, default=3.0)
    ap.add_argument("--max-vessels", type=int, default=120, help="per scene, from GFW matches")
    ap.add_argument("--mmsi", nargs="*", default=[])
    ap.add_argument("--imo", nargs="*", default=[])
    ap.add_argument("--ric", nargs="*", default=[], help="reference RICs for the field probe")
    ap.add_argument("--bbox", nargs=4, type=float, default=DEFAULT_BBOX, metavar="LON/LAT")
    ap.add_argument("--recent-lag-hours", type=float, default=3.0)
    ap.add_argument("--max-candidates", type=int, default=1500)
    ap.add_argument("--depth-years", nargs="*", type=int, default=list(range(2010, 2020, 2)))
    ap.add_argument("--out", type=Path, default=RAW_DIR / "lseg")
    a = ap.parse_args()

    now = L.utc_now()
    out_dir = a.out / f"probe_{now.strftime('%Y%m%dT%H%M%SZ')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    A: dict[str, Any] = {"run_utc": now, "args": {k: str(v) for k, v in vars(a).items()}}

    def finish(code: int) -> int:
        path = out_dir / "assessment.json"
        path.write_text(json.dumps(jsonable(A), indent=2, default=str))
        shutil.copyfile(path, a.out / "assessment_latest.json")
        print(f"\nassessment -> {path}")
        return code

    print("1. preflight")
    A["preflight"] = pre = preflight()
    print(f"   env: {pre['env_vars_present']} | proxy: {pre['proxy']}")
    key = get_secret("EIKON_APP_KEY")
    if not key:
        A["blocker"] = {"class": "credential_missing", "action": "add EIKON_APP_KEY to .env"}
        return finish(2)
    if not pre["proxy"].get("reachable") or not pre["proxy"].get("ready"):
        A["blocker"] = {
            "class": "desktop_unavailable",
            "action": "start LSEG Workspace on this machine and log in, then re-run",
        }
        return finish(3)
    port = pre["proxy"]["port"]
    A["throttling_before"] = L.throttling_limits(port)
    A["session"] = sess = open_desktop_session(key)
    print(f"   session: {sess}")
    if not sess.get("ok"):
        A["blocker"] = {
            "class": "session_open_failed",
            "action": "check the app key (Workspace > APPKEY) and the Workspace login",
        }
        return finish(4)
    p = Probe(key)
    try:
        print("2. universe, coverage and area snapshot (Search API)")
        A["universe"] = global_universe(p)
        A["coverage"] = {n: coverage_region(p, n, b, now) for n, b in COVERAGE_REGIONS.items()}
        A["area_snapshot"] = snap = area_snapshot(p, tuple(a.bbox), now, out_dir)
        refs = a.ric or snap.get("fresh_rics") or ["C}BL7309511428"]
        print(f"3. field probe on {refs}")
        A["fields"] = field_probe(p, refs, out_dir)

        print("4. identifier resolution + historical positions per scene")
        A["scenes"] = {}
        all_resolved = []
        for scene_id in a.scene or SCENES:
            gfw = gfw_scene(scene_id)
            matched = gfw[gfw.mmsi.notna()] if not gfw.empty else gfw
            mmsis = [m for m in (L.normalise_mmsi(x) for x in matched.mmsi) if m][: a.max_vessels]
            mmsis += list(a.mmsi)
            resolved, rstats = resolve_identifiers(p, mmsis, list(a.imo), scene_id[:25])
            cat_by_mmsi = {
                L.normalise_mmsi(r.mmsi): r.matched_category for r in matched.itertuples()
            }
            res_m = set(resolved.MMSI.dropna().astype(str)) if not resolved.empty else set()
            rstats["resolution_by_gfw_category"] = {
                c: {
                    "queried": sum(1 for m in mmsis if cat_by_mmsi.get(m) == c),
                    "resolved": sum(1 for m in mmsis if cat_by_mmsi.get(m) == c and m in res_m),
                }
                for c in sorted({str(v) for v in cat_by_mmsi.values()})
            }
            if not resolved.empty:
                resolved.to_csv(out_dir / f"resolved_{scene_id[:32]}.csv", index=False)
                all_resolved.append(resolved)
            A["scenes"][scene_id] = {
                "gfw_detections": len(gfw),
                "gfw_matched_with_mmsi": len(matched),
                "gfw_category_counts": (
                    gfw.matched_category.value_counts().to_dict() if not gfw.empty else {}
                ),
                "resolution": rstats,
                "history": scene_history(p, scene_id, gfw, resolved, a.window_hours, out_dir),
            }
            h = A["scenes"][scene_id]["history"]
            print(
                f"   {scene_id[:33]}: resolved {rstats['n_mmsi_resolved']}/"
                f"{rstats['n_mmsi_queried']} MMSI; obs in ±{a.window_hours} h: "
                f"{h.get('n_rics_with_obs_in_window')}; gap≤30min: {h.get('n_gap_le')}"
            )

        print("5. history depth")
        hist_rics: list[str] = []
        if all_resolved:
            allr = pd.concat(all_resolved)
            hist_rics = list(allr[allr.IMO.notna()].RIC.unique()[:5])
        A["history_depth"] = history_depth(p, hist_rics or refs, a.depth_years)

        print("6. recent reconstruction of the AIS layer for the bbox")
        A["recent_reconstruction"] = recent_reconstruction(
            p, tuple(a.bbox), now, a.recent_lag_hours, a.max_candidates, out_dir
        )
    finally:
        import lseg.data as ld

        ld.close_session()
    print("7. Vessel Tracking API (separate product)")
    first_imo = None
    if A.get("scenes"):
        for f in out_dir.glob("resolved_*.csv"):
            imos = pd.read_csv(f).IMO.dropna()
            if len(imos):
                first_imo = str(int(imos.iloc[0]))
                break
    A["vessel_tracking_api"] = vessel_tracking_api(first_imo)
    A["throttling_after"] = L.throttling_limits(port)
    A["request_log_summary"] = {
        "n_requests": len(p.log),
        "by_status": Counter(e["status"] for e in p.log),
        "error_classes": Counter(e.get("error_class") for e in p.log if e["status"] == "error"),
    }
    pd.DataFrame(p.log).to_csv(out_dir / "request_log.csv", index=False)
    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
