"""Network-free tests for the .env loader and the LSEG probe helpers."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from shadow_ship_spotter import config
from shadow_ship_spotter.data import lseg as L

T0 = datetime(2020, 9, 28, 17, 18, 16, tzinfo=UTC)


def test_parse_dotenv_handles_quotes_comments_export() -> None:
    text = "# c\nEIKON_APP_KEY=abc\nexport B='x y'\nC=\"q\"\nD=v # note\nbad line\n1X=no\n"
    assert config.parse_dotenv(text) == {"EIKON_APP_KEY": "abc", "B": "x y", "C": "q", "D": "v"}


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("SSS_TEST_A=file\nSSS_TEST_B=file\n")
    monkeypatch.setenv("SSS_TEST_A", "shell")
    monkeypatch.delenv("SSS_TEST_B", raising=False)
    assert config.load_dotenv(env) == ["SSS_TEST_B"]
    assert os.environ["SSS_TEST_A"] == "shell" and os.environ["SSS_TEST_B"] == "file"


@pytest.mark.parametrize(
    ("msg", "code", "expected"),
    [
        ("Too many requests, please try again later.", 429, "rate_limited"),
        ("Permission Denied to parameter 'Dur'.", 906, "entitlement_denied"),
        ("Unable to collect data for all requested fields.", 414, "invalid_field"),
        ("Unable to collect data for some field(s).", 415, "no_data"),
        ("The '6' is unexpected in formula.", 234, "bad_request"),
        ("Invalid result window: (top + skip) must not exceed 10,000", 400, "bad_request"),
        ("Connection refused", None, "connection"),
        ("something else", None, "other"),
    ],
)
def test_classify_error(msg: str, code: int | None, expected: str) -> None:
    assert L.classify_error(msg, code) == expected


def _raw() -> dict:
    return {
        "headers": [
            [
                {"displayName": "Instrument"},
                {"field": "TR.ASSETLOCATIONDATE"},
                {"field": "TR.ASSETLOCATIONLATITUDE"},
                {"field": "TR.ASSETLOCATIONLONGITUDE"},
                {"field": "TR.ASSETSPEED"},
                {"field": "TR.ASSETHEADING"},
            ]
        ],
        "data": [
            ["C}A", "2020-09-28T17:00:00Z", 56.0, 7.0, 10.0, 511],
            ["C}A", "2020-09-28T17:30:00Z", 56.1, 7.2, 10.0, 90],
            ["C}B", "", "", "", "", ""],  # no data / invalid identifier -> dropped
            ["C}C", "2020-09-29T01:00:00Z", 0.0, 0.0, None, None],
        ],
        "error": [{"code": 415, "col": 4, "message": "Unable to collect data", "row": 2}],
    }


def test_parse_and_validate_positions() -> None:
    headers, rows, errors = L.parse_adc([_raw()])
    assert headers[1] == "TR.ASSETLOCATIONDATE" and len(errors) == 1
    pos = L.positions_from_adc(headers, rows)
    assert [p["ric"] for p in pos] == ["C}A", "C}A", "C}C"]
    assert pos[0]["time_utc"].tzinfo is not None and pos[0]["heading_deg"] is None  # 511
    assert all(p["position_kind"] == "reported" for p in pos)
    day = datetime(2020, 9, 28, tzinfo=UTC)
    v = L.validate_positions(pos, day, day + timedelta(hours=23, minutes=59, seconds=59))
    assert v["n_inside_requested_interval"] == 2 and v["n_outside_requested_interval"] == 1
    assert v["n_valid_coords"] == 2  # (0, 0) rejected


def test_nearest_and_interpolation() -> None:
    pos = L.positions_from_adc(*L.parse_adc(_raw())[:2])
    track = [p for p in pos if p["ric"] == "C}A"]
    near, gap = L.nearest_position(track, T0)
    assert near is track[1] and gap == pytest.approx(11 * 60 + 44)
    ip = L.interpolate_position(track, T0, max_gap_s=30 * 60)
    assert ip is not None and ip["position_kind"] == "interpolated_by_probe"
    assert 56.0 < ip["lat"] < 56.1 and 7.0 < ip["lon"] < 7.2
    assert L.interpolate_position(track, T0, max_gap_s=10 * 60) is None
    assert L.median_interval_s(track) == 1800


def test_geometry_and_filters() -> None:
    assert L.haversine_m(0, 0, 0, 1) == pytest.approx(111_195, rel=1e-3)
    bbox = (108.5, 17.5, 111.5, 19.5)
    assert L.bbox_filter(bbox).startswith("Latitude ge 17.5 and Latitude le 19.5")
    with pytest.raises(ValueError):
        L.bbox_filter((170.0, 0.0, -170.0, 1.0))
    big = L.buffer_bbox(bbox, 111.32)
    assert big[1] == pytest.approx(16.5) and big[0] < 107.5
    assert len(L.split_bbox(bbox)) == 4
    assert L.in_bbox(18.0, 110.0, bbox) and not L.in_bbox(0.0, 0.0, (-1, -1, 1, 1))
    assert L.in_filter("MMSI", ["1", "2"]) == "MMSI in ('1' '2')"
    assert L.day_params(T0 - timedelta(hours=20), T0) == {
        "SDate": "2020-09-27",
        "EDate": "2020-09-28",
    }
    assert L.normalise_mmsi(244577000.0) == "244577000" and L.normalise_mmsi(None) is None
    assert L.normalise_mmsi(12.5) is None
