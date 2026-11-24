"""Validate the extracted Official SSDD (BBox-SSDD) sample and build a machine-readable inventory.

Usage (from the repository root, after scripts/download_ssdd.py):
    uv run python -I scripts/validate_ssdd.py

Outputs (small, tracked in Git):
    data/inventory/ssdd_images.csv        one row per image
    data/inventory/ssdd_boxes.csv         one row per COCO box (+ matched VOC box)
    data/inventory/ssdd_validation.json   summary of every check and its result
    docs/figures/ssdd_overlays.png        annotation-overlay grid for visual verification
Outputs (git-ignored):
    data/processed/ssdd_overlays/*.png    per-image overlays for a larger sample

Checks: image files exist and open; COCO/VOC/actual dimensions agree; boxes are positive and
inside the image; COCO vs VOC box agreement per image; split-list consistency (COCO vs VOC
ImageSets, train/test disjoint, inshore+offshore == test); exact and near duplicates (MD5,
dHash) within and across splits; channel structure of the JPEGs.
"""

from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

from shadow_ship_spotter.data import ssdd  # noqa: E402
from shadow_ship_spotter.paths import (  # noqa: E402
    FIGURES_DIR,
    INVENTORY_DIR,
    PROCESSED_DIR,
    REPO_ROOT,
)

NEAR_DUP_HAMMING = 4  # dHash bits; <=4/64 is visually near-identical in our spot checks
OOB_TOL = 1.0  # px tolerance for boxes touching the border


def rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


def main() -> None:
    if not ssdd.COCO_DIR.exists():
        sys.exit(f"SSDD not found at {ssdd.SSDD_ROOT}. Run scripts/download_ssdd.py first.")
    report: dict = {"source": "Official-SSDD-OPEN.rar / BBox_SSDD", "checks": {}}
    checks = report["checks"]

    # ---- COCO ---------------------------------------------------------------------------
    coco = {s: ssdd.load_coco(s) for s in (*ssdd.SPLITS, *ssdd.TEST_SUBSETS)}
    cats = {c["id"]: c["name"] for s in coco.values() for c in s["categories"]}
    checks["coco_categories"] = cats

    img_rows: dict[str, dict] = {}
    box_rows: list[dict] = []
    problems: list[str] = []
    coco_ids_seen: dict[int, str] = {}
    for split in ssdd.SPLITS:
        d = coco[split]
        by_img = collections.defaultdict(list)
        for a in d["annotations"]:
            by_img[a["image_id"]].append(a)
        ann_ids = [a["id"] for a in d["annotations"]]
        if len(ann_ids) != len(set(ann_ids)):
            problems.append(f"{split}: duplicate COCO annotation ids")
        img_ids = {im["id"] for im in d["images"]}
        orphans = [a["id"] for a in d["annotations"] if a["image_id"] not in img_ids]
        if orphans:
            problems.append(f"{split}: {len(orphans)} annotations reference unknown image ids")
        for im in d["images"]:
            stem = Path(im["file_name"]).stem
            if im["id"] in coco_ids_seen:
                problems.append(f"image id {im['id']} in both {coco_ids_seen[im['id']]} & {split}")
            coco_ids_seen[im["id"]] = split
            if int(stem) != im["id"]:
                problems.append(f"{im['file_name']}: COCO id {im['id']} != filename number")
            path = ssdd.COCO_DIR / "images" / split / im["file_name"]
            row = {
                "image_id": stem,
                "coco_image_id": im["id"],
                "file_name": im["file_name"],
                "path": rel(path),
                "official_split": split,
                "coco_width": im["width"],
                "coco_height": im["height"],
                "file_exists": path.exists(),
            }
            img_rows[stem] = row
            if not path.exists():
                problems.append(f"missing image file {rel(path)}")
                continue
            with Image.open(path) as pil:
                pil.load()
                row.update(width=pil.width, height=pil.height, mode=pil.mode, format=pil.format)
                same, maxdiff = ssdd.channel_stats(pil)
                row.update(channels_identical=same, channel_max_absdiff=maxdiff)
                row["dhash"] = f"{ssdd.dhash(pil):016x}"
            row["md5"] = ssdd.md5(path)

            # VOC cross-check
            xml = ssdd.VOC_DIR / "Annotations" / f"{stem}.xml"
            voc_boxes: list[ssdd.Box] = []
            if xml.exists():
                vw, vh, voc_boxes = ssdd.read_voc(xml)
                row.update(voc_width=vw, voc_height=vh)
            else:
                problems.append(f"missing VOC xml for {stem}")
            coco_boxes = [ssdd.Box(*a["bbox"]) for a in by_img[im["id"]]]
            matches = ssdd.greedy_match(coco_boxes, voc_boxes, thr=0.5)
            mj = {i: (j, v) for i, j, v in matches}
            row.update(
                n_boxes_coco=len(coco_boxes),
                n_boxes_voc=len(voc_boxes),
                n_boxes_matched=len(matches),
            )
            for i, (a, b) in enumerate(zip(by_img[im["id"]], coco_boxes, strict=True)):
                j, v = mj.get(i, (None, None))
                vb = voc_boxes[j] if j is not None else None
                oob = (
                    b.x < -OOB_TOL
                    or b.y < -OOB_TOL
                    or b.x2 > pil.width + OOB_TOL
                    or b.y2 > pil.height + OOB_TOL
                )
                box_rows.append(
                    {
                        "image_id": stem,
                        "official_split": split,
                        "coco_ann_id": a["id"],
                        "category": cats.get(a["category_id"]),
                        "x": round(b.x, 2),
                        "y": round(b.y, 2),
                        "w": round(b.w, 2),
                        "h": round(b.h, 2),
                        "coco_area": round(a.get("area", float("nan")), 2),
                        "iscrowd": a.get("iscrowd"),
                        "ignore": a.get("ignore"),
                        "has_segmentation": bool(a.get("segmentation")),
                        "positive_size": b.w > 0 and b.h > 0,
                        "out_of_bounds": oob,
                        "voc_match_iou": round(v, 3) if v is not None else None,
                        "voc_x": vb.x if vb else None,
                        "voc_y": vb.y if vb else None,
                        "voc_w": vb.w if vb else None,
                        "voc_h": vb.h if vb else None,
                    }
                )

    images = pd.DataFrame(list(img_rows.values())).sort_values("image_id")
    boxes = pd.DataFrame(box_rows)

    # Test inshore/offshore membership (COCO files)
    sub = {}
    for s in ssdd.TEST_SUBSETS:
        sub[s] = {Path(im["file_name"]).stem for im in coco[s]["images"]}
    images["test_scene_type"] = images["image_id"].map(
        lambda x: (
            "inshore"
            if x in sub["test_inshore"]
            else "offshore" if x in sub["test_offshore"] else ""
        )
    )
    # Training-image inshore/offshore lists exist only as image folders in voc_style.
    train_in = {p.stem for p in (ssdd.VOC_DIR / "JPEGImages_train_inshore").glob("*.jpg")}
    train_off = {p.stem for p in (ssdd.VOC_DIR / "JPEGImages_train_offshore").glob("*.jpg")}
    images.loc[images.image_id.isin(train_in), "test_scene_type"] = "inshore"
    images.loc[images.image_id.isin(train_off), "test_scene_type"] = "offshore"
    images = images.rename(columns={"test_scene_type": "scene_type"})
    # Not provided by SSDD: kept as explicit empty columns so downstream code does not assume.
    for col in ("parent_scene_id", "sensor", "polarisation", "acquisition_time", "lat", "lon"):
        images[col] = pd.NA

    # ---- Checks -------------------------------------------------------------------------
    checks["n_images"] = int(len(images))
    checks["n_images_by_split"] = images.official_split.value_counts().to_dict()
    checks["n_boxes_coco"] = int(len(boxes))
    checks["n_boxes_coco_by_split"] = boxes.official_split.value_counts().to_dict()
    checks["n_boxes_voc"] = int(images.n_boxes_voc.sum())
    checks["missing_image_files"] = int((~images.file_exists).sum())
    dims_ok = (images.width == images.coco_width) & (images.height == images.coco_height)
    dims_ok &= (images.width == images.voc_width) & (images.height == images.voc_height)
    checks["dimension_mismatches"] = images.loc[~dims_ok, "image_id"].tolist()
    checks["images_without_boxes"] = images.loc[images.n_boxes_coco == 0, "image_id"].tolist()
    checks["boxes_nonpositive_size"] = int((~boxes.positive_size).sum())
    checks["boxes_out_of_bounds"] = boxes.loc[
        boxes.out_of_bounds, ["image_id", "coco_ann_id"]
    ].to_dict("records")
    cnt_mismatch = images[images.n_boxes_coco != images.n_boxes_voc]
    checks["coco_vs_voc_count_mismatch_images"] = cnt_mismatch[
        ["image_id", "n_boxes_coco", "n_boxes_voc"]
    ].to_dict("records")
    checks["coco_boxes_without_voc_match_iou50"] = int(boxes.voc_match_iou.isna().sum())
    checks["coco_voc_iou_quantiles"] = (
        boxes.voc_match_iou.dropna().quantile([0.0, 0.01, 0.05, 0.5]).round(3).to_dict()
    )
    checks["box_size_px"] = {
        "w": boxes.w.describe().round(1).to_dict(),
        "h": boxes.h.describe().round(1).to_dict(),
        "boxes_lt_8px_min_side": int(((boxes[["w", "h"]].min(axis=1)) < 8).sum()),
    }
    checks["image_size_px"] = {
        "width": images.width.describe().round(1).to_dict(),
        "height": images.height.describe().round(1).to_dict(),
    }
    checks["channels"] = {
        "modes": images["mode"].value_counts().to_dict(),
        "identical_rgb_channels": int(images.channels_identical.sum()),
        "non_identical": images.loc[~images.channels_identical, ["image_id", "channel_max_absdiff"]]
        .sort_values("channel_max_absdiff", ascending=False)
        .to_dict("records"),
    }

    # Split consistency against supplied VOC ImageSets lists
    split_checks = {}
    for name in (*ssdd.SPLITS, *ssdd.TEST_SUBSETS):
        lst = set(ssdd.read_split_list(name))
        coco_set = {Path(im["file_name"]).stem for im in coco[name]["images"]}
        split_checks[name] = {
            "voc_list": len(lst),
            "coco": len(coco_set),
            "identical": lst == coco_set,
        }
    tr = set(images.loc[images.official_split == "train", "image_id"])
    te = set(images.loc[images.official_split == "test", "image_id"])
    split_checks["train_test_disjoint"] = not (tr & te)
    split_checks["inshore_offshore_partition_test"] = sub["test_inshore"] | sub[
        "test_offshore"
    ] == te and not (sub["test_inshore"] & sub["test_offshore"])
    split_checks["test_ids_end_in_1_or_9"] = all(x[-1] in "19" for x in te)
    split_checks["train_ids_never_end_in_1_or_9"] = all(x[-1] not in "19" for x in tr)
    checks["splits"] = split_checks

    # Duplicates
    md5_groups = images.groupby("md5").image_id.apply(list)
    checks["exact_duplicate_groups"] = [g for g in md5_groups if len(g) > 1]
    hashes = [(r.image_id, int(r.dhash, 16), r.official_split) for r in images.itertuples()]
    near = []
    for i in range(len(hashes)):
        for j in range(i + 1, len(hashes)):
            d = bin(hashes[i][1] ^ hashes[j][1]).count("1")
            if d <= NEAR_DUP_HAMMING:
                near.append(
                    {
                        "a": hashes[i][0],
                        "b": hashes[j][0],
                        "hamming": d,
                        "cross_split": hashes[i][2] != hashes[j][2],
                    }
                )
    checks["near_duplicate_pairs_dhash_le4"] = near
    checks["near_duplicate_cross_split_pairs"] = sum(p["cross_split"] for p in near)
    checks["other_problems"] = problems
    checks["parent_scene_metadata_available"] = False

    # ---- Write --------------------------------------------------------------------------
    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    images.drop(columns=["file_exists"]).to_csv(INVENTORY_DIR / "ssdd_images.csv", index=False)
    boxes.to_csv(INVENTORY_DIR / "ssdd_boxes.csv", index=False)
    (INVENTORY_DIR / "ssdd_validation.json").write_text(json.dumps(report, indent=2, default=str))

    # ---- Overlays -----------------------------------------------------------------------
    rng = random.Random(0)
    pick = []
    for split in ("train", "test"):
        for st in ("offshore", "inshore"):
            pool = images[(images.official_split == split) & (images.scene_type == st)]
            pool = pool[pool.n_boxes_coco > 0].image_id.tolist()
            pick += rng.sample(pool, 3)
    many = images.sort_values("n_boxes_coco", ascending=False).image_id.iloc[0]
    pick = [*pick[:11], many] if many not in pick else pick[:12]
    if cnt_mismatch.shape[0]:
        pick[-1] = cnt_mismatch.image_id.iloc[0]  # show one disagreement case if any

    def draw(ax, stem: str) -> None:
        r = images.set_index("image_id").loc[stem]
        ax.imshow(Image.open(REPO_ROOT / r.path), cmap="gray")
        for b in boxes[boxes.image_id == stem].itertuples():
            ax.add_patch(mpatches.Rectangle((b.x, b.y), b.w, b.h, fill=False, ec="lime", lw=1.2))
        _, _, vb = ssdd.read_voc(ssdd.VOC_DIR / "Annotations" / f"{stem}.xml")
        for b in vb:
            ax.add_patch(
                mpatches.Rectangle((b.x, b.y), b.w, b.h, fill=False, ec="red", lw=0.8, ls="--")
            )
        ax.set_title(
            f"{stem} {r.official_split}/{r.scene_type}  coco={r.n_boxes_coco} voc={r.n_boxes_voc}",
            fontsize=7,
        )
        ax.axis("off")

    fig, axes = plt.subplots(3, 4, figsize=(16, 11))
    for ax, stem in zip(axes.flat, pick, strict=False):
        draw(ax, stem)
    fig.suptitle(
        "SSDD original images with annotations drawn by us: "
        "COCO bbox (green), VOC bbox (red dashed)",
        fontsize=10,
    )
    fig.tight_layout()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES_DIR / "ssdd_overlays.png", dpi=110)
    plt.close(fig)

    out = PROCESSED_DIR / "ssdd_overlays"
    out.mkdir(parents=True, exist_ok=True)
    for stem in rng.sample(images.image_id.tolist(), 40) + pick:
        fig, ax = plt.subplots(figsize=(6, 5))
        draw(ax, stem)
        fig.savefig(out / f"{stem}.png", dpi=100, bbox_inches="tight")
        plt.close(fig)

    # ---- Console summary ----------------------------------------------------------------
    s = checks
    print(
        f"images={s['n_images']} {s['n_images_by_split']}  "
        f"boxes coco={s['n_boxes_coco']} voc={s['n_boxes_voc']}"
    )
    print(
        f"missing files={s['missing_image_files']} dim mismatches={len(s['dimension_mismatches'])}"
    )
    print(
        f"nonpositive boxes={s['boxes_nonpositive_size']} "
        f"out-of-bounds={len(s['boxes_out_of_bounds'])}"
    )
    print(
        f"coco/voc count-mismatch images={len(s['coco_vs_voc_count_mismatch_images'])} "
        f"unmatched coco boxes={s['coco_boxes_without_voc_match_iou50']} "
        f"iou q={s['coco_voc_iou_quantiles']}"
    )
    print(f"splits={s['splits']}")
    print(
        f"exact dup groups={len(s['exact_duplicate_groups'])} near-dup pairs={len(near)} "
        f"(cross-split {s['near_duplicate_cross_split_pairs']})"
    )
    print(f"channels={s['channels']['modes']} identical={s['channels']['identical_rgb_channels']}")
    print(f"images without boxes={len(s['images_without_boxes'])} other problems={len(problems)}")
    print(f"wrote {INVENTORY_DIR}/ssdd_*.csv|json and {FIGURES_DIR / 'ssdd_overlays.png'}")


if __name__ == "__main__":
    main()
