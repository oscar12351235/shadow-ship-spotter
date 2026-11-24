from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from shadow_ship_spotter.data.compatibility import Product, Relation, relation, require_substitute
from shadow_ship_spotter.data.contracts import (
    Origin,
    Policy,
    RasterRequest,
    SourceError,
    State,
    Window,
)
from shadow_ship_spotter.data.imagery import CachedCog, Grid, Piece, RasterResolver
from shadow_ship_spotter.data.storage import BlobCache

SCENE = "S1A_IW_GRDH_1SDV_20200126T052956_20200126T053025_030967_038E50_B43E"


def win(x=0, y=0, w=6, h=4):
    return Window(col=x, row=y, width=w, height=h)


def request(**kwargs):
    return RasterRequest.model_validate(
        dict(scene=SCENE, product="s1-grd-dn", window=win(), georeferenced=False) | kwargs
    )


class Measured:
    product = Product.DN

    def __init__(self, extent=None, bands=("VV", "VH"), value=7):
        self.extent = extent or win(w=100, h=100)
        self.bands = bands
        self.value = value
        self.calls = []

    def read(self, q, band, w):
        self.calls.append((band, w))
        overlap = w.intersect(self.extent)
        if overlap is None or band not in self.bands:
            raise SourceError(State.UNAVAILABLE, "missing coverage")
        return Piece(
            band,
            overlap,
            Grid(width=100, height=100),
            np.ma.array(np.full((overlap.height, overlap.width), self.value, dtype="uint16")),
            Origin(
                source="pc-cog",
                asset=f"{q.scene}/measurement/{band}",
                product=self.product,
                revision=q.scene,
            ),
            q.scene,
        )


@pytest.mark.parametrize(
    ("wanted", "offered", "kind"),
    [
        (Product.DN, Product.DN, Relation.EQUIVALENT),
        (Product.DN, Product.CROP, Relation.CONDITIONAL),
        (Product.DN, Product.CDSE, Relation.CONDITIONAL),
        (Product.DB, Product.DN, Relation.INCOMPATIBLE),
        (Product.DB, Product.OPTICAL, Relation.ALTERNATIVE),
        (Product.REVIEWED, Product.WEAK, Relation.COMPLEMENT),
        (Product.TILES, Product.SSDD, Relation.COMPLEMENT),
        (Product.AIS, Product.REGISTRY, Relation.COMPLEMENT),
        (Product.AIS, Product.GFW, Relation.INCOMPATIBLE),
        (Product.REPORTED, Product.GFW, Relation.INCOMPATIBLE),
        (Product.REVIEWED, Product.GFW, Relation.INCOMPATIBLE),
        (Product.MODEL, Product.GFW, Relation.COMPLEMENT),
    ],
)
def test_relationships(wanted, offered, kind):
    assert relation(wanted, offered) == kind
    if wanted == offered or (wanted, offered) == (Product.DN, Product.CROP):
        require_substitute(wanted, offered)
    else:
        with pytest.raises(SourceError) as err:
            require_substitute(wanted, offered)
        assert err.value.state == State.INCOMPATIBLE


def compose(*readers):
    return RasterResolver(
        Policy(version=1, raster_priority=tuple(k for k, _ in readers)), dict(readers)
    )


def test_partial_supplements_only_missing_band_and_rectangles():
    local = Measured(win(2, 1, 3, 2), bands=("VV",), value=1)
    local.product = Product.CROP
    remote = Measured()
    result = compose(("pc-crop", local), ("pc-cog", remote)).resolve(request())
    assert result.state == State.COMPLETE and result.stack().shape == (2, 4, 6)
    assert len(remote.calls) == 5
    assert all(w.intersect(local.extent) is None for b, w in remote.calls if b == "VV")
    assert result.stack()[0, 1:3, 2:5].tolist() == [[1] * 3] * 2
    assert (result.stack()[1] == 7).all() and result.missing == {"VV": (), "VH": ()}
    assert [a.state for a in result.attempts][:2] == [State.PARTIAL, State.UNAVAILABLE]
    full = Measured()
    compose(("pc-crop", full), ("pc-cog", remote)).resolve(request())
    assert len(remote.calls) == 5


def test_actual_product_scene_grid_shape_and_geo_are_checked():
    reader = Measured()
    result = compose(("pc-cog", reader)).resolve(request(product="xview3-db-10m"))
    assert result.state == State.INCOMPATIBLE and not reader.calls
    assert (
        compose(("pc-cog", reader)).resolve(request(georeferenced=True)).state == State.INCOMPATIBLE
    )

    class Wrong(Measured):
        def read(self, q, b, w):
            return replace(super().read(q, b, w), scene=SCENE[:-4] + "FFFF")

    assert compose(("pc-cog", Wrong())).resolve(request()).state == State.INCOMPATIBLE

    class Bug(Measured):
        def read(self, q, b, w):
            raise RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        compose(("pc-cog", Bug())).resolve(request())


def test_partial_result_does_not_fabricate_missing_pixels():
    result = compose(("pc-crop", Measured(win(0, 0, 2, 2)))).resolve(request(bands=["VV"]))
    assert result.state == State.PARTIAL
    assert sum(w.width * w.height for w in result.missing["VV"]) == 20
    with pytest.raises(SourceError):
        result.stack()


def test_access_failure_can_only_fall_back_to_same_product_with_trace():
    class Denied(Measured):
        def read(self, q, b, w):
            raise SourceError(State.ACCESS, "HTTP 403")

    result = compose(("pc-crop", Denied()), ("pc-cog", Measured())).resolve(request())
    assert result.state == State.COMPLETE and result.attempts[0].state == State.ACCESS
    assert compose(("pc-cog", Denied())).resolve(request()).state == State.ACCESS


def test_incompatible_second_band_grid_keeps_the_first():
    class Shifted(Measured):
        def read(self, q, b, w):
            p = super().read(q, b, w)
            return replace(
                p,
                grid=Grid(
                    width=100,
                    height=100,
                    crs="EPSG:32631",
                    affine=(10, 0, 0 if b == "VV" else 10, 0, -10, 1000),
                ),
            )

    result = compose(("pc-cog", Shifted())).resolve(request(georeferenced=True))
    assert result.state == State.PARTIAL and set(p.band for p in result.pieces) == {"VV"}
    assert result.attempts[-1].state == State.INCOMPATIBLE


def test_cache_overlaps_offline_replay_and_versioned_identity(tmp_path):
    store = BlobCache(tmp_path / "cache.sqlite")
    reader = Measured()
    cache = CachedCog(reader, store, True)
    resolver = compose(("pc-cog", cache))
    assert resolver.resolve(request(window=win(w=3), bands=["VV"])).state == State.COMPLETE
    result = resolver.resolve(request(bands=["VV"]))
    assert reader.calls == [("VV", win(w=3)), ("VV", win(x=3, w=3))]
    assert (
        len(result.pieces) == 2 and "verified cache read" in result.pieces[0].origin.transformations
    )
    offline = CachedCog(reader, store, False)
    resolver = compose(("pc-cog", offline))
    assert np.array_equal(resolver.resolve(request(bands=["VV"])).stack(), result.stack())
    for q in (request(bands=["VH"]), request(scene=SCENE[:-4] + "1234"), request(window=win(y=20))):
        assert resolver.resolve(q).state == State.UNAVAILABLE
    offline.version = "processing-v2"
    assert resolver.resolve(request()).state == State.UNAVAILABLE
    assert len(reader.calls) == 2


def test_cache_detects_and_repairs_exact_corruption(tmp_path: Path):
    store = BlobCache(tmp_path / "cache.sqlite")
    reader = Measured()
    q = request(bands=["VV"])
    online = compose(("pc-cog", CachedCog(reader, store, True)))
    online.resolve(q)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE objects SET payload=?", (b"damaged",))
    assert compose(("pc-cog", CachedCog(reader, store, False))).resolve(q).state == State.CORRUPT
    recovered = online.resolve(q)
    assert recovered.state == State.COMPLETE
    assert "refetched after cache digest failure" in recovered.pieces[0].origin.transformations


def test_parent_grid_only_read_repair_and_offline_reuse_of_nonorigin_window(tmp_path):
    grid = Grid(width=100, height=100, crs="EPSG:32631", affine=(10, 0, 0, 0, -10, 1000))

    class Located(Measured):
        def grid(self, scene, band):
            self.calls.append((scene, band))
            return grid

        def read(self, q, b, w):
            return replace(super().read(q, b, w), grid=grid)

    store = BlobCache(tmp_path / "grid.sqlite")
    reader = Located()
    online = compose(("pc-cog", CachedCog(reader, store, True)))
    offline = compose(("pc-cog", CachedCog(reader, store, False)))
    assert online.locate(SCENE, "s1-grd-dn").grid == grid
    assert offline.locate(SCENE, "s1-grd-dn").grid == grid
    assert reader.calls == [(SCENE, "VV")]
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE objects SET payload=?", (b"damaged",))
    assert offline.locate(SCENE, "s1-grd-dn").state == State.CORRUPT
    assert online.locate(SCENE, "s1-grd-dn").grid == grid
    assert online.resolve(request(bands=["VH"], window=win(x=17, y=11))).state == State.COMPLETE
    assert offline.locate(SCENE, "s1-grd-dn", "VH").grid == grid
    assert reader.calls == [(SCENE, "VV"), (SCENE, "VV"), ("VH", win(x=17, y=11))]


def test_incompatible_network_measurement_is_never_cached(tmp_path):
    class WrongUnits(Measured):
        def read(self, q, b, w):
            p = super().read(q, b, w)
            return replace(p, pixels=p.pixels.astype("float32"))

    store = BlobCache(tmp_path / "bad.sqlite")
    reader = WrongUnits()
    q = request(bands=["VV"])
    assert (
        compose(("pc-cog", CachedCog(reader, store, True))).resolve(q).state == State.INCOMPATIBLE
    )
    assert (
        compose(("pc-cog", CachedCog(reader, store, False))).resolve(q).state == State.UNAVAILABLE
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"product": "optical"},
        {"bands": ["HH"]},
        {"bands": ["VV", "VV"]},
        {"scene": SCENE.rsplit("_", 1)[0]},
        {"window": {"col": 1.2, "row": 0, "width": 2, "height": 2}},
    ],
)
def test_incompatible_request(kwargs):
    with pytest.raises(ValidationError):
        request(**kwargs)


@pytest.mark.parametrize(
    "settings",
    [
        {"raster_priority": ["pc-typo"]},
        {"raster_priority": ["pc-cog", "pc-crop"]},
        {"raster_priority": ["xview3"], "required_layers": ["positions"]},
        {"raster_priority": ["xview3"], "lseg_runs": ["../latest"]},
        {"raster_priority": ["xview3"], "typo": True},
    ],
)
def test_bad_config_fails(settings):
    with pytest.raises(ValidationError):
        Policy.model_validate({"version": 1, **settings})
