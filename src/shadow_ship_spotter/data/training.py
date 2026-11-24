"""Identical sample references, partitions and raw pixels for descriptor and CNN consumers."""

from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self
from zipfile import BadZipFile

import numpy as np
import zarr
from PIL import Image
from pydantic import Field, model_validator
from zarr.storage import ZipStore

from .catalog import xview_scenes
from .compatibility import Product
from .contracts import (
    Interval,
    Model,
    Origin,
    Policy,
    RasterRequest,
    SourceError,
    State,
    Window,
    acquisition_group,
    data_error,
    sensing_interval,
)
from .download import file_hash
from .imagery import RasterResolver

Family = Literal["gfw-tiles", "xview3", "ssdd"]
Partition = Literal["train", "validation", "test", "benchmark"]
SHA256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
BoxXYWH = tuple[float, float, float, float]
LonLat = tuple[Annotated[float, Field(ge=-180, le=180)], Annotated[float, Field(ge=-90, le=90)]]
TILE_ZIP = "raw/gfw_paolo2024/training/detection_tiles.zip"
LABEL_PRODUCTS = {
    "xview3": (Product.REVIEWED, Product.WEAK),
    "gfw-tiles": (Product.TILES,),
    "ssdd": (Product.SSDD,),
}


class Manifest(Model):
    version: Literal[1]
    seed: str = Field(min_length=1)
    chip_size: int = Field(gt=0, le=4096)
    scene_assignments: dict[str, Literal["train", "validation", "test"]]
    sha256: dict[str, SHA256]

    @model_validator(mode="after")
    def names(self) -> Self:
        for p in self.sha256:
            if not re.fullmatch(r"(?:[\w.-]+/)*[\w.-]+", p) or ".." in p.split("/"):
                raise ValueError("expected a relative dataset path")
        if any(not re.fullmatch(r"S1[ABCD]/\d{6}/[0-9A-F]{6}", g) for g in self.scene_assignments):
            raise ValueError("invalid scene group override")
        return self

    def split(self, scene: str) -> Partition:
        group = acquisition_group(scene)
        if group in self.scene_assignments:
            return self.scene_assignments[group]
        n = int.from_bytes(hashlib.sha256(f"{self.seed}/{group}".encode()).digest()[:8]) % 100
        return "train" if n < 70 else "validation" if n < 85 else "test"


class Example(Model):
    id: str
    product: Product
    split: Partition
    group: str
    scene: str | None
    acquisition: Interval | None = None
    lonlat: LonLat | None = None
    presence: bool | None
    fishing: bool | None = None
    annotation_source: str
    confidence: str | None = None
    length_m: float | None = None
    weight: float | None = None
    window: Window | None = None
    # Boxes in returned image coordinates (x, y, width, height), before clipping.
    boxes: tuple[BoxXYWH, ...] = ()
    center_xy: tuple[int, int] | None = None


@dataclass(frozen=True)
class Sample:
    example: Example
    pixels: np.ma.MaskedArray  # C,H,W; native scale/dtype and nodata mask
    channels: tuple[str, ...]
    origins: tuple[Origin, ...]
    manifest_sha256: str


class TrainingSet:
    """Open one family at a time. A pin is checked before its first use in this session."""

    def __init__(
        self,
        data: Path,
        family: Family,
        manifest: Path | None = None,
        *,
        product: Product | None = None,
    ):
        self.data, self.family = data, family
        if family not in LABEL_PRODUCTS:
            raise ValueError(f"unknown training family {family}")
        self.product = product or LABEL_PRODUCTS[family][0]
        if self.product not in LABEL_PRODUCTS[family]:
            raise SourceError(State.INCOMPATIBLE, f"{family} cannot supply {self.product}")
        raw = (manifest or data / "splits/training-v1.json").read_bytes()
        self.manifest = Manifest.model_validate_json(raw)
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        self._verified: dict[str, tuple[int, int, int]] = {}
        self._rows: dict[str, dict] = {}
        self._examples: dict[str, Example] = {}
        self._resources = ExitStack()
        self._zarr: zarr.Group | None = None
        self._resolver = RasterResolver.local(data, Policy(version=1, raster_priority=("xview3",)))
        loaders = {
            "gfw-tiles": self._tile_index,
            "xview3": self._xview_index,
            "ssdd": self._ssdd_index,
        }
        try:
            for example, row in loaders[family]():
                if example.product != self.product:
                    continue
                if example.id in self._examples:
                    raise ValueError("duplicate example identity")
                self._examples[example.id], self._rows[example.id] = example, row
        except (KeyError, ValueError, OSError, csv.Error) as exc:
            raise data_error(exc, f"{family} index") from None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self._resources.close()
        self._zarr = None

    def _pin(self, name: str) -> Path:
        digest = self.manifest.sha256.get(name)
        if digest is None:
            raise SourceError(State.INCOMPATIBLE, f"unversioned training asset: {name}")
        path = self.data / name
        if not path.is_file():
            raise SourceError(State.UNAVAILABLE, f"missing pinned asset: {name}")
        st = path.stat()
        identity = (st.st_ino, st.st_size, st.st_mtime_ns)
        if self._verified.get(name) != identity:
            if file_hash(path) != digest:
                raise SourceError(State.CORRUPT, f"training SHA-256 mismatch: {name}")
            self._verified[name] = identity
        return path

    def _index(self, name: str, required: set[str]) -> Iterator[dict]:
        with self._pin(name).open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not required.issubset(reader.fieldnames or ()):
                raise ValueError(f"missing columns in {name}")
            yield from reader

    def _tile_index(self) -> Iterator[tuple[Example, dict]]:
        for r in self._index(
            "inventory/gfw_detection_tiles.csv",
            {"tile_index", "detect_id", "scene_id", "presence", "weight", "length_m", "lon", "lat"},
        ):
            scene = r["scene_id"]
            if r["presence"] not in ("0", "1") or r["detect_id"].split(";")[0] != scene:
                raise ValueError("invalid GFW tile identity or target")
            yield Example(
                id=r["detect_id"],
                product=Product.TILES,
                split=self.manifest.split(scene),
                scene=scene,
                acquisition=sensing_interval(scene),
                lonlat=(float(r["lon"]), float(r["lat"])),
                group=acquisition_group(scene),
                presence=r["presence"] == "1",
                annotation_source="Paolo et al. presence/length training release",
                length_m=float(r["length_m"]) if float(r["length_m"]) > 0 else None,
                weight=float(r["weight"]),
            ), r

    def _ssdd_index(self) -> Iterator[tuple[Example, dict]]:
        boxes: dict[str, list[BoxXYWH]] = defaultdict(list)
        for r in self._index("inventory/ssdd_boxes.csv", {"image_id", "x", "y", "w", "h"}):
            boxes[r["image_id"]].append(
                (float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"]))
            )
        for r in self._index(
            "inventory/ssdd_images.csv",
            {"image_id", "official_split", "md5", "n_boxes_coco", "width", "height"},
        ):
            id_ = r["image_id"]
            if (
                not re.fullmatch(r"\d{6}", id_)
                or r["official_split"] not in ("train", "test")
                or len(boxes[id_]) != int(r["n_boxes_coco"])
            ):
                raise ValueError("invalid SSDD identity or label count")
            yield Example(
                id=id_,
                product=Product.SSDD,
                split="benchmark",
                group="ssdd-unknown-parent",
                scene=None,
                presence=bool(boxes[id_]),
                annotation_source="Official SSDD BBox COCO",
                boxes=tuple(boxes[id_]),
            ), r

    def _xview_index(self) -> Iterator[tuple[Example, dict]]:
        self._pin("inventory/xview3_scenes.csv")
        scenes = {s.alias: s for s in xview_scenes(self.data).values()}
        size = self.manifest.chip_size
        for r in self._index(
            "raw/xview3/validation.csv",
            {
                "scene_id",
                "detect_id",
                "detect_lon",
                "detect_lat",
                "detect_scene_row",
                "detect_scene_column",
                "source",
                "confidence",
                "is_vessel",
                "is_fishing",
                "vessel_length_m",
                "top",
                "bottom",
                "left",
                "right",
            },
        ):
            scene = scenes.get(r["scene_id"])
            if scene is None:
                continue
            x, y = int(r["detect_scene_column"]), int(r["detect_scene_row"])
            if (
                not 0 <= x < scene.width
                or not 0 <= y < scene.height
                or size > min(scene.width, scene.height)
            ):
                raise ValueError("label or chip outside xView3 image")
            w = Window(
                col=min(max(0, x - size // 2), scene.width - size),
                row=min(max(0, y - size // 2), scene.height - size),
                width=size,
                height=size,
            )
            box: tuple[BoxXYWH, ...] = ()
            if r["top"]:
                top, bottom, left, right = (float(r[k]) for k in ("top", "bottom", "left", "right"))
                if (
                    not 0 <= left <= x <= right < scene.width
                    or not 0 <= top <= y <= bottom < scene.height
                ):
                    raise ValueError("invalid xView3 box")
                box = ((left - w.col, top - w.row, right - left + 1, bottom - top + 1),)
            presence = {"True": True, "False": False, "": None}[r["is_vessel"]]
            yield Example(
                id=r["detect_id"],
                product={
                    "manual": Product.REVIEWED,
                    "ais/manual": Product.REVIEWED,
                    "ais": Product.WEAK,
                }[r["source"]],
                split=self.manifest.split(scene.id),
                group=acquisition_group(scene.id),
                scene=scene.id,
                acquisition=scene.time,
                lonlat=(float(r["detect_lon"]), float(r["detect_lat"])),
                presence=presence,
                fishing={"True": True, "False": False, "": None}[r["is_fishing"]],
                annotation_source=r["source"],
                confidence=r["confidence"],
                boxes=box,
                window=w,
                center_xy=(x - w.col, y - w.row),
                length_m=float(r["vessel_length_m"]) if r["vessel_length_m"] else None,
            ), r

    def examples(self, split: Partition | None = None) -> Iterator[Example]:
        return (e for e in self._examples.values() if split is None or e.split == split)

    def read(self, id_: str) -> Sample:
        e = self._examples[id_]
        r = self._rows[id_]
        if self.family == "xview3":
            assert e.scene and e.window
            folder = f"raw/xview3/scenes/{r['scene_id']}/{r['scene_id']}"
            for pol in ("VV", "VH"):
                self._pin(f"{folder}/{pol}_dB.tif")
            request = RasterRequest(scene=e.scene, product="xview3-db-10m", window=e.window)
            result = self._resolver.resolve(request)
            label_origin = Origin(
                source="xview3",
                asset="validation.csv",
                product=e.product,
                revision=self.manifest.sha256["raw/xview3/validation.csv"],
            )
            return Sample(
                e,
                result.stack(),
                request.bands,
                (*(p.origin for p in result.pieces), label_origin),
                self.manifest_sha256,
            )
        try:
            if self.family == "gfw-tiles":
                path = self._pin(TILE_ZIP)
                if self._zarr is None:
                    store = ZipStore(path, mode="r")
                    self._resources.callback(store.close)
                    self._zarr = zarr.open_group(
                        store=store, path="detection_tiles_v4.zarr", mode="r"
                    )
                i = int(r["tile_index"])
                ids, labels, tiles = (self._zarr[k] for k in ("detect_id", "presence", "tiles"))
                if (
                    not isinstance(ids, zarr.Array)
                    or not isinstance(labels, zarr.Array)
                    or not isinstance(tiles, zarr.Array)
                ):
                    raise ValueError("expected Zarr arrays in the detection tiles group")
                if i < 0 or str(ids[i]) != id_ or int(np.asarray(labels[i]).item()) != e.presence:
                    raise ValueError("tile index and archive disagree")
                hwc = np.asarray(tiles[i])
                if hwc.shape != (80, 80, 2) or hwc.dtype != np.float16:
                    raise ValueError("unexpected Zarr tile")
                channels: tuple[str, ...] = ("release_channel_0", "release_channel_1")
                origin = Origin(
                    source="gfw-figshare",
                    asset=f"detection_tiles.zip#tiles/{i}",
                    product=e.product,
                    revision=self.manifest.sha256[TILE_ZIP],
                    transformations=("Zarr chunk read", "HWC to CHW"),
                )
            else:
                path = (
                    self.data
                    / "raw/ssdd/extracted/Official-SSDD-OPEN/BBox_SSDD/coco_style/images"
                    / r["official_split"]
                    / f"{id_}.jpg"
                )
                with path.open("rb") as f:
                    if hashlib.file_digest(f, "md5").hexdigest() != r["md5"]:
                        raise ValueError("JPEG differs from pinned inventory")
                    f.seek(0)
                    with Image.open(f) as image:
                        if image.mode != "RGB" or image.size != (int(r["width"]), int(r["height"])):
                            raise ValueError("JPEG differs from SSDD metadata")
                        hwc = np.asarray(image)
                channels = ("R", "G", "B")
                origin = Origin(
                    source="official-ssdd",
                    asset=f"BBox_SSDD/{r['official_split']}/{id_}.jpg",
                    product=e.product,
                    revision=f"md5:{r['md5']}",
                    transformations=("JPEG decode", "HWC to CHW"),
                )
        except (OSError, ValueError, KeyError, IndexError, BadZipFile) as exc:
            raise data_error(exc, f"{self.family} sample") from None
        return Sample(
            e, np.ma.asarray(hwc.transpose(2, 0, 1)), channels, (origin,), self.manifest_sha256
        )
