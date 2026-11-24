"""Directional product relationships. Only verified substitutions may enter a resolver."""

from enum import StrEnum

from .contracts import SourceError, State


class Product(StrEnum):
    DB = "xview3-db-10m"
    DN = "s1-grd-dn"
    CROP = "pc-native-dn-crop"
    CDSE = "cdse-safe-grd"
    OPTICAL = "optical-image"
    REVIEWED = "xview3-reviewed-annotations"
    WEAK = "xview3-ais-derived-labels"
    SSDD = "ssdd-boxed-jpeg"
    TILES = "gfw-presence-tile"
    REPORTED = "provider-reported-position"
    AIS = "raw-ais-message"
    REGISTRY = "vessel-registry"
    GFW = "gfw-published-prediction"
    MODEL = "sss-model-prediction"


class Relation(StrEnum):
    EQUIVALENT = "equivalent"
    CONDITIONAL = "conditional"
    COMPLEMENT = "complement"
    ALTERNATIVE = "alternative_workflow"
    INCOMPATIBLE = "incompatible"


def relation(requested: Product, offered: Product) -> Relation:
    if requested == offered:
        return Relation.EQUIVALENT
    if requested == Product.DN and offered in (Product.CROP, Product.CDSE):
        return Relation.CONDITIONAL
    if requested in (Product.DB, Product.DN) and offered == Product.OPTICAL:
        return Relation.ALTERNATIVE
    training = {Product.REVIEWED, Product.WEAK, Product.SSDD, Product.TILES}
    if {requested, offered} <= training:
        return Relation.COMPLEMENT
    if (requested, offered) in {
        (Product.REPORTED, Product.REGISTRY),
        (Product.AIS, Product.REGISTRY),
        (Product.MODEL, Product.GFW),
        (Product.REPORTED, Product.AIS),
    }:
        return Relation.COMPLEMENT
    return Relation.INCOMPATIBLE


def require_substitute(requested: Product, offered: Product) -> None:
    kind = relation(requested, offered)
    # The PC crop adapter validates the full parent, offset, product, band and grid at read time.
    # CDSE catalogue access alone supplies no verified pixel conversion.
    if kind == Relation.EQUIVALENT or (requested, offered) == (Product.DN, Product.CROP):
        return
    raise SourceError(State.INCOMPATIBLE, f"{offered} cannot supply {requested} ({kind})")
