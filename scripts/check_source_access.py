"""Opt-in, read-only access checks. No vessel queries, large downloads or signed URLs in output."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlencode

from shadow_ship_spotter.config import describe_env
from shadow_ship_spotter.data.catalog import COLLECTION, STAC, pc_scene
from shadow_ship_spotter.data.contracts import SourceError
from shadow_ship_spotter.data.http import get_json
from shadow_ship_spotter.data.lseg import discover_proxy

ARCHIVED_SCENE = "S1B_IW_GRDH_1SDV_20190318T104813_20190318T104842_015408_01CDA6_F3BE"


def main() -> None:
    report: dict = {"checked_at": datetime.now(UTC).isoformat()}
    for rec, article, name in (
        ("tiles", 24309469, "detection_tiles.zip"),
        ("analysis", 24309475, "industrial_vessels_v20240102.csv.zip"),
    ):
        try:
            meta = get_json(f"https://api.figshare.com/v2/articles/{article}")
            files = [
                {k: f[k] for k in ("id", "name", "size", "computed_md5")}
                for f in meta["files"]
                if f["name"] == name
            ]
            report[f"figshare_{rec}"] = dict(version=meta["version"], files=files)
        except SourceError as exc:
            report[f"figshare_{rec}"] = dict(state=exc.state, reason=str(exc))
    try:
        item = get_json(f"{STAC}/collections/{COLLECTION}/items/{ARCHIVED_SCENE.rsplit('_',1)[0]}")
        scene, _ = pc_scene(item)
        report["pc"] = dict(
            exact_asset_parent=scene.id == ARCHIVED_SCENE,
            polarisations=item["properties"]["sar:polarizations"],
        )
    except SourceError as exc:
        report["pc"] = dict(state=exc.state, reason=str(exc))
    try:
        query = urlencode(
            {
                "$filter": f"Name eq '{ARCHIVED_SCENE}.SAFE'",
                "$select": "Name,ContentDate",
                "$top": 2,
            }
        )
        meta = get_json(f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?{query}")
        report["cdse"] = dict(exact_safe_records=len(meta["value"]), scope="catalogue only")
    except SourceError as exc:
        report["cdse"] = dict(state=exc.state, reason=str(exc))
    status = discover_proxy()
    report["workspace"] = dict(
        reachable=status["reachable"],
        ready=status.get("ready", False),
        credential_names_present=describe_env(
            ["EIKON_APP_KEY", "VESSEL_TRACKING_API_KEY", "GFW_API_TOKEN", "CDSE_CLIENT_ID"]
        ),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
