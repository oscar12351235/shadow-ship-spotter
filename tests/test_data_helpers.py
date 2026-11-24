from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from shadow_ship_spotter.data import ssdd
from shadow_ship_spotter.data.download import file_hash, verify

REPO = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_iou_identical_and_disjoint() -> None:
    a = ssdd.Box(0, 0, 10, 10)
    assert ssdd.iou(a, a) == pytest.approx(1.0)
    assert ssdd.iou(a, ssdd.Box(20, 20, 5, 5)) == 0.0
    assert ssdd.iou(a, ssdd.Box(5, 0, 10, 10)) == pytest.approx(50 / 150)


def test_greedy_match_is_one_to_one() -> None:
    a = [ssdd.Box(0, 0, 10, 10), ssdd.Box(100, 100, 10, 10)]
    b = [ssdd.Box(1, 1, 10, 10), ssdd.Box(0, 0, 10, 10)]
    m = ssdd.greedy_match(a, b, thr=0.5)
    assert [(i, j) for i, j, _ in m] == [(0, 1)]


def test_read_voc(tmp_path: Path) -> None:
    xml = tmp_path / "x.xml"
    xml.write_text(
        "<annotation><size><width>50</width><height>40</height><depth>3</depth></size>"
        "<object><name>ship</name><bndbox><xmin>1</xmin><ymin>2</ymin><xmax>11</xmax>"
        "<ymax>7</ymax></bndbox></object></annotation>"
    )
    w, h, boxes = ssdd.read_voc(xml)
    assert (w, h) == (50, 40)
    assert boxes == [ssdd.Box(1, 2, 10, 5)]


def test_verify_detects_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    digest = verify(f, None, 5)
    assert digest == file_hash(f)
    with pytest.raises(RuntimeError):
        verify(f, "0" * 64, None)


def test_parse_aria2_list(tmp_path: Path) -> None:
    mod = _load_script("download_xview3_scenes")
    p = tmp_path / "list.txt"
    p.write_text(
        "https://example.org/validation/0123456789abcdefv.tar.gz?sig=x\n"
        " checksum=sha-1=deadbeef\n"
    )
    assert mod.parse_aria2_list(p) == {
        "0123456789abcdefv": (
            "https://example.org/validation/0123456789abcdefv.tar.gz?sig=x",
            "deadbeef",
        )
    }
