"""Public conventions for acquisition, grid coordinates, product routing and diagnostics."""

from __future__ import annotations

import re
import tomllib
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)


class Model(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True
    )


Utc = Annotated[AwareDatetime, AfterValidator(lambda v: v.astimezone(UTC))]
SCENE_PATTERN = (
    r"^S1[ABCD]_[A-Z0-9]{2}_GRD[FHM]_[0-9][A-Z0-9]{3}_"
    r"[0-9]{8}T[0-9]{6}_[0-9]{8}T[0-9]{6}_[0-9]{6}_[0-9A-F]{6}_[0-9A-F]{4}$"
)
SceneID = Annotated[str, Field(pattern=SCENE_PATTERN)]
Band = Literal["VV", "VH"]
RasterSource = Literal["xview3", "pc-crop", "pc-cog"]
RasterProduct = Literal["xview3-db-10m", "s1-grd-dn"]
Layer = Literal["imagery", "positions", "reference"]


class State(StrEnum):
    COMPLETE = "complete"
    EMPTY = "empty"
    PARTIAL = "partial"
    UNKNOWN = "unknown_coverage"
    UNAVAILABLE = "unavailable"
    ACCESS = "access_denied"
    CORRUPT = "corrupt"
    INCOMPATIBLE = "incompatible"


class SourceError(Exception):
    """Expected provider/data error. Messages must be safe to log."""

    def __init__(self, state: State, message: str):
        self.state = state
        super().__init__(message)


class Attempt(Model):
    source: str
    state: State
    reason: str
    applicable: bool = True


class Origin(Model):
    source: str
    asset: str
    product: str
    revision: str
    retrieved_at: Utc | None = None
    run_started_at: Utc | None = None
    provider_updated_at: Utc | None = None
    transformations: tuple[str, ...] = ()


class Interval(Model):
    """UTC, half-open [start, end). Never infer a timezone from the host."""

    start: Utc
    end: Utc

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must follow start")
        return self

    @classmethod
    def day(cls, day: date) -> Self:
        start = datetime.combine(day, time.min, UTC)
        return cls(start=start, end=start + timedelta(days=1))

    def intersects(self, other: Interval) -> bool:
        return self.start < other.end and other.start < self.end


def sensing_interval(scene: str) -> Interval:
    if not re.fullmatch(SCENE_PATTERN, scene):
        raise ValueError("expected the complete ESA GRD product name including its unique suffix")
    a, b = scene.split("_")[4:6]
    return Interval(
        start=datetime.strptime(a, "%Y%m%dT%H%M%S").replace(tzinfo=UTC),
        end=datetime.strptime(b, "%Y%m%dT%H%M%S").replace(tzinfo=UTC),
    )


def acquisition_group(scene: str) -> str:
    """One platform/orbit/datatake group across processors, polarisations and adjacent slices."""
    sensing_interval(scene)
    parts = scene.split("_")
    return "/".join((parts[0], parts[6], parts[7]))


class Bounds(Model):
    """EPSG:4326 longitude, latitude; split antimeridian-crossing viewports before querying."""

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.east <= self.west or self.north <= self.south:
            raise ValueError("expected west < east and south < north")
        return self

    @property
    def xyxy(self) -> tuple[float, float, float, float]:
        return self.west, self.south, self.east, self.north

    def contains(self, lon: float, lat: float) -> bool:
        return self.west <= lon <= self.east and self.south <= lat <= self.north


class Window(Model):
    """Integer pixel edges in the named product's native grid, origin upper left."""

    col: int = Field(ge=0, strict=True)
    row: int = Field(ge=0, strict=True)
    width: int = Field(gt=0, strict=True)
    height: int = Field(gt=0, strict=True)

    @property
    def right(self) -> int:
        return self.col + self.width

    @property
    def bottom(self) -> int:
        return self.row + self.height

    def intersect(self, other: Window) -> Window | None:
        x, y = max(self.col, other.col), max(self.row, other.row)
        w, h = min(self.right, other.right) - x, min(self.bottom, other.bottom) - y
        return Window(col=x, row=y, width=w, height=h) if w > 0 and h > 0 else None

    def subtract(self, inside: Window) -> tuple[Window, ...]:
        """Disjoint strips of self left after a verified rectangular read."""
        if self.intersect(inside) != inside:
            raise ValueError("returned window lies outside the request")
        parts = (
            (self.col, self.row, self.width, inside.row - self.row),
            (self.col, inside.bottom, self.width, self.bottom - inside.bottom),
            (self.col, inside.row, inside.col - self.col, inside.height),
            (inside.right, inside.row, self.right - inside.right, inside.height),
        )
        return tuple(Window(col=x, row=y, width=w, height=h) for x, y, w, h in parts if w and h)


class RasterRequest(Model):
    scene: SceneID
    product: RasterProduct
    window: Window
    bands: tuple[Band, ...] = ("VV", "VH")
    georeferenced: bool = True

    @model_validator(mode="after")
    def bounded(self) -> Self:
        sensing_interval(self.scene)
        if not self.bands or len(set(self.bands)) != len(self.bands):
            raise ValueError("specify distinct bands")
        if self.window.width * self.window.height > 4096**2:
            raise ValueError("split reads larger than 16 megapixels into windows")
        return self


class Policy(Model):
    version: Literal[1]
    online: bool = False
    raster_priority: tuple[RasterSource, ...]
    required_layers: tuple[Layer, ...] = ("imagery",)
    # Explicit export runs; never select a different vintage by modification time.
    lseg_runs: tuple[Annotated[str, Field(pattern=r"^probe_[0-9]{8}T[0-9]{6}Z$")], ...] = ()

    @model_validator(mode="after")
    def routes(self) -> Self:
        for seq in (self.raster_priority, self.required_layers, self.lseg_runs):
            if len(seq) != len(set(seq)):
                raise ValueError("duplicate configuration reference")
        if not self.raster_priority or "imagery" not in self.required_layers:
            raise ValueError("a raster provider and the required imagery layer are needed")
        if "pc-cog" in self.raster_priority and self.raster_priority[-1] != "pc-cog":
            raise ValueError("local raster routes must precede the network route")
        return self

    @classmethod
    def read(cls, path: Path) -> Self:
        with path.open("rb") as stream:
            return cls.model_validate(tomllib.load(stream))


def data_error(exc: Exception, asset: str) -> SourceError:
    """Only call for explicitly handled input/IO exceptions at a provider boundary."""
    if isinstance(exc, FileNotFoundError):
        return SourceError(State.UNAVAILABLE, f"missing {asset}")
    if isinstance(exc, PermissionError):
        return SourceError(State.ACCESS, f"access denied to {asset}")
    if isinstance(exc, ValidationError):
        return SourceError(State.CORRUPT, f"invalid {asset} fields: {exc.error_count()} errors")
    return SourceError(State.CORRUPT, f"invalid {asset} ({type(exc).__name__})")
