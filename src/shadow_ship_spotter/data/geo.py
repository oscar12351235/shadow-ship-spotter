"""Explicit transformations between WGS84 lon/lat and the parent raster's native grid."""

from __future__ import annotations

from affine import Affine
from rasterio.control import GroundControlPoint
from rasterio.transform import GCPTransformer, rowcol
from rasterio.warp import transform

from .contracts import SourceError, State, Window
from .imagery import Grid


def points(grid: Grid) -> list[GroundControlPoint]:
    return [GroundControlPoint(row=r, col=c, x=x, y=y, z=z) for r, c, x, y, z in grid.gcps]


def pixel_at(grid: Grid, lon: float, lat: float) -> tuple[int, int]:
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("expected WGS84 longitude, latitude")
    if grid.gcps and grid.crs == "EPSG:4326":
        with GCPTransformer(points(grid)) as mapper:
            row, col = mapper.rowcol(lon, lat)
    elif grid.affine and grid.crs:
        xs, ys = transform("EPSG:4326", grid.crs, [lon], [lat])
        row, col = rowcol(Affine(*grid.affine), xs[0], ys[0])
    else:
        raise SourceError(State.INCOMPATIBLE, "no supported georeferencing on this grid")
    return int(row), int(col)


def window_at(grid: Grid, lon: float, lat: float, size: int) -> Window:
    if not 1 <= size <= 4096:
        raise ValueError("preview size must be between 1 and 4096")
    row, col = pixel_at(grid, lon, lat)
    if not (0 <= row < grid.height and 0 <= col < grid.width):
        raise SourceError(State.UNAVAILABLE, "selected point is outside the raster")
    x, y = max(0, col - size // 2), max(0, row - size // 2)
    return Window(
        col=x,
        row=y,
        width=min(col - size // 2 + size, grid.width) - x,
        height=min(row - size // 2 + size, grid.height) - y,
    )
