"""Retrospective scene-review boundary. Public summaries contain no licensed position rows."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Self

import numpy as np
from pydantic import Field, model_validator

from .catalog import Discovery, discover
from .contracts import (
    Bounds,
    Interval,
    Layer,
    Model,
    Policy,
    RasterProduct,
    RasterRequest,
    SceneID,
    SourceError,
    State,
)
from .geo import window_at
from .imagery import RasterResolver, RasterResult
from .observations import PositionRequest, load_positions
from .reference import load_reference


class StudyRequest(Model):
    day: date
    zone: Bounds | None = None
    viewport: Bounds | None = None
    scene: SceneID
    product: RasterProduct
    minutes: int = Field(default=30, gt=0)
    preview_pixels: int = Field(default=80, gt=0, le=4096)

    @model_validator(mode="after")
    def has_area(self) -> Self:
        if self.zone is None and self.viewport is None:
            raise ValueError("specify a zone or map viewport")
        return self

    @property
    def area(self) -> Bounds:
        b = self.zone or self.viewport
        assert b is not None
        return b


def raster_summary(result: RasterResult) -> dict:
    return dict(
        state=result.state,
        request=result.request.model_dump(mode="json"),
        missing={b: [w.model_dump() for w in wins] for b, wins in result.missing.items()},
        reads=[
            dict(
                band=p.band,
                window=p.window.model_dump(),
                dtype=str(p.pixels.dtype),
                valid_pixels=int(p.pixels.count()),
                crs=p.grid.crs,
                affine=p.grid.affine,
                control_points=len(p.grid.gcps),
                origin=p.origin.model_dump(mode="json"),
            )
            for p in result.pieces
        ],
        attempts=[a.model_dump() for a in result.attempts],
    )


def _select(data: Path, policy: Policy, q: StudyRequest) -> Discovery:
    day = Interval.day(q.day)
    local = discover(data, q.area, day)
    if (
        policy.online
        and q.product == "s1-grd-dn"
        and "pc-cog" in policy.raster_priority
        and not any(
            h.scene.id == q.scene and h.scene.origin.product == q.product for h in local.hits
        )
    ):
        return discover(data, q.area, day, online=True)
    return local


def prepare(data: Path, policy: Policy, q: StudyRequest) -> dict:
    discovery = _select(data, policy, q)
    named = [h for h in discovery.hits if h.scene.id == q.scene]
    hit = next((h for h in named if h.scene.origin.product == q.product), None)
    result: dict = dict(
        request=q.model_dump(mode="json"),
        effective_area=q.area.model_dump(),
        catalogue_scope=discovery.scope,
        discovery_attempts=[a.model_dump() for a in discovery.attempts],
        required_layers=policy.required_layers,
        model="not_run",
        matching="insufficient_ais_information",
    )
    if hit is None:
        state = (
            discovery.state
            if discovery.state not in (State.EMPTY, State.COMPLETE)
            else State.UNAVAILABLE
        )
        reason = "selected acquisition unavailable for this date/area"
        if named:
            state = next(
                (
                    a.state
                    for a in discovery.attempts
                    if a.source == "pc-stac" and a.state != State.COMPLETE
                ),
                State.INCOMPATIBLE,
            )
            reason = "no verified footprint for the requested product of this acquisition"
        return dict(
            result,
            state=state,
            reason=reason,
            inputs_ready=False,
        )
    result["scene"] = hit.model_dump(mode="json")
    result["footprint_state"] = State.COMPLETE if hit.covers_aoi else State.PARTIAL
    resolver = RasterResolver.local(data, policy)
    grid = resolver.locate(q.scene, q.product)
    image_state = grid.state
    result["grid_attempts"] = [a.model_dump() for a in grid.attempts]
    result["imagery"] = dict(state=image_state, reads=[])
    if grid.grid is not None:
        try:
            window = window_at(grid.grid, *hit.sample_lonlat, q.preview_pixels)
            raster = resolver.resolve(
                RasterRequest(scene=q.scene, product=q.product, window=window)
            )
            image_state = raster.state
            result["imagery"] = raster_summary(raster)
            if image_state == State.COMPLETE:
                valid = (~np.ma.getmaskarray(raster.stack())).all(axis=0)
                result["joint_valid_preview_pixels"] = int(valid.sum())
                if not valid.any():
                    image_state = State.EMPTY
                elif not valid.all():
                    image_state = State.PARTIAL
        except SourceError as exc:
            image_state = exc.state
            result["preview_error"] = str(exc)
            result["imagery"] = dict(state=image_state, reads=[])
    result["preview_state"] = image_state
    gap = timedelta(minutes=q.minutes)
    times = Interval(start=hit.scene.time.start - gap, end=hit.scene.time.end + gap)
    obs = load_positions(data, policy, PositionRequest(area=q.area, time=times))
    ref = load_reference(data, q.scene, q.area)
    queried = (State.COMPLETE, State.EMPTY, State.PARTIAL)
    result["positions"] = dict(
        state=obs.state,
        reported_variants=len(obs.observations) if obs.state in queried else None,
        time=times.model_dump(mode="json"),
        population_coverage=obs.population_coverage,
        exports=[e.model_dump(mode="json") for e in obs.exports],
        limitation=obs.limitation,
        attempts=[a.model_dump() for a in obs.attempts],
    )
    result["reference"] = dict(
        state=ref.state,
        published_rows=len(ref.predictions) if ref.state in queried else None,
        reason=ref.reason,
        covered=ref.covered.model_dump() if ref.covered else None,
        origin=ref.origin.model_dump(mode="json"),
    )
    states: dict[Layer, State] = {
        "imagery": result["footprint_state"] if image_state == State.COMPLETE else image_state,
        "positions": obs.state,
        "reference": ref.state,
    }
    result["inputs_ready"] = all(states[k] == State.COMPLETE for k in policy.required_layers)
    result["state"] = next(
        (states[k] for k in policy.required_layers if states[k] != State.COMPLETE), State.COMPLETE
    )
    return result
