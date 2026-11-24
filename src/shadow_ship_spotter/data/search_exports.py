"""Private Workspace Search exports. Identifier candidates carry their snapshot vintage."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Annotated

from pydantic import Field, TypeAdapter

from .catalog import read_item
from .compatibility import Product
from .contracts import Model, Origin, SceneID, SourceError, State, Utc, data_error
from .observations import Fix, Observation, PositionRequest, reconcile, scene_export_path


class SearchExportRequest(Model):
    run: Annotated[str, Field(pattern=r"^probe_[0-9]{8}T[0-9]{6}Z$")]
    # Omit for the Search area snapshot, supply for that historical probe's lookup candidates.
    lookup_scene: SceneID | None = None
    positions: PositionRequest


class IdentityCandidate(Model):
    ric: str
    name: str | None
    mmsi_as_supplied: str | None
    mmsi: str | None
    imo_as_supplied: str | None
    asset_type: str | None
    origin: Origin


class SearchExport(Model):
    identities: tuple[IdentityCandidate, ...]
    positions: tuple[Observation, ...]
    query_state: State
    limitation: str = (
        "Identities describe the search run. Position rows are selected by their "
        "individual report times. Regional reception and historical identity are unknown."
    )


def read_search_export(data: Path, q: SearchExportRequest) -> SearchExport:
    folder = data / "raw/lseg" / q.run
    receipt = read_item(folder / "assessment.json")
    identities = []
    fixes = []
    capped = False
    try:
        stamp = TypeAdapter(Utc).validate_python(receipt["run_utc"])
        if stamp.strftime("probe_%Y%m%dT%H%M%SZ") != q.run:
            raise ValueError("run timestamp differs from selected export")
        if q.lookup_scene:
            if q.lookup_scene not in receipt.get("scenes", {}):
                raise SourceError(State.UNAVAILABLE, "no identifier lookup for this scene")
            path = scene_export_path(folder, "resolved", q.lookup_scene, receipt["scenes"])
        else:
            path = folder / "area_snapshot_latest.csv"
        with path.open(encoding="utf-8", newline="") as f:
            rows = csv.DictReader(f)
            if not {
                "RIC",
                "MMSI",
                "IMO",
                "AssetName",
                "RCSAssetTypeLeaf",
                "LocationTimestamp",
                "Longitude",
                "Latitude",
            }.issubset(rows.fieldnames or ()):
                raise ValueError("invalid Workspace Search schema")
            for i, row in enumerate(rows, 1):
                origin = Origin(
                    source="lseg-workspace-search",
                    asset=f"{q.run}/{path.name}#row={i}",
                    revision=q.run,
                    product=Product.REGISTRY,
                    run_started_at=stamp,
                )
                m = row["MMSI"]
                identities.append(
                    IdentityCandidate(
                        ric=row["RIC"],
                        name=row["AssetName"] or None,
                        mmsi_as_supplied=m or None,
                        mmsi=m if m.isascii() and m.isdigit() and len(m) == 9 else None,
                        imo_as_supplied=row["IMO"] or None,
                        asset_type=row["RCSAssetTypeLeaf"] or None,
                        origin=origin,
                    )
                )
                if all(row[k] for k in ("LocationTimestamp", "Latitude", "Longitude")):
                    fix = Fix.model_validate(
                        dict(
                            namespace="lseg:ric",
                            identifier=row["RIC"],
                            observed_at=row["LocationTimestamp"],
                            lon=row["Longitude"],
                            lat=row["Latitude"],
                        )
                    )
                    if (
                        (fix.lat, fix.lon) != (0, 0)
                        and q.positions.time.start <= fix.observed_at < q.positions.time.end
                        and q.positions.area.contains(fix.lon, fix.lat)
                    ):
                        fixes.append((fix, origin.model_copy(update={"product": Product.REPORTED})))
        if not q.lookup_scene:
            snapshot = receipt["area_snapshot"]
            if len(identities) != snapshot["rows_returned"]:
                raise ValueError("incomplete area snapshot export")
            total = snapshot.get("total_latest_in_bbox")
            if total is not None:
                if total < len(identities):
                    raise ValueError("area total smaller than export")
                capped = total > len(identities)
    except (OSError, KeyError, ValueError, TypeError, csv.Error) as exc:
        raise data_error(exc, "Workspace Search export") from None
    return SearchExport(
        identities=tuple(identities),
        positions=reconcile(fixes),
        query_state=State.PARTIAL if capped else State.COMPLETE if fixes else State.EMPTY,
    )
