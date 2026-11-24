from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest
import rasterio
from pydantic import ValidationError
from rasterio.transform import from_origin

from shadow_ship_spotter.cli import main
from shadow_ship_spotter.data import catalog
from shadow_ship_spotter.data.catalog import discover, pc_scene
from shadow_ship_spotter.data.compatibility import Product
from shadow_ship_spotter.data.contracts import Bounds, Interval, Origin, Policy, SourceError, State
from shadow_ship_spotter.data.observations import Fix, PositionRequest, load_positions, reconcile
from shadow_ship_spotter.data.reference import (
    ARCHIVE_MD5,
    SCS,
    load_reference,
    published_scene_for_lookup,
    write_reference,
)
from shadow_ship_spotter.data.search_exports import SearchExportRequest, read_search_export
from shadow_ship_spotter.data.study import StudyRequest, prepare
from shadow_ship_spotter.data.training import TrainingSet

SID = "S1A_IW_GRDH_1SDV_20200126T052956_20200126T053025_030967_038E50_B43E"
ALIAS = "b1844cde847a3942v"
RUN = "probe_20260102T000000Z"
T = "2020-01-26T05:30:05Z"
BOX = Bounds(west=2.999, south=0.001, east=3.003, north=0.006)
POLICY = Policy(version=1, raster_priority=("xview3",), lseg_runs=(RUN,))


def table(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


def xview(data):
    table(
        data / "inventory/xview3_scenes.csv",
        [
            dict(
                esa_scene_name=SID,
                scene_id=ALIAS,
                crs="EPSG:32631",
                width=100,
                height=100,
                lon_min=3,
                lat_min=0,
                lon_max=3.00899,
                lat_max=0.00905,
                acquisition_start_utc="2020-01-26T05:29:56Z",
                acquisition_stop_utc="2020-01-26T05:30:25Z",
            )
        ],
    )
    folder = data / "raw/xview3/scenes" / ALIAS / ALIAS
    folder.mkdir(parents=True)
    for band in ("VV", "VH"):
        with rasterio.open(
            folder / f"{band}_dB.tif",
            "w",
            driver="GTiff",
            width=100,
            height=100,
            count=1,
            dtype="float16",
            crs="EPSG:32631",
            transform=from_origin(500000, 1000, 10, 10),
            nodata=-32768,
        ) as f:
            f.write(np.full((100, 100), -15, dtype="float16"), 1)


def export(data, *, run=RUN, errors=(), count=1):
    folder = data / "raw/lseg" / run
    folder.mkdir(parents=True)
    history = dict(
        requested_day_interval_utc=["2020-01-26T00:00:00Z", "2020-01-26T23:59:59Z"],
        n_rics_requested=1,
        request_errors=list(errors),
        cell_errors=[],
        validation_vs_requested_days={"n_positions": count},
    )
    stamp = datetime.strptime(run, "probe_%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat()
    (folder / "assessment.json").write_text(
        json.dumps(dict(run_utc=stamp, scenes={SID: {"history": history}}))
    )
    p = folder / f"history_{SID[:32]}.csv"
    if count:
        table(
            p,
            [
                dict(
                    ric="C}TEST",
                    time_utc=T,
                    lon=3.001,
                    lat=0.003,
                    speed_kn="",
                    course_deg="360",
                    heading_deg="511",
                    nav_status="",
                    position_kind="reported",
                )
            ],
        )
    return p


def position_query():
    return PositionRequest(area=BOX, time=Interval.day(date(2020, 1, 26)))


def test_offline_reports_query_vs_population_and_duplicates(tmp_path, monkeypatch):
    monkeypatch.delenv("EIKON_APP_KEY", raising=False)
    export(tmp_path)
    export(tmp_path, run="probe_20260103T000000Z")
    policy = POLICY.model_copy(update={"lseg_runs": (RUN, "probe_20260103T000000Z")})
    result = load_positions(tmp_path, policy, position_query())
    assert result.state == State.COMPLETE and result.population_coverage == "unknown"
    assert len(result.observations) == 1
    obs = result.observations[0]
    assert len(obs.origins) == 2 and not obs.conflict and obs.fix.heading_deg is None
    assert obs.origins[0].run_started_at > obs.fix.observed_at
    assert obs.origins[0].retrieved_at is None
    elsewhere = position_query().model_copy(update={"area": SCS})
    assert load_positions(tmp_path, policy, elsewhere).state == State.EMPTY
    other_day = position_query().model_copy(update={"time": Interval.day(date(2020, 1, 27))})
    assert load_positions(tmp_path, policy, other_day).state == State.UNAVAILABLE
    missing = policy.model_copy(update={"lseg_runs": (*policy.lseg_runs, "probe_20260104T000000Z")})
    assert load_positions(tmp_path, missing, position_query()).state == State.PARTIAL


def test_conflicting_fixes_keep_observations_and_origin():
    a = Fix.model_validate(
        dict(namespace="ais:mmsi", identifier="012345678", observed_at=T, lon=10, lat=5)
    )
    first = Origin(source="a", asset="export1", product="provider-reported-position", revision="1")
    second = first.model_copy(update={"source": "b"})
    result = reconcile([(a, first), (a, second), (a.model_copy(update={"lon": 12.0}), second)])
    assert [len(o.origins) for o in result] == [2, 1]
    assert all(o.conflict for o in result)
    assert {o.fix.lon for o in result} == {10, 12}
    with pytest.raises(ValidationError):
        Fix.model_validate(dict(a.model_dump(), identifier="123"))
    with pytest.raises(SourceError):
        reconcile([(a, first.model_copy(update={"product": "gfw-published-prediction"}))])


def test_search_identity_candidates_and_report_times_are_separate(tmp_path):
    p = export(tmp_path)
    snap = p.parent / "area_snapshot_latest.csv"
    fmt = dict(
        RIC="C}TEST",
        MMSI="12345",
        IMO="",
        AssetName="fixture",
        RCSAssetTypeLeaf="Other",
        LocationTimestamp=T,
        Longitude=3.001,
        Latitude=0.003,
    )
    table(snap, [fmt, dict(fmt, RIC="C}ALT", MMSI="012345678")])
    receipt = p.parent / "assessment.json"
    receipt.write_text(
        json.dumps(json.loads(receipt.read_text()) | {"area_snapshot": {"rows_returned": 2}})
    )
    q = SearchExportRequest(run=RUN, positions=position_query())
    snap_rows = read_search_export(tmp_path, q)
    assert (
        snap_rows.identities[0].mmsi is None and snap_rows.identities[0].mmsi_as_supplied == "12345"
    )
    assert snap_rows.identities[1].mmsi == "012345678" and len(snap_rows.positions) == 2
    later = PositionRequest(area=BOX, time=Interval.day(date(2026, 1, 2)))
    assert not read_search_export(tmp_path, q.model_copy(update={"positions": later})).positions
    capped = json.loads(receipt.read_text())
    capped["area_snapshot"]["total_latest_in_bbox"] = 4
    receipt.write_text(json.dumps(capped))
    assert read_search_export(tmp_path, q).query_state == State.PARTIAL


@pytest.mark.parametrize(
    "changes",
    [
        {"lat": "91"},
        {"lon": "inf"},
        {"time_utc": "2020-01-26 05:30:05"},
        {"position_kind": "interpolated_by_probe"},
        {"time_utc": "2019-01-01T00:00:00Z"},
    ],
)
def test_bad_export_is_corrupt_not_empty(tmp_path, changes):
    p = export(tmp_path)
    with p.open() as f:
        row = next(csv.DictReader(f))
    table(p, [row | changes])
    assert load_positions(tmp_path, POLICY, position_query()).state == State.CORRUPT


def test_auth_empty_and_unavailable_are_distinct(tmp_path):
    q = position_query()
    assert load_positions(tmp_path, POLICY, q).state == State.UNAVAILABLE
    export(tmp_path, errors=[{"class": "entitlement_denied"}], count=0)
    assert load_positions(tmp_path, POLICY, q).state == State.ACCESS
    export(tmp_path, run="probe_20260103T000000Z", count=0)
    policy = POLICY.model_copy(update={"lseg_runs": ("probe_20260103T000000Z",)})
    assert load_positions(tmp_path, policy, q).state == State.EMPTY


def test_ambiguous_legacy_export_requires_full_scene_names(tmp_path):
    old = export(tmp_path)
    path = old.parent / "assessment.json"
    receipt = json.loads(path.read_bytes())
    alt = SID[:-4] + "FFFF"
    receipt["scenes"][alt] = receipt["scenes"][SID]
    path.write_text(json.dumps(receipt))
    assert load_positions(tmp_path, POLICY, position_query()).state == State.INCOMPATIBLE
    for sid in (SID, alt):
        (old.parent / f"history_{sid}.csv").write_bytes(old.read_bytes())
    result = load_positions(tmp_path, POLICY, position_query())
    assert result.state == State.COMPLETE and len(result.observations) == 1
    assert len(result.observations[0].origins) == 2


def test_application_date_zone_and_required_status(tmp_path, monkeypatch):
    xview(tmp_path)
    monkeypatch.setattr(catalog, "get_json", lambda *a: pytest.fail("unexpected network request"))
    inside = BOX.model_copy(update={"west": 3.0001})
    q = StudyRequest(
        day=date(2020, 1, 26), viewport=SCS, zone=inside, scene=SID, product="xview3-db-10m"
    )
    result = prepare(tmp_path, POLICY, q)
    assert result["inputs_ready"] and result["effective_area"] == inside.model_dump()
    assert result["imagery"]["state"] == State.COMPLETE
    assert result["positions"]["state"] == State.UNAVAILABLE
    assert result["positions"]["reported_variants"] is None
    assert result["reference"]["published_rows"] is None
    assert result["matching"] == "insufficient_ais_information" and result["model"] == "not_run"
    assert not prepare(
        tmp_path, POLICY.model_copy(update={"required_layers": ("imagery", "positions")}), q
    )["inputs_ready"]
    assert not prepare(tmp_path, POLICY, q.model_copy(update={"day": date(2020, 1, 25)}))[
        "inputs_ready"
    ]
    assert not prepare(tmp_path, POLICY, q.model_copy(update={"zone": None}))["inputs_ready"]
    wrong_product = prepare(tmp_path, POLICY, q.model_copy(update={"product": "s1-grd-dn"}))
    assert wrong_product["state"] == State.INCOMPATIBLE and not wrong_product["inputs_ready"]
    edge = prepare(tmp_path, POLICY, q.model_copy(update={"zone": BOX}))
    assert edge["state"] == edge["footprint_state"] == State.PARTIAL and not edge["inputs_ready"]
    assert edge["preview_state"] == State.COMPLETE


def pc_item():
    short = SID.rsplit("_", 1)[0]
    p = {
        "sar:product_type": "GRD",
        "sar:polarizations": ["VV"],
        "sar:instrument_mode": "IW",
        "s1:shape": [100, 100],
        "start_datetime": "2020-01-26T05:29:56.15Z",
        "end_datetime": "2020-01-26T05:30:25.2Z",
    }
    return {
        "id": short,
        "collection": "sentinel-1-grd",
        "properties": p,
        "geometry": {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [1, 2], [1, 1]]]},
        "assets": {
            "vv": {"href": f"https://{catalog.ASSET_HOST}/s1-grd/{SID}/measurement/iw-vv.tiff"}
        },
    }


def test_actual_footprint_and_pagination_failure(tmp_path, monkeypatch):
    xview(tmp_path)
    outside = Bounds(west=1.7, east=1.9, south=1.7, north=1.9)
    t = Interval.day(date(2020, 1, 26))
    page = {
        "features": [pc_item()],
        "links": [{"rel": "next", "href": catalog.STAC + "/search?token=next"}],
    }

    def get(url):
        if "token=next" in url:
            raise SourceError(State.ACCESS, "HTTP 403")
        return page

    monkeypatch.setattr(catalog, "get_json", get)
    assert discover(tmp_path, outside, t, online=True).state == State.ACCESS
    area = Bounds(west=1, east=2, south=1, north=2)
    result = discover(tmp_path, area, t, online=True)
    assert result.state == State.PARTIAL and len(result.hits) == 1 and not result.hits[0].covers_aoi
    monkeypatch.setattr(catalog, "get_json", lambda url: dict(features=[], links=[]))
    assert discover(tmp_path, area, t, online=True).state == State.EMPTY


def test_catalogue_id_time_coordinate_and_band_validation():
    item = pc_item()
    scene, _ = pc_scene(item)
    assert scene.time.start.microsecond == 150000 and scene.id == SID
    item["properties"]["start_datetime"] = "2020-01-27T00:00:00Z"
    with pytest.raises(SourceError):
        pc_scene(item)
    item = pc_item()
    item["assets"]["vv"]["href"] = item["assets"]["vv"]["href"].replace("iw-vv", "iw-vh")
    with pytest.raises(SourceError):
        pc_scene(item)
    for v in (
        dict(west=170, east=-170, south=1, north=2),
        dict(west=1, east=2, south=-92, north=1),
    ):
        with pytest.raises(ValidationError):
            Bounds(**v)


def test_real_tiff_crop_native_grid_only_and_full_parent_check(tmp_path):
    from rasterio.errors import NotGeoreferencedWarning

    from shadow_ship_spotter.data.contracts import RasterRequest, Window
    from shadow_ship_spotter.data.download import file_hash
    from shadow_ship_spotter.data.imagery import RasterResolver

    item = pc_item()
    folder = tmp_path / "raw/planetary_computer" / item["id"]
    folder.mkdir(parents=True)
    (folder / "item.json").write_text(json.dumps(item))
    stored = [10, 12, 4, 3]
    (folder / "window_meta.json").write_text(
        json.dumps({"vv": {"window": stored, "dtype": "uint16", "shape": [100, 100]}})
    )
    with (
        pytest.warns(NotGeoreferencedWarning),
        rasterio.open(
            folder / "window_vv.tif",
            "w",
            driver="GTiff",
            width=4,
            height=3,
            count=1,
            dtype="uint16",
        ) as f,
    ):
        f.write(np.arange(12, dtype="uint16").reshape(3, 4), 1)
        f.update_tags(source=item["id"], window=json.dumps(stored))
    pin = file_hash(folder / "window_vv.tif")
    (tmp_path / "sources.json").write_text(
        json.dumps({"planetary_computer_s1_grd": {"legacy_native_crop_sha256": {SID: {"VV": pin}}}})
    )
    resolver = RasterResolver.local(tmp_path, Policy(version=1, raster_priority=("pc-crop",)))
    q = RasterRequest(
        scene=SID,
        product="s1-grd-dn",
        window=Window(col=10, row=12, width=2, height=2),
        georeferenced=False,
        bands=("VV",),
    )
    assert resolver.resolve(q).stack().tolist() == [[[None, 1], [4, 5]]]
    assert resolver.locate(SID, "s1-grd-dn").state == State.INCOMPATIBLE
    assert (
        resolver.resolve(q.model_copy(update={"georeferenced": True})).state == State.INCOMPATIBLE
    )
    assert (
        resolver.resolve(q.model_copy(update={"scene": SID[:-4] + "FFFF"})).state
        == State.INCOMPATIBLE
    )
    (folder / "window_vv.tif").write_bytes(b"wrong band")
    assert resolver.resolve(q).state == State.CORRUPT


def test_whole_scene_lookup_requires_coverage_and_replays_verified_derivative(tmp_path):
    folder = tmp_path / "processed"
    folder.mkdir()
    path = folder / "gfw_sar_detections_scs.parquet"
    rows = pl.DataFrame(
        [
            dict(
                scene_id=SID,
                timestamp=datetime.fromisoformat(T),
                lon=110.5,
                lat=1.4,
                mmsi=None,
                matched_category="unmatched",
                length_m=16,
            )
        ]
    )
    write_reference(path, rows, ARCHIVE_MD5)
    with pytest.raises(SourceError) as err:
        published_scene_for_lookup(tmp_path, SID)
    assert err.value.state == State.UNAVAILABLE
    item = pc_item()
    item["geometry"]["coordinates"] = [[[110, 1], [112, 1], [110, 2], [110, 1]]]
    loc = tmp_path / "raw/planetary_computer" / item["id"]
    loc.mkdir(parents=True)
    (loc / "item.json").write_text(json.dumps(item))
    assert published_scene_for_lookup(tmp_path, SID)["length_m"].to_list() == [16]
    path.unlink()
    assert published_scene_for_lookup(tmp_path, SID).height == 1
    cache = folder / "gfw_scenes/lookup-v1" / f"{SID}.parquet"
    cache.write_bytes(b"corrupt")
    with pytest.raises(SourceError) as err:
        published_scene_for_lookup(tmp_path, SID)
    assert err.value.state == State.CORRUPT


def test_nodata_preview_does_not_become_zero_vessels(tmp_path):
    xview(tmp_path)
    path = tmp_path / "raw/xview3/scenes" / ALIAS / ALIAS / "VH_dB.tif"
    with rasterio.open(path, "r+") as f:
        f.write(np.full((100, 100), -32768, dtype="float16"), 1)
    result = prepare(
        tmp_path,
        POLICY,
        StudyRequest(day=date(2020, 1, 26), zone=BOX, scene=SID, product="xview3-db-10m"),
    )
    assert result["imagery"]["state"] == State.COMPLETE and result["preview_state"] == State.EMPTY
    assert result["joint_valid_preview_pixels"] == 0 and not result["inputs_ready"]


def test_reference_is_filtered_and_reports_partial_empty_corrupt(tmp_path):
    folder = tmp_path / "processed"
    folder.mkdir()
    path = folder / "gfw_sar_detections_scs.parquet"
    t = datetime(2020, 1, 26, 5, 30, 5, tzinfo=UTC)
    rows = [
        dict(
            scene_id=SID,
            timestamp=t,
            lat=5.0,
            lon=110.0,
            matched_category="unmatched",
            matching_score=None,
            fishing_score=None,
            length_m=57.0,
        )
    ]
    pl.DataFrame(rows).write_parquet(path)
    assert load_reference(tmp_path, SID, SCS).state == State.CORRUPT
    write_reference(path, pl.DataFrame(rows), ARCHIVE_MD5)
    r = load_reference(tmp_path, SID, SCS)
    assert (
        r.state == State.COMPLETE
        and len(r.predictions) == 1
        and r.origin.product == "gfw-published-prediction"
    )
    assert (
        load_reference(tmp_path, SID, Bounds(west=104, east=111, south=1, north=10)).state
        == State.PARTIAL
    )
    assert (
        load_reference(tmp_path, SID, Bounds(west=112, east=113, south=1, north=3)).state
        == State.EMPTY
    )
    assert load_reference(tmp_path, SID, BOX).state == State.UNAVAILABLE
    write_reference(
        path, pl.DataFrame([dict(rows[0], timestamp=t.replace(year=2019))]), ARCHIVE_MD5
    )
    assert load_reference(tmp_path, SID, SCS).state == State.CORRUPT


def test_cli_and_pinned_training_use_the_same_pixels(tmp_path: Path, capsys):
    import hashlib

    from shadow_ship_spotter.data.contracts import acquisition_group
    from shadow_ship_spotter.data.download import file_hash

    xview(tmp_path)
    labels = tmp_path / "raw/xview3/validation.csv"
    table(
        labels,
        [
            dict(
                scene_id=ALIAS,
                detect_id="fixture",
                detect_lon=3.0045,
                detect_lat=0.0054,
                detect_scene_row=40,
                detect_scene_column=50,
                source="manual",
                confidence="HIGH",
                is_vessel="True",
                is_fishing="",
                top=38,
                bottom=42,
                left=47,
                right=53,
                vessel_length_m=22,
            )
        ],
    )
    with labels.open() as f:
        reviewed = next(csv.DictReader(f))
    weak = dict(reviewed, detect_id="weak", source="ais", is_fishing="", is_vessel="")
    table(labels, [reviewed, weak])
    lock = dict(
        version=1,
        chip_size=8,
        seed="sample",
        scene_assignments={acquisition_group(SID): "test"},
        sha256={
            p.relative_to(tmp_path).as_posix(): file_hash(p)
            for p in tmp_path.rglob("*")
            if p.is_file()
        },
    )
    manifest = tmp_path / "splits/training-v1.json"
    manifest.parent.mkdir()
    manifest.write_text(json.dumps(lock))
    (tmp_path / "loading.toml").write_text('version=1\nraster_priority=["xview3"]\n')
    assert main(["--data", str(tmp_path), "training", "xview3", "--split", "test"]) == 0
    result = json.loads(capsys.readouterr().out)
    with TrainingSet(tmp_path, "xview3") as ds:
        s = ds.read("fixture")
        assert result["shape"] == list(s.pixels.shape) == [2, 8, 8] and np.all(s.pixels == -15)
        assert result["manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
        assert ds.manifest.split(SID[:-4] + "FFFF") == s.example.split == "test"
        assert s.example.boxes == ((1, 2, 7, 5),)
        assert s.example.lonlat == (3.0045, 0.0054)
        assert [e.id for e in ds.examples()] == ["fixture"]
    with TrainingSet(tmp_path, "xview3", product=Product.WEAK) as ds:
        assert [e.id for e in ds.examples("test")] == ["weak"]
        assert ds.read("weak").example.presence is None
    with pytest.raises(SourceError, match="cannot supply"):
        TrainingSet(tmp_path, "ssdd", product=Product.REVIEWED)
    labels.write_text(labels.read_text() + "\n")
    with pytest.raises(SourceError, match="SHA-256 mismatch"):
        TrainingSet(tmp_path, "xview3")


def test_pinned_ssdd_jpeg_and_gfw_zarr_samples(tmp_path):
    import hashlib

    import zarr
    from PIL import Image
    from zarr.storage import ZipStore

    from shadow_ship_spotter.data.download import file_hash
    from shadow_ship_spotter.data.training import TILE_ZIP

    inv = tmp_path / "inventory"
    jpg = (
        tmp_path
        / "raw/ssdd/extracted/Official-SSDD-OPEN/BBox_SSDD/coco_style/images/train/000001.jpg"
    )
    jpg.parent.mkdir(parents=True)
    Image.new("RGB", (6, 4), (77, 77, 77)).save(jpg)
    table(inv / "ssdd_boxes.csv", [dict(image_id="000001", x=1, y=0, w=3, h=2)])
    table(
        inv / "ssdd_images.csv",
        [
            dict(
                image_id="000001",
                official_split="train",
                md5=hashlib.md5(jpg.read_bytes()).hexdigest(),
                n_boxes_coco=1,
                width=6,
                height=4,
            )
        ],
    )
    tile_id = f"{SID};110.0;1.5"
    table(
        inv / "gfw_detection_tiles.csv",
        [
            dict(
                tile_index=0,
                detect_id=tile_id,
                scene_id=SID,
                presence=0,
                weight=1,
                length_m=0,
                lon=110.0,
                lat=1.5,
            )
        ],
    )
    archive = tmp_path / TILE_ZIP
    archive.parent.mkdir(parents=True)
    with ZipStore(archive, mode="w") as store:
        group = zarr.open_group(store, path="detection_tiles_v4.zarr", mode="w", zarr_format=2)
        group.create_array("detect_id", data=np.array([tile_id]))
        group.create_array("presence", data=np.array([0]))
        group.create_array("tiles", data=np.ones((1, 80, 80, 2), dtype="float16"))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            dict(
                version=1,
                chip_size=80,
                seed="fixture",
                scene_assignments={},
                sha256={
                    p.relative_to(tmp_path).as_posix(): file_hash(p)
                    for p in [*inv.glob("*.csv"), archive]
                },
            )
        )
    )
    with TrainingSet(tmp_path, "ssdd", manifest) as dataset:
        sample = dataset.read("000001")
        assert sample.example.split == "benchmark" and sample.example.lonlat is None
        assert sample.example.boxes == ((1, 0, 3, 2),) and sample.pixels.shape == (3, 4, 6)
        jpg.write_bytes(b"changed")
        with pytest.raises(SourceError) as err:
            dataset.read("000001")
        assert err.value.state == State.CORRUPT
    with TrainingSet(tmp_path, "gfw-tiles", manifest) as dataset:
        sample = dataset.read(tile_id)
        assert sample.pixels.shape == (2, 80, 80) and sample.channels == (
            "release_channel_0",
            "release_channel_1",
        )
        assert sample.example.presence is False and sample.example.lonlat == (110.0, 1.5)
