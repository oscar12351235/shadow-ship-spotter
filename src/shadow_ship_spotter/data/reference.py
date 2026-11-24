"""Predicate-pushed reads of the published GFW SCS subset; the result is a prediction layer."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from zipfile import BadZipFile, ZipFile

import pandas as pd
import polars as pl
from pydantic import Field

from .catalog import discover
from .contracts import (
    Bounds,
    Interval,
    Model,
    Origin,
    SceneID,
    SourceError,
    State,
    Utc,
    data_error,
    sensing_interval,
)
from .download import file_hash, snapshot_sha256
from .storage import staged_file

SCS = Bounds(west=105, south=0, east=122, north=25)
ARCHIVE_MD5 = "a98f09e156b2cbb6dfb4887bd7efc0de"
LEGACY_SHA256 = "bbd02b2203c67f04c342e647e28f88337c819e192813e6828ee18bcc7173c540"
LINEAGE = {
    "sss.source": f"figshare/24309475/43882980/md5/{ARCHIVE_MD5}",
    "sss.processing": "scs-clip-wgs84-v1",
    "sss.bounds": "105,0,122,25",
}
# These two legacy identifier extracts were compared, row for row, with the pinned global ZIP.
HAINAN_SCENE = "S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE"
NORTH_SEA_SCENE = "S1A_IW_GRDH_1SDV_20200928T171800_20200928T171831_034562_0405EA_F164"
LEGACY_SCENES = {
    HAINAN_SCENE: "9658eeafa415d4170349a137394084ba98bdabcd99fe95d13979cff456f95755",
    NORTH_SEA_SCENE: "c8009cb76d8a59ff186db7de89f812e7a2672b1f2b7490cbc5d57f0f303397f2",
}
LOOKUP_FIELDS = ["scene_id", "timestamp", "lat", "lon", "mmsi", "matched_category", "length_m"]


def scan_reference(path: Path) -> pl.LazyFrame:
    """Accept the pinned historical file or a derivative with the verified release receipt."""
    meta = pl.read_parquet_metadata(path)
    if any(k.startswith("sss.") for k in meta):
        if any(meta.get(k) != v for k, v in LINEAGE.items()):
            raise ValueError("incompatible reference lineage")
    elif snapshot_sha256(path) != LEGACY_SHA256:
        raise ValueError("unversioned reference parquet; rebuild from the pinned archive")
    return pl.scan_parquet(path)


def write_reference(path: Path, frame: pl.DataFrame, verified_md5: str) -> None:
    if verified_md5 != ARCHIVE_MD5:
        raise ValueError("unsupported GFW analysis release")
    with staged_file(path) as stage:
        frame.write_parquet(stage, metadata=LINEAGE)


def published_scene_for_lookup(data: Path, scene: str) -> pl.DataFrame:
    """Published predictions for a whole acquisition, used to select lookup candidates."""
    interval = sensing_interval(scene)
    try:
        return _read_lookup(data, scene, interval)
    except (OSError, ValueError, BadZipFile, pl.exceptions.PolarsError) as exc:
        raise data_error(exc, "published GFW scene extract") from None


def _read_lookup(data: Path, scene: str, interval: Interval) -> pl.DataFrame:
    folder = data / "processed/gfw_scenes"
    legacy = folder / f"{scene}.parquet"
    cache = folder / "lookup-v1" / f"{scene}.parquet"
    receipt = {
        "sss.source": LINEAGE["sss.source"],
        "sss.processing": "scene-lookup-v1",
        "sss.scene": scene,
    }
    if cache.is_file():
        metadata = pl.read_parquet_metadata(cache)
        if any(metadata.get(k) != v for k, v in receipt.items()):
            raise SourceError(State.CORRUPT, "published scene cache lineage mismatch")
        return pl.read_parquet(cache, columns=LOOKUP_FIELDS)
    if scene in LEGACY_SCENES and legacy.is_file() and file_hash(legacy) == LEGACY_SCENES[scene]:
        return pl.read_parquet(legacy, columns=LOOKUP_FIELDS)
    scs = data / "processed/gfw_sar_detections_scs.parquet"
    contained = any(
        s.scene.id == scene and s.intersection_bounds == s.scene.bounds
        for s in discover(data, SCS, interval).hits
    )
    if contained and scs.is_file():
        frame = (
            scan_reference(scs).filter(pl.col("scene_id") == scene).select(LOOKUP_FIELDS).collect()
        )
    else:
        archive = data / "raw/gfw_paolo2024/analysis/industrial_vessels_v20240102.csv.zip"
        if not archive.is_file():
            raise SourceError(State.UNAVAILABLE, "no verified whole-scene GFW input")
        if file_hash(archive, "md5") != ARCHIVE_MD5:
            raise SourceError(State.CORRUPT, "GFW analysis archive checksum mismatch")
        with ZipFile(archive) as zf:
            csvs = [f for f in zf.namelist() if f.endswith(".csv")]
            if len(csvs) != 1:
                raise SourceError(State.CORRUPT, "expected one GFW analysis CSV")
            with zf.open(csvs[0]) as fh:
                chunks = pd.read_csv(fh, chunksize=250_000, usecols=LOOKUP_FIELDS)
                rows = pd.concat(
                    (chunk.loc[chunk.scene_id == scene] for chunk in chunks), ignore_index=True
                )
        rows["timestamp"] = pd.to_datetime(rows.timestamp, utc=True, format="mixed")
        frame = pl.from_pandas(rows).select(LOOKUP_FIELDS)
    with staged_file(cache) as stage:
        frame.write_parquet(stage, metadata=receipt)
    return frame


class Prediction(Model):
    scene_id: SceneID
    timestamp: Utc
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    matched_category: Literal[
        "matched_fishing", "matched_nonfishing", "matched_unknown", "unmatched"
    ]
    matching_score: float | None
    fishing_score: float | None
    length_m: float | None


class References(Model):
    state: State
    area: Bounds
    covered: Bounds | None
    origin: Origin
    predictions: tuple[Prediction, ...] = ()
    reason: str


def load_reference(data: Path, scene: str, area: Bounds) -> References:
    interval = sensing_interval(scene)
    path = data / "processed/gfw_sar_detections_scs.parquet"
    origin = Origin(
        source="gfw-paolo2024",
        asset=path.name,
        product="gfw-published-prediction",
        revision="industrial_vessels_v20240102.csv.zip:md5:a98f09e156b2cbb6dfb4887bd7efc0de",
        transformations=("published rows clipped to SCS box", "scene and AOI filter"),
    )
    x, y, x2, y2 = (
        max(area.west, SCS.west),
        max(area.south, SCS.south),
        min(area.east, SCS.east),
        min(area.north, SCS.north),
    )
    if x >= x2 or y >= y2 or not 2017 <= interval.start.year <= 2021:
        return References(
            state=State.UNAVAILABLE,
            area=area,
            covered=None,
            origin=origin,
            reason="outside the local derivative's region or release years",
        )
    if not path.is_file():
        return References(
            state=State.UNAVAILABLE,
            area=area,
            covered=None,
            origin=origin,
            reason="missing SCS parquet",
        )
    covered = Bounds(west=x, south=y, east=x2, north=y2)
    try:
        frame = (
            scan_reference(path)
            .filter(
                (pl.col("scene_id") == scene)
                & pl.col("lon").is_between(x, x2)
                & pl.col("lat").is_between(y, y2)
            )
            .select(list(Prediction.model_fields))
            .collect()
        )
        dtype = frame.schema["timestamp"]
        if not isinstance(dtype, pl.Datetime) or dtype.time_zone != "UTC":
            raise ValueError("expected timezone-aware UTC predictions")
        rows = tuple(Prediction.model_validate(r) for r in frame.iter_rows(named=True))
        if any(not interval.start <= p.timestamp <= interval.end for p in rows):
            raise ValueError("prediction time disagrees with acquisition")
    except (OSError, pl.exceptions.PolarsError, ValueError) as exc:
        return References(
            state=data_error(exc, "published GFW predictions").state,
            area=area,
            covered=None,
            origin=origin,
            reason="invalid prediction schema, time, or parquet",
        )
    state = State.PARTIAL if covered != area else State.COMPLETE if rows else State.EMPTY
    return References(
        state=state,
        area=area,
        covered=covered,
        origin=origin,
        predictions=rows,
        reason="published GFW detections and GFW matching; study sampling applies",
    )
