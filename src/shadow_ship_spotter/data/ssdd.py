"""Parsing and validation helpers for the Official SSDD release (BBox-SSDD variant).

Canonical inputs (verified identical copies exist in all four SSDD variants):
  images:       BBox_SSDD/coco_style/images/{train,test}/NNNNNN.jpg   (originals, no drawings)
  COCO labels:  BBox_SSDD/coco_style/annotations/{train,test,test_inshore,test_offshore}.json
  VOC labels:   BBox_SSDD/voc_style/Annotations/NNNNNN.xml          (cross-check only)
  split lists:  BBox_SSDD/voc_style/ImageSets/Main/{train,test,test_inshore,test_offshore}.txt

Never use the ``*_GT`` image folders (e.g. JPEGImages_BBox_GT): they have ground-truth boxes
burnt into the pixels and are visualisation aids only.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from shadow_ship_spotter.paths import RAW_DIR

SSDD_ROOT = RAW_DIR / "ssdd" / "extracted" / "Official-SSDD-OPEN"
BBOX_ROOT = SSDD_ROOT / "BBox_SSDD"
COCO_DIR = BBOX_ROOT / "coco_style"
VOC_DIR = BBOX_ROOT / "voc_style"
SPLITS = ("train", "test")
TEST_SUBSETS = ("test_inshore", "test_offshore")


@dataclass(frozen=True)
class Box:
    """Axis-aligned box in pixel coordinates: (x, y) top-left, width, height."""

    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h


def load_coco(name: str) -> dict:
    return json.loads((COCO_DIR / "annotations" / f"{name}.json").read_text())


def read_voc(xml_path: Path) -> tuple[int, int, list[Box]]:
    """Return (width, height, boxes) from a VOC XML file (VOC corners are inclusive ints)."""
    root = ET.parse(xml_path).getroot()
    size = root.find("size")
    assert size is not None
    w, h = int(size.findtext("width", "0")), int(size.findtext("height", "0"))
    boxes = []
    for obj in root.iter("object"):
        bb = obj.find("bndbox")
        if bb is None:
            continue
        x1, y1 = float(bb.findtext("xmin", "nan")), float(bb.findtext("ymin", "nan"))
        x2, y2 = float(bb.findtext("xmax", "nan")), float(bb.findtext("ymax", "nan"))
        boxes.append(Box(x1, y1, x2 - x1, y2 - y1))
    return w, h, boxes


def read_split_list(name: str) -> list[str]:
    path = VOC_DIR / "ImageSets" / "Main" / f"{name}.txt"
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x, b.x))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y, b.y))
    inter = ix * iy
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def greedy_match(a: list[Box], b: list[Box], thr: float = 0.5) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching by descending IoU. Returns (i, j, iou) pairs >= thr."""
    pairs = sorted(
        ((iou(x, y), i, j) for i, x in enumerate(a) for j, y in enumerate(b)), reverse=True
    )
    used_a: set[int] = set()
    used_b: set[int] = set()
    out = []
    for v, i, j in pairs:
        if v < thr:
            break
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        out.append((i, j, v))
    return out


def dhash(img: Image.Image, size: int = 8) -> int:
    """64-bit difference hash, robust to re-encoding and small intensity changes."""
    g = np.asarray(img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS), float)
    bits = (g[:, 1:] > g[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 (dedup only)


def channel_stats(img: Image.Image) -> tuple[bool, int]:
    """(all channels identical?, max abs difference between channels)."""
    a = np.asarray(img)
    if a.ndim == 2:
        return True, 0
    a = a.astype(np.int16)
    d = int(max(np.abs(a[..., 0] - a[..., 1]).max(), np.abs(a[..., 1] - a[..., 2]).max()))
    return d == 0, d
