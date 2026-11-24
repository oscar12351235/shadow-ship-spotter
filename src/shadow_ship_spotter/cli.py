"""Data workflows. The default only reads the selected checkout and its pinned assets."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from .data.catalog import bounds, discover
from .data.compatibility import Product
from .data.contracts import Interval, Policy, RasterRequest, SourceError, State, Window
from .data.imagery import RasterResolver
from .data.study import StudyRequest, prepare, raster_summary
from .data.training import LABEL_PRODUCTS, TrainingSet
from .paths import DATA_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow Ship Spotter research data")
    parser.add_argument("--data", type=Path, default=DATA_DIR, help="data root")
    parser.add_argument("--config", type=Path, help="defaults to DATA/loading.toml")
    parser.add_argument(
        "--online",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="enable PC metadata and native-window reads on cache misses",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("training", help="inspect a pinned sample and the partition counts")
    train.add_argument("family", choices=("gfw-tiles", "xview3", "ssdd"))
    train.add_argument("--manifest", type=Path)
    train.add_argument(
        "--product",
        type=Product,
        choices=sorted({p for products in LABEL_PRODUCTS.values() for p in products}),
        help="annotation product (xView3 defaults to manually reviewed rows)",
    )
    train.add_argument("--split", choices=("train", "validation", "test", "benchmark"))
    train.add_argument("--id", help="choose a sample ID within the selected partition")
    cat = commands.add_parser(
        "scenes", help="list actual acquisitions intersecting the date and area"
    )
    app = commands.add_parser(
        "study", help="inspect acquisition inputs and coverage for a map request"
    )
    for cmd in (cat, app):
        cmd.add_argument("--date", required=True, type=date.fromisoformat)
        cmd.add_argument(
            "--bbox",
            nargs=4,
            type=float,
            metavar=("W", "S", "E", "N"),
            help="viewport, WGS84 longitude/latitude",
        )
        cmd.add_argument(
            "--zone",
            nargs=4,
            type=float,
            metavar=("W", "S", "E", "N"),
            help="explicit zone overrides viewport",
        )
    raster = commands.add_parser("window", help="read pixels on a named product's native grid")
    for cmd in (raster, app):
        cmd.add_argument("--scene", required=True, help="complete ESA product name")
        cmd.add_argument("--product", required=True, choices=("xview3-db-10m", "s1-grd-dn"))
    raster.add_argument(
        "--window", nargs=4, required=True, type=int, metavar=("COL", "ROW", "W", "H")
    )
    raster.add_argument("--bands", nargs="+", choices=("VV", "VH"), default=["VV", "VH"])
    raster.add_argument(
        "--pixel-only", action="store_true", help="allow unlocated native-grid crops"
    )
    a = parser.parse_args(argv)
    if a.command in ("scenes", "study") and not (a.zone or a.bbox):
        parser.error("supply --zone or --bbox")
    try:
        policy = Policy.read(a.config or a.data / "loading.toml")
        if a.online is not None:
            policy = policy.model_copy(update={"online": a.online})
        if a.command == "training":
            with TrainingSet(a.data, a.family, a.manifest, product=a.product) as ds:
                selected = next((e for e in ds.examples(a.split) if not a.id or e.id == a.id), None)
                if selected is None:
                    raise SourceError(State.EMPTY, "no sample for the selected id/partition")
                sample = ds.read(selected.id)
                out = dict(
                    state=State.COMPLETE,
                    family=a.family,
                    splits=dict(Counter(e.split for e in ds.examples())),
                    example=selected.model_dump(mode="json"),
                    shape=sample.pixels.shape,
                    valid_values=int(sample.pixels.count()),
                    dtype=str(sample.pixels.dtype),
                    channels=sample.channels,
                    manifest_sha256=sample.manifest_sha256,
                    origins=[p.model_dump(mode="json") for p in sample.origins],
                )
        elif a.command == "window":
            x, y, w, h = a.window
            req = RasterRequest(
                scene=a.scene,
                product=a.product,
                bands=tuple(a.bands),
                window=Window(col=x, row=y, width=w, height=h),
                georeferenced=not a.pixel_only,
            )
            out = raster_summary(RasterResolver.local(a.data, policy).resolve(req))
        elif a.command == "scenes":
            out = discover(
                a.data, bounds(tuple(a.zone or a.bbox)), Interval.day(a.date), online=policy.online
            ).model_dump(mode="json")
        else:
            q = StudyRequest(
                day=a.date,
                viewport=bounds(tuple(a.bbox)) if a.bbox else None,
                zone=bounds(tuple(a.zone)) if a.zone else None,
                scene=a.scene,
                product=a.product,
            )
            out = prepare(a.data, policy, q)
        print(json.dumps(out, indent=2, allow_nan=False))
        return 0 if out["state"] in (State.COMPLETE, State.EMPTY) else 1
    except SourceError as exc:
        print(json.dumps({"state": exc.state, "reason": str(exc)}), file=sys.stderr)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"Data configuration/input error: {exc}", file=sys.stderr)
    return 2
