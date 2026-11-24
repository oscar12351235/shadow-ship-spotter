"""Discovery returns acquisition candidates. A catalogue footprint does not certify valid pixels."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlparse

from pydantic import Field
from shapely import Geometry, box
from shapely.errors import ShapelyError
from shapely.geometry import shape

from .contracts import (
    Attempt,
    Bounds,
    Interval,
    Model,
    Origin,
    SceneID,
    SourceError,
    State,
    data_error,
    sensing_interval,
)
from .http import get_json

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-1-grd"
ASSET_HOST = "sentinel1euwest.blob.core.windows.net"


class Scene(Model):
    id: SceneID
    alias: str
    time: Interval
    bounds: Bounds
    extent_kind: Literal["raster_envelope", "catalogue_footprint"]
    bands: tuple[str, ...]
    origin: Origin
    crs: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Hit(Model):
    scene: Scene
    intersection_bounds: Bounds
    covers_aoi: bool
    sample_lonlat: tuple[float, float]


class Discovery(Model):
    state: State
    hits: tuple[Hit, ...]
    attempts: tuple[Attempt, ...]
    scope: str


def bounds(values: tuple[float, ...]) -> Bounds:
    return Bounds(west=values[0], south=values[1], east=values[2], north=values[3])


def xview_scenes(data: Path) -> dict[str, Scene]:
    path = data / "inventory/xview3_scenes.csv"
    result: dict[str, Scene] = {}
    try:
        with path.open(encoding="utf-8", newline="") as f:
            rows = csv.DictReader(f)
            if not {
                "esa_scene_name",
                "scene_id",
                "crs",
                "width",
                "height",
                "lon_min",
                "lon_max",
                "lat_min",
                "lat_max",
                "acquisition_start_utc",
                "acquisition_stop_utc",
            }.issubset(rows.fieldnames or ()):
                raise ValueError("scene inventory schema")
            for r in rows:
                sid, alias = r["esa_scene_name"], r["scene_id"]
                if not re.fullmatch(r"[0-9a-f]{16}[tvp]", alias):
                    raise ValueError("invalid xView3 id")
                times = Interval.model_validate(
                    dict(start=r["acquisition_start_utc"], end=r["acquisition_stop_utc"])
                )
                if sid in result or times != sensing_interval(sid):
                    raise ValueError("ambiguous acquisition")
                result[sid] = Scene(
                    id=sid,
                    alias=alias,
                    time=times,
                    bounds=bounds(
                        tuple(float(r[k]) for k in ("lon_min", "lat_min", "lon_max", "lat_max"))
                    ),
                    extent_kind="raster_envelope",
                    bands=("VV", "VH"),
                    crs=r["crs"],
                    width=int(r["width"]),
                    height=int(r["height"]),
                    origin=Origin(
                        source="xview3",
                        asset=alias,
                        product="xview3-db-10m",
                        revision="xview3-2021",
                    ),
                )
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        raise data_error(exc, path.name) from None
    return result


def pc_asset(item: dict, band: str) -> tuple[str, str]:
    """Verify the full parent in the asset path. PC item IDs alone omit the product suffix."""
    try:
        href = item["assets"][band.lower()]["href"]
        u = urlparse(href)
        parent, folder, filename = u.path.split("/")[-3:]
        if (
            u.scheme != "https"
            or u.netloc != ASSET_HOST
            or u.query
            or u.fragment
            or folder != "measurement"
            or filename.lower()
            != f"{item['properties']['sar:instrument_mode'].lower()}-{band.lower()}.tiff"
        ):
            raise ValueError("unexpected asset")
        sensing_interval(parent)
        if item["id"] != parent.rsplit("_", 1)[0]:
            raise ValueError("asset parent differs from item")
        return parent, href
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise data_error(exc, "PC measurement asset") from None


def pc_scene(item: dict, retrieved: datetime | None = None) -> tuple[Scene, Geometry]:
    try:
        p = item["properties"]
        if item["collection"] != COLLECTION or p["sar:product_type"] != "GRD":
            raise SourceError(State.INCOMPATIBLE, "expected Sentinel-1 GRD")
        pols = p["sar:polarizations"]
        if not isinstance(pols, list) or not pols:
            raise ValueError("missing polarisation metadata")
        ids = {pc_asset(item, band)[0] for band in pols}
        if len(ids) != 1:
            raise ValueError("polarisation parent mismatch")
        sid = ids.pop()
        times = Interval.model_validate(dict(start=p["start_datetime"], end=p["end_datetime"]))
        encoded = sensing_interval(sid)
        if any(
            a.replace(microsecond=0) != b
            for a, b in ((times.start, encoded.start), (times.end, encoded.end))
        ):
            raise ValueError("catalogue and asset sensing times disagree")
        geom = shape(item["geometry"])
        if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty or not geom.is_valid:
            raise ValueError("invalid footprint")
        scene = Scene(
            id=sid,
            alias=item["id"],
            time=times,
            bounds=bounds(geom.bounds),
            extent_kind="catalogue_footprint",
            bands=tuple(pols),
            width=p["s1:shape"][0],
            height=p["s1:shape"][1],
            origin=Origin(
                source="pc",
                asset=item["id"],
                product="s1-grd-dn",
                revision=sid,
                provider_updated_at=p.get("updated"),
                retrieved_at=retrieved or item.get("sss:retrieved_at"),
            ),
        )
        return scene, geom
    except (KeyError, IndexError, TypeError, ValueError, ShapelyError) as exc:
        raise data_error(exc, "PC item") from None


def read_item(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            item = json.load(f)
        if not isinstance(item, dict):
            raise ValueError("invalid item")
        return item
    except (OSError, ValueError) as exc:
        raise data_error(exc, path.name) from None


def pc_search(area: Bounds, window: Interval) -> Iterator[dict]:
    query = urlencode(
        dict(
            collections=COLLECTION,
            bbox=",".join(map(str, area.xyxy)),
            datetime=f"{window.start.isoformat()}/{window.end.isoformat()}",
            limit=100,
        )
    )
    url = f"{STAC}/search?{query}"
    seen: set[str] = set()
    while url:
        if url in seen:
            raise SourceError(State.CORRUPT, "catalogue pagination cycle")
        seen.add(url)
        page = get_json(url)
        features, links = page.get("features"), page.get("links")
        if not isinstance(features, list) or not isinstance(links, list):
            raise SourceError(State.CORRUPT, "invalid STAC search response")
        yield from features
        try:
            next_links = [v for v in links if v["rel"] == "next"]
            url = next_links[0]["href"] if next_links else ""
            if next_links and (
                len(next_links) != 1
                or next_links[0].get("method", "GET") != "GET"
                or not url.startswith(f"{STAC}/search?")
            ):
                raise SourceError(State.INCOMPATIBLE, "unsupported STAC pagination link")
        except (KeyError, TypeError, AttributeError) as exc:
            raise data_error(exc, "STAC links") from None


def discover(data: Path, area: Bounds, window: Interval, *, online: bool = False) -> Discovery:
    aoi = box(*area.xyxy)
    hits: dict[tuple[str, str], Hit] = {}
    attempts = []

    def add(scene: Scene, footprint: Geometry) -> None:
        if scene.time.intersects(window):
            clip = footprint.intersection(aoi)
            if not clip.is_empty and clip.area > 0:
                pt = clip.representative_point()
                hits[(scene.id, scene.origin.source)] = Hit(
                    scene=scene,
                    intersection_bounds=bounds(clip.bounds),
                    covers_aoi=footprint.covers(aoi),
                    sample_lonlat=(pt.x, pt.y),
                )

    try:
        for scene in xview_scenes(data).values():
            add(scene, box(*scene.bounds.xyxy))
        attempts.append(Attempt(source="xview3", state=State.COMPLETE, reason="indexed envelopes"))
    except SourceError as exc:
        attempts.append(Attempt(source="xview3", state=exc.state, reason=str(exc)))
    paths = sorted((data / "raw/planetary_computer").glob("*/item.json"))
    paths += sorted((data / "processed/catalogue-pc").glob("*/item.json"))
    for path in paths:
        try:
            add(*pc_scene(read_item(path)))
        except SourceError as exc:
            attempts.append(Attempt(source="pc-crop", state=exc.state, reason=str(exc)))
    if online:
        try:
            for item in pc_search(area, window):
                add(*pc_scene(item, datetime.now(UTC)))
            attempts.append(
                Attempt(source="pc-stac", state=State.COMPLETE, reason="exhausted pages")
            )
        except SourceError as exc:
            attempts.append(Attempt(source="pc-stac", state=exc.state, reason=str(exc)))
    failed = [a.state for a in attempts if a.state != State.COMPLETE]
    state = (
        (State.PARTIAL if hits else failed[0])
        if failed
        else (State.COMPLETE if hits else State.EMPTY)
    )
    return Discovery(
        state=state,
        hits=tuple(
            sorted(
                hits.values(), key=lambda h: (h.scene.time.start, h.scene.id, h.scene.origin.source)
            )
        ),
        attempts=tuple(attempts),
        scope="indexed local scenes" + (" and PC GRD catalogue" if online else ""),
    )
