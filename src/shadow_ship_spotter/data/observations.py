"""Licensed historical sample reports. Query completion and reception coverage are independent."""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from .catalog import read_item
from .compatibility import Product, require_substitute
from .contracts import (
    Attempt,
    Bounds,
    Interval,
    Model,
    Origin,
    Policy,
    SourceError,
    State,
    Utc,
    data_error,
    sensing_interval,
)


class PositionRequest(Model):
    area: Bounds
    time: Interval


class Fix(Model):
    namespace: Literal["lseg:ric", "ais:mmsi"]
    identifier: str = Field(min_length=1)
    observed_at: Utc
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    speed_kn: float | None = Field(default=None, ge=0)
    course_deg: float | None = Field(default=None, ge=0, lt=360)
    heading_deg: float | None = Field(default=None, ge=0, lt=360)
    nav_status: str | None = None
    kind: Literal["reported"] = "reported"

    @model_validator(mode="after")
    def validate_id(self):
        if self.namespace == "ais:mmsi" and (
            len(self.identifier) != 9
            or not self.identifier.isascii()
            or not self.identifier.isdigit()
        ):
            raise ValueError("expected a nine-digit MMSI")
        if self.namespace == "lseg:ric" and not self.identifier.startswith("C}"):
            raise ValueError("expected a vessel RIC")
        return self


class Observation(Model):
    fix: Fix
    origins: tuple[Origin, ...]
    conflict: bool


def reconcile(rows: Iterable[tuple[Fix, Origin]]) -> tuple[Observation, ...]:
    variants: dict[tuple[str, str, datetime], dict[Fix, list[Origin]]] = defaultdict(dict)
    for fix, source in rows:
        require_substitute(Product.REPORTED, Product(source.product))
        group = variants[fix.namespace, fix.identifier, fix.observed_at]
        origins = group.setdefault(fix, [])
        if source not in origins:
            origins.append(source)
    return tuple(
        Observation(fix=fix, origins=tuple(origins), conflict=len(variants[key]) > 1)
        for key in sorted(variants)
        for fix, origins in variants[key].items()
    )


class ExportCoverage(Model):
    source_run: str
    selection_scene: str
    requested_days: Interval
    identifiers_requested: int = Field(ge=0)
    exported_rows: int = Field(ge=0)
    selected_rows: int = Field(ge=0)
    first_selected_report: Utc | None = None
    last_selected_report: Utc | None = None


class Positions(Model):
    request: PositionRequest
    state: State
    population_coverage: Literal["unknown"] = "unknown"
    observations: tuple[Observation, ...]
    attempts: tuple[Attempt, ...]
    exports: tuple[ExportCoverage, ...]
    limitation: str = (
        "Reports for selected provider identifiers. Area reception and fleet "
        "completeness are unknown. Display rights require separate clearance."
    )


def _number(row: dict, key: str, sentinel: str | None = None) -> float | None:
    value = row[key]
    if not value or (sentinel and float(value) == float(sentinel)):
        return None
    return float(value)


def scene_export_path(
    folder: Path, kind: Literal["history", "resolved"], scene: str, scenes: Iterable[str]
) -> Path:
    """Earlier probes used a truncated name. Accept it only for an unambiguous receipt."""
    sensing_interval(scene)
    exact = folder / f"{kind}_{scene}.csv"
    if exact.is_file():
        return exact
    prefix = scene[:32]
    if sum(s.startswith(prefix) for s in scenes) != 1:
        raise SourceError(State.INCOMPATIBLE, "ambiguous legacy scene export name")
    return folder / f"{kind}_{prefix}.csv"


def _read_export(
    folder: Path,
    scene: str,
    history: dict,
    q: PositionRequest,
    run_time: datetime,
    scenes: Iterable[str],
) -> tuple[list[tuple[Fix, Origin]], State, ExportCoverage | None]:
    sensing_interval(scene)
    span = history["requested_day_interval_utc"]
    dates = Interval(
        start=TypeAdapter(Utc).validate_python(span[0]),
        end=TypeAdapter(Utc).validate_python(span[1]) + timedelta(seconds=1),
    )
    if not dates.intersects(q.time):
        return [], State.INCOMPATIBLE, None
    if history.get("n_rics_requested", 0) == 0:
        raise SourceError(State.UNKNOWN, "probe had no resolved identifiers")
    errors = [*history["request_errors"], *history["cell_errors"]]
    expected = history["validation_vs_requested_days"]["n_positions"]
    if errors and not expected:
        denied = any(e.get("class") == "entitlement_denied" for e in errors)
        raise SourceError(State.ACCESS if denied else State.UNKNOWN, "source reported query errors")
    file = scene_export_path(folder, "history", scene, scenes)
    rows: list[tuple[Fix, Origin]] = []
    if expected or file.exists():
        with file.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required = {
                "ric",
                "time_utc",
                "lon",
                "lat",
                "position_kind",
                "speed_kn",
                "course_deg",
                "heading_deg",
                "nav_status",
            }
            if not required.issubset(reader.fieldnames or ()):
                raise ValueError("missing historical export columns")
            count = 0
            for count, row in enumerate(reader, 1):
                fix = Fix.model_validate(
                    dict(
                        namespace="lseg:ric",
                        identifier=row["ric"],
                        observed_at=row["time_utc"],
                        lon=row["lon"],
                        lat=row["lat"],
                        kind=row["position_kind"],
                        speed_kn=_number(row, "speed_kn"),
                        course_deg=_number(row, "course_deg", "360"),
                        heading_deg=_number(row, "heading_deg", "511"),
                        nav_status=row["nav_status"] or None,
                    )
                )
                if (fix.lat, fix.lon) == (0, 0):
                    raise ValueError("LSEG missing-location sentinel")
                if not dates.start <= fix.observed_at < dates.end:
                    raise ValueError("report outside recorded provider query")
                if q.time.start <= fix.observed_at < q.time.end and q.area.contains(
                    fix.lon, fix.lat
                ):
                    rows.append(
                        (
                            fix,
                            Origin(
                                source="lseg-workspace",
                                revision=folder.name,
                                asset=f"{folder.name}/{file.name}#row={count}",
                                product="provider-reported-position",
                                run_started_at=run_time,
                                transformations=("filtered historical export in UTC and WGS84",),
                            ),
                        )
                    )
            if count != expected:
                raise ValueError("export count differs from probe assessment")
    partial = errors or q.time.start < dates.start or q.time.end > dates.end
    coverage = ExportCoverage(
        source_run=folder.name,
        selection_scene=scene,
        requested_days=dates,
        identifiers_requested=history["n_rics_requested"],
        exported_rows=expected,
        selected_rows=len(rows),
        first_selected_report=min((fix.observed_at for fix, _ in rows), default=None),
        last_selected_report=max((fix.observed_at for fix, _ in rows), default=None),
    )
    return rows, State.PARTIAL if partial else State.COMPLETE if rows else State.EMPTY, coverage


def load_positions(data: Path, policy: Policy, request: PositionRequest) -> Positions:
    attempts: list[Attempt] = []
    exports: list[ExportCoverage] = []
    rows: list[tuple[Fix, Origin]] = []
    for run in policy.lseg_runs:
        folder = data / "raw/lseg" / run
        try:
            receipt = read_item(folder / "assessment.json")
            stamp = TypeAdapter(Utc).validate_python(receipt["run_utc"])
            if stamp.strftime("probe_%Y%m%dT%H%M%SZ") != run:
                raise ValueError("wrong probe receipt")
            if "blocker" in receipt:
                reason = receipt["blocker"]["class"]
                raise SourceError(
                    (
                        State.ACCESS
                        if reason in ("credential_missing", "entitlement_denied")
                        else State.UNAVAILABLE
                    ),
                    f"recorded probe blocker: {reason}",
                )
            scenes = receipt["scenes"]
            if not isinstance(scenes, dict):
                raise ValueError("invalid scene history receipts")
            for scene, detail in scenes.items():
                try:
                    found, state, coverage = _read_export(
                        folder, scene, detail["history"], request, stamp, scenes
                    )
                    if coverage:
                        exports.append(coverage)
                    rows.extend(found)
                    attempts.append(
                        Attempt(
                            source=run,
                            state=state,
                            applicable=state != State.INCOMPATIBLE,
                            reason=f"{scene}: "
                            f"{len(found)} selected reports; run started {stamp.isoformat()}",
                        )
                    )
                except (OSError, ValueError, KeyError, TypeError, IndexError, csv.Error) as exc:
                    err = data_error(exc, "historical position export")
                    attempts.append(Attempt(source=run, state=err.state, reason=str(err)))
                except SourceError as exc:
                    attempts.append(Attempt(source=run, state=exc.state, reason=str(exc)))
        except (OSError, KeyError, TypeError, ValueError) as exc:
            err = data_error(exc, "probe assessment")
            attempts.append(Attempt(source=run, state=err.state, reason=str(err)))
        except SourceError as exc:
            attempts.append(Attempt(source=run, state=exc.state, reason=str(exc)))
    states = {a.state for a in attempts if a.applicable}
    failed = states.intersection(
        {
            State.CORRUPT,
            State.ACCESS,
            State.UNKNOWN,
            State.PARTIAL,
            State.UNAVAILABLE,
            State.INCOMPATIBLE,
        }
    )
    if failed and (rows or State.EMPTY in states or State.PARTIAL in states):
        state = State.PARTIAL
    elif rows:
        state = State.COMPLETE
    elif State.EMPTY in states:
        state = State.EMPTY
    else:
        state = next(
            (
                s
                for s in (State.CORRUPT, State.ACCESS, State.INCOMPATIBLE, State.UNKNOWN)
                if s in states
            ),
            State.UNAVAILABLE,
        )
    return Positions(
        request=request,
        state=state,
        observations=reconcile(rows),
        attempts=tuple(attempts),
        exports=tuple(exports),
    )
