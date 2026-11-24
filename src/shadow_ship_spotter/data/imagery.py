"""Resolve each band and uncovered rectangle on one named acquisition and native grid."""

from __future__ import annotations

import io
import json
import logging
import warnings
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from zipfile import BadZipFile

import numpy as np
import rasterio
from pydantic import Field
from rasterio.errors import NotGeoreferencedWarning, RasterioIOError
from rasterio.io import DatasetReader
from rasterio.warp import transform_bounds
from rasterio.windows import Window as RioWindow

from .catalog import COLLECTION, STAC, pc_asset, pc_scene, read_item, xview_scenes
from .compatibility import Product, require_substitute
from .contracts import (
    Attempt,
    Band,
    Model,
    Origin,
    Policy,
    RasterProduct,
    RasterRequest,
    SourceError,
    State,
    Window,
    data_error,
    sensing_interval,
)
from .download import snapshot_sha256
from .http import get_json
from .storage import BlobCache, write_json

LOG = logging.getLogger(__name__)


class Grid(Model):
    """Transform/GCP coordinates refer to the *parent* grid, even for a cropped read."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    crs: str | None = None
    affine: tuple[float, float, float, float, float, float] | None = None
    gcps: tuple[tuple[float, float, float, float, float], ...] = ()  # row,col,x,y,z

    @property
    def extent(self) -> Window:
        return Window(col=0, row=0, width=self.width, height=self.height)


@dataclass(frozen=True)
class Piece:
    band: Band
    window: Window
    grid: Grid
    pixels: np.ma.MaskedArray
    origin: Origin
    scene: str


@dataclass(frozen=True)
class RasterResult:
    request: RasterRequest
    state: State
    pieces: tuple[Piece, ...]
    missing: dict[Band, tuple[Window, ...]]
    attempts: tuple[Attempt, ...]

    def stack(self) -> np.ma.MaskedArray:
        """Stack complete reads in requested band order, preserving the nodata mask."""
        if self.state != State.COMPLETE:
            raise SourceError(self.state, "incomplete raster request")
        w = self.request.window
        out = np.ma.masked_all(
            (len(self.request.bands), w.height, w.width), dtype=self.pieces[0].pixels.dtype
        )
        for p in self.pieces:
            y, x = p.window.row - w.row, p.window.col - w.col
            out[
                self.request.bands.index(p.band), y : y + p.window.height, x : x + p.window.width
            ] = p.pixels
        return out


class Reader(Protocol):
    product: Product

    def grid(self, scene: str, band: Band) -> Grid: ...

    def read(self, request: RasterRequest, band: Band, window: Window) -> Piece: ...


def native_read(src, window: Window, col: int = 0, row: int = 0) -> np.ma.MaskedArray:
    return src.read(
        1,
        window=RioWindow(window.col - col, window.row - row, window.width, window.height),
        masked=True,
    )


def inside(have: Window, want: Window) -> Window:
    overlap = have.intersect(want)
    if overlap is None:
        raise SourceError(State.UNAVAILABLE, "requested pixels outside asset extent")
    return overlap


@dataclass(frozen=True)
class OpenBand:
    dataset: DatasetReader
    grid: Grid
    extent: Window
    origin: Origin
    scene: str


class NativeReader(ABC):
    product: Product

    @abstractmethod
    def asset(self, scene: str, band: Band) -> AbstractContextManager[OpenBand]: ...

    def grid(self, scene: str, band: Band) -> Grid:
        with self.asset(scene, band) as asset:
            return asset.grid

    def read(self, request: RasterRequest, band: Band, window: Window) -> Piece:
        with self.asset(request.scene, band) as asset:
            if request.georeferenced and not (asset.grid.affine or asset.grid.gcps):
                raise SourceError(State.INCOMPATIBLE, "asset lacks georeferencing")
            actual = inside(asset.extent, window)
            pixels = native_read(asset.dataset, actual, asset.extent.col, asset.extent.row)
            if self.product in (Product.DN, Product.CROP):
                pixels = np.ma.masked_equal(pixels, 0)
            return Piece(band, actual, asset.grid, pixels, asset.origin, asset.scene)


class XViewReader(NativeReader):
    product = Product.DB

    def __init__(self, data: Path):
        self.data = data

    @contextmanager
    def asset(self, scene_id: str, band: Band) -> Iterator[OpenBand]:
        scene = xview_scenes(self.data).get(scene_id)
        if scene is None:
            raise SourceError(State.UNAVAILABLE, "scene absent from xView3 inventory")
        path = self.data / "raw/xview3/scenes" / scene.alias
        if (path / scene.alias).is_dir():
            path /= scene.alias
        path /= f"{band}_dB.tif"
        if not path.is_file():
            raise SourceError(State.UNAVAILABLE, f"xView3 {band} absent")
        try:
            with rasterio.open(path) as src:
                if (
                    str(src.crs) != scene.crs
                    or (src.width, src.height) != (scene.width, scene.height)
                    or src.dtypes != ("float16",)
                    or src.nodata != -32768
                    or src.transform.a != 10
                    or src.transform.e != -10
                    or src.transform.b != 0
                    or src.transform.d != 0
                    or not np.allclose(
                        transform_bounds(src.crs, "EPSG:4326", *src.bounds),
                        scene.bounds.xyxy,
                        rtol=0,
                        atol=1e-5,
                    )
                ):
                    raise SourceError(State.INCOMPATIBLE, "xView3 grid/unit contract mismatch")
                grid = Grid(
                    width=src.width, height=src.height, crs=str(src.crs), affine=src.transform[:6]
                )
                yield OpenBand(
                    src,
                    grid,
                    grid.extent,
                    scene.origin.model_copy(update={"asset": f"{scene.alias}/{path.name}"}),
                    scene.id,
                )
        except RasterioIOError as exc:
            raise data_error(exc, path.name) from None


def pc_folder(data: Path, scene: str) -> Path:
    return data / "raw/planetary_computer" / scene.rsplit("_", 1)[0]


class CropReader(NativeReader):
    product = Product.CROP

    def __init__(self, data: Path):
        self.data = data

    @contextmanager
    def asset(self, scene_id: str, band: Band) -> Iterator[OpenBand]:
        folder = pc_folder(self.data, scene_id)
        item = read_item(folder / "item.json")
        scene, _ = pc_scene(item)
        if scene.id != scene_id or band not in item["properties"]["sar:polarizations"]:
            raise SourceError(State.INCOMPATIBLE, "crop parent or polarisation differs")
        metadata = read_item(folder / "window_meta.json")
        name = f"window_{band.lower()}.tif"
        if band.lower() not in metadata or not (folder / name).is_file():
            raise SourceError(State.UNAVAILABLE, f"missing saved {band} window")
        try:
            entry = metadata[band.lower()]
            release = read_item(self.data / "sources.json")["planetary_computer_s1_grd"]
            expected = release.get("legacy_native_crop_sha256", {}).get(scene_id, {}).get(band)
            if expected is None:
                raise SourceError(
                    State.INCOMPATIBLE, "no verified legacy crop for this parent/band"
                )
            if snapshot_sha256(folder / name) != expected:
                raise SourceError(State.CORRUPT, "legacy crop failed its band-specific SHA-256")
            x, y, w, h = entry["window"]
            stored = Window(col=x, row=y, width=w, height=h)
            grid = Grid(width=scene.width, height=scene.height)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", NotGeoreferencedWarning)
                dataset = rasterio.open(folder / name)
            with dataset as src:
                if (
                    entry["shape"] != [scene.height, scene.width]
                    or src.shape != (h, w)
                    or entry["dtype"] != "uint16"
                    or src.dtypes != ("uint16",)
                    or src.tags().get("source") != scene.alias
                    or json.loads(src.tags().get("window", "null")) != entry["window"]
                    or grid.extent.intersect(stored) != stored
                ):
                    raise SourceError(State.INCOMPATIBLE, "crop metadata/grid mismatch")
                gcps, crs = src.gcps
                if gcps and str(crs) == "EPSG:4326":
                    grid = grid.model_copy(
                        update={
                            "crs": str(crs),
                            "gcps": tuple((p.row + y, p.col + x, p.x, p.y, p.z) for p in gcps),
                        }
                    )
                yield OpenBand(
                    src,
                    grid,
                    stored,
                    Origin(
                        source="pc-crop",
                        asset=f"{scene.id}/{name}",
                        product=self.product,
                        revision=scene.id,
                        transformations=("native-grid crop",),
                    ),
                    scene.id,
                )
        except (RasterioIOError, KeyError, ValueError, TypeError) as exc:
            raise data_error(exc, name) from None


class CogReader(NativeReader):
    product = Product.DN

    def __init__(self, data: Path):
        self.data = data

    @contextmanager
    def asset(self, scene_id: str, band: Band) -> Iterator[OpenBand]:
        folder = pc_folder(self.data, scene_id)
        local = folder / "item.json"
        saved = self.data / "processed/catalogue-pc" / scene_id / "item.json"
        if saved.is_file():
            local = saved
        item = (
            read_item(local)
            if local.is_file()
            else get_json(f"{STAC}/collections/{COLLECTION}/items/{folder.name}")
        )
        scene, _ = pc_scene(item)
        if scene.id != scene_id or band not in item["properties"]["sar:polarizations"]:
            raise SourceError(State.INCOMPATIBLE, "remote product or polarisation differs")
        _, href = pc_asset(item, band)
        if not local.is_file():
            # Retain only verified unsigned measurement hrefs and the catalogue fields used.
            unsigned = {k: item[k] for k in ("id", "collection", "geometry", "properties")}
            unsigned["assets"] = {
                pol.lower(): {"href": pc_asset(item, pol)[1]}
                for pol in item["properties"]["sar:polarizations"]
            }
            unsigned["sss:retrieved_at"] = datetime.now(UTC).isoformat()
            write_json(saved, unsigned)
        response = get_json(
            f"https://planetarycomputer.microsoft.com/api/sas/v1/token/{COLLECTION}"
        )
        token = response.get("token")
        if not isinstance(token, str) or not token:
            raise SourceError(State.ACCESS, "PC supplied no asset access token")
        # Credentials stay in GDAL's scoped Azure environment. Dataset names never contain a SAS.
        path = "/vsiaz" + urlparse(href).path
        try:
            with (
                rasterio.Env(
                    AZURE_STORAGE_ACCOUNT="sentinel1euwest",
                    AZURE_STORAGE_SAS_TOKEN=token.lstrip("?"),
                    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                    GDAL_HTTP_TIMEOUT="20",
                    GDAL_HTTP_MAX_RETRY="2",
                    GDAL_HTTP_RETRY_DELAY="1",
                ),
                rasterio.open(path) as src,
            ):
                if src.dtypes != ("uint16",) or (src.width, src.height) != (
                    scene.width,
                    scene.height,
                ):
                    raise SourceError(
                        State.INCOMPATIBLE, "unexpected GRD sample type or dimensions"
                    )
                gcps, crs = src.gcps
                if not gcps or str(crs) != "EPSG:4326":
                    raise SourceError(
                        State.INCOMPATIBLE, "expected native GRD WGS84 control points"
                    )
                grid = Grid(
                    width=src.width,
                    height=src.height,
                    crs=str(crs),
                    gcps=tuple((p.row, p.col, p.x, p.y, p.z) for p in gcps),
                )
                yield OpenBand(
                    src,
                    grid,
                    grid.extent,
                    Origin(
                        source="pc-cog",
                        asset=f"{scene.id}/measurement/{band}",
                        product=self.product,
                        revision=scene.id,
                        retrieved_at=datetime.now(UTC),
                        provider_updated_at=scene.origin.provider_updated_at,
                        transformations=("native-grid range read",),
                    ),
                    scene.id,
                )
        except RasterioIOError as exc:
            state = (
                State.ACCESS
                if any(s in str(exc) for s in ("401", "403", "denied"))
                else (State.CORRUPT if "TIFFRead" in str(exc) else State.UNAVAILABLE)
            )
            raise SourceError(state, "PC measurement range read failed") from None


class CachedCog:
    product = Product.DN
    version = "pc-grd-native-window-v1"

    def __init__(self, reader: Reader, cache: BlobCache, online: bool):
        self.reader, self.cache, self.online = reader, cache, online

    def family(self, scene: str, band: Band) -> str:
        return json.dumps([self.version, "pc-cog", self.product, scene, band])

    def grid(self, scene: str, band: Band) -> Grid:
        family = self.family(scene, band)
        key = json.dumps([family, "geolocation"])
        try:
            metadata = self.cache.get(key)
            if metadata is not None:
                return Grid.model_validate_json(metadata)
            # Older windows already contain the verified parent grid. Prefer the smallest record.
            candidate = self.cache.first_window(family)
            if candidate and (raw := self.cache.get(candidate)) is not None:
                with np.load(io.BytesIO(raw), allow_pickle=False) as v:
                    return Grid.model_validate_json(str(v["grid"]))
        except (ValueError, KeyError, BadZipFile, EOFError) as exc:
            if not self.online:
                raise data_error(exc, "cached parent grid") from None
            LOG.warning("Refetching invalid cached parent grid for %s %s", scene, band)
        except SourceError as exc:
            if exc.state != State.CORRUPT or not self.online:
                raise
            LOG.warning("Refetching damaged cached parent grid for %s %s", scene, band)
        if not self.online:
            raise SourceError(State.UNAVAILABLE, "offline; no cached parent grid")
        grid = self.reader.grid(scene, band)
        self.cache.put(key, grid.model_dump_json().encode())
        return grid

    def read(self, request: RasterRequest, band: Band, window: Window) -> Piece:
        family = self.family(request.scene, band)
        key = json.dumps([family, window.model_dump()], sort_keys=True)
        candidate = self.cache.overlap(family, window)
        repaired = False
        try:
            raw = self.cache.get(candidate or key)
        except SourceError as exc:
            if not self.online or exc.state != State.CORRUPT:
                raise
            repaired = True
            raw = None
        if raw is not None:
            try:
                with np.load(io.BytesIO(raw), allow_pickle=False) as v:
                    origin = Origin.model_validate_json(str(v["origin"]))
                    grid = Grid.model_validate_json(str(v["grid"]))
                    actual = Window.model_validate_json(str(v["window"]))
                    clip = inside(actual, window)
                    if (
                        origin.asset != f"{request.scene}/measurement/{band}"
                        or origin.revision != request.scene
                        or (candidate or key)
                        != json.dumps([family, actual.model_dump()], sort_keys=True)
                    ):
                        raise SourceError(
                            State.CORRUPT, "cached identity does not match the request"
                        )
                    values = np.ma.array(v["data"], mask=v["mask"])
                    x, y = clip.col - actual.col, clip.row - actual.row
                    return Piece(
                        band,
                        clip,
                        grid,
                        values[y : y + clip.height, x : x + clip.width],
                        origin.model_copy(
                            update={
                                "transformations": (*origin.transformations, "verified cache read")
                            }
                        ),
                        request.scene,
                    )
            except (ValueError, KeyError, BadZipFile, EOFError) as exc:
                raise data_error(exc, "cached raster") from None
        if not self.online:
            raise SourceError(State.UNAVAILABLE, "offline; requested pixels missing from PC cache")
        p = self.reader.read(request, band, window)
        if (
            p.scene != request.scene
            or p.band != band
            or p.origin.asset != f"{request.scene}/measurement/{band}"
            or p.origin.revision != request.scene
            or p.origin.product != self.product
            or p.pixels.dtype != np.uint16
            or p.pixels.shape != (p.window.height, p.window.width)
            or p.window != window.intersect(p.window)
            or p.window != p.grid.extent.intersect(p.window)
        ):
            raise SourceError(
                State.INCOMPATIBLE, "measurement differs from the requested native product"
            )
        key = json.dumps([family, p.window.model_dump()], sort_keys=True)
        if repaired:
            p = Piece(
                band,
                p.window,
                p.grid,
                p.pixels,
                p.origin.model_copy(
                    update={
                        "transformations": (
                            *p.origin.transformations,
                            "refetched after cache digest failure",
                        )
                    }
                ),
                p.scene,
            )
        f = io.BytesIO()
        np.savez_compressed(
            f,
            data=p.pixels.data,
            mask=np.ma.getmaskarray(p.pixels),
            origin=p.origin.model_dump_json(),
            grid=p.grid.model_dump_json(),
            window=p.window.model_dump_json(),
        )
        self.cache.put(key, f.getvalue(), coverage=(family, p.window))
        return p


class GridLookup(Model):
    state: State
    grid: Grid | None
    attempts: tuple[Attempt, ...]


class RasterResolver:
    def __init__(self, policy: Policy, readers: dict[str, Reader]):
        self.policy, self.readers = policy, readers
        if missing := set(policy.raster_priority).difference(readers):
            raise ValueError(f"missing configured raster providers: {sorted(missing)}")

    @classmethod
    def local(cls, data: Path, policy: Policy) -> RasterResolver:
        cache = BlobCache(data / "processed/cache/pc-windows.sqlite3")
        return cls(
            policy,
            {
                "xview3": XViewReader(data),
                "pc-crop": CropReader(data),
                "pc-cog": CachedCog(CogReader(data), cache, policy.online),
            },
        )

    def locate(self, scene: str, product: RasterProduct, band: Band = "VV") -> GridLookup:
        sensing_interval(scene)
        attempts = []
        errors = []
        for name in self.policy.raster_priority:
            reader = self.readers[name]
            try:
                require_substitute(Product(product), reader.product)
            except SourceError as exc:
                attempts.append(
                    Attempt(source=name, state=exc.state, reason=str(exc), applicable=False)
                )
                continue
            try:
                grid = reader.grid(scene, band)
                if not grid.crs or not (grid.affine or grid.gcps):
                    raise SourceError(State.INCOMPATIBLE, "no geolocation on this asset")
                attempts.append(
                    Attempt(source=name, state=State.COMPLETE, reason=f"{band} parent grid")
                )
                return GridLookup(state=State.COMPLETE, grid=grid, attempts=tuple(attempts))
            except SourceError as exc:
                errors.append(exc.state)
                attempts.append(Attempt(source=name, state=exc.state, reason=str(exc)))
        return GridLookup(state=_failure_state(errors), grid=None, attempts=tuple(attempts))

    def resolve(self, request: RasterRequest) -> RasterResult:
        missing: dict[Band, tuple[Window, ...]] = {b: (request.window,) for b in request.bands}
        pieces: list[Piece] = []
        attempts: list[Attempt] = []
        errors: list[State] = []
        for name in self.policy.raster_priority:
            if not any(missing.values()):
                break
            reader = self.readers[name]
            try:
                require_substitute(Product(request.product), reader.product)
            except SourceError as exc:
                attempts.append(
                    Attempt(source=name, state=exc.state, reason=str(exc), applicable=False)
                )
                continue
            for band in request.bands:
                rest: list[Window] = []
                pending = list(missing[band])
                while pending:
                    window = pending.pop(0)
                    try:
                        p = reader.read(request, band, window)
                        if (
                            p.scene != request.scene
                            or p.origin.product != reader.product
                            or p.band != band
                            or p.grid.extent.intersect(p.window) != p.window
                            or window.intersect(p.window) != p.window
                            or p.pixels.shape != (p.window.height, p.window.width)
                            or (
                                request.georeferenced
                                and not (p.grid.crs and (p.grid.affine or p.grid.gcps))
                            )
                        ):
                            raise SourceError(State.INCOMPATIBLE, "invalid band, grid or support")
                        for prev in pieces:
                            if (
                                prev.grid.extent != p.grid.extent
                                or prev.pixels.dtype != p.pixels.dtype
                                or (prev.grid.crs and p.grid.crs and prev.grid != p.grid)
                            ):
                                raise SourceError(State.INCOMPATIBLE, "incompatible parent grids")
                        parts = window.subtract(p.window)
                        pieces.append(p)
                        if isinstance(reader, CachedCog):
                            pending.extend(part for part in parts if p.grid.extent.intersect(part))
                            rest.extend(part for part in parts if not p.grid.extent.intersect(part))
                        else:
                            rest.extend(parts)
                        attempts.append(
                            Attempt(
                                source=name,
                                state=State.PARTIAL if parts else State.COMPLETE,
                                reason=f"{band} {p.window} from {p.origin.asset}",
                            )
                        )
                    except SourceError as exc:
                        errors.append(exc.state)
                        rest.append(window)
                        attempts.append(
                            Attempt(source=name, state=exc.state, reason=f"{band}: {exc}")
                        )
                missing[band] = tuple(rest)
        if any(missing.values()):
            state = State.PARTIAL if pieces else _failure_state(errors)
        else:
            state = State.COMPLETE
        LOG.info("raster %s %s: %s (%d pieces)", request.scene, request.product, state, len(pieces))
        return RasterResult(request, state, tuple(pieces), missing, tuple(attempts))


def _failure_state(errors: list[State]) -> State:
    return next(
        (
            s
            for s in (State.CORRUPT, State.ACCESS, State.INCOMPATIBLE, State.UNAVAILABLE)
            if s in errors
        ),
        State.INCOMPATIBLE,
    )
