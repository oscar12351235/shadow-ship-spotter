# Partition assignments

**What this folder is for.** A *split* assigns every image, chip or scene to exactly one
partition:
- **train**: used to fit models;
- **validation**: used to tune them;
- **test**: used once for the final evaluation.

If near-identical data ends up on both sides, results look better than they are ("leakage").
This folder holds the versioned inputs used by the descriptor-based and CNN approaches.

[`training-v1.json`](training-v1.json) is the pinned pilot manifest. Both model families use
the same reader and partitions. Full Sentinel IDs are grouped by platform, absolute orbit and
datatake. Three explicit group assignments put Lagos in train, the Adriatic in validation and
the North Sea in test. Other groups use the first eight SHA-256 bytes of `seed/group`, big-endian
modulo 100, with cutoffs at 70 and 85. Both xView3 and GFW use this same function. SSDD belongs
to one external benchmark partition because its parent acquisitions are unknown.

Constraints established by the step-2 validation (see `docs/validation_results.md`):

- **SSDD**: the official train/test split leaks — 10 exact-duplicate groups and 4 near-duplicate
  pairs cross it, and some harbour crops overlap visually. Any split we use for the
  descriptor-vs-CNN comparison must assign whole duplicate clusters (exact MD5 groups, dHash
  near-duplicates, and manually confirmed same-scene crops) to one partition. If results are also
  reported on the official split for literature comparison, flag the leakage.
- **xView3** uses only `manual` and `ais/manual` in the default reviewed product. The local
  validation release also has 27 `ais` rows, available through the explicit weak product.
  Their scene assignments stay fixed. All original training-partition labels are AIS-derived
  and lack boxes. The corresponding training-partition rasters are absent from this checkout.
- **GFW detection tiles**: group by parent scene (parsed from `detect_id`); GFW's own train/test
  indices share 2 scenes.
- Identical partitions must be used for the traditional-ML and CNN approaches; final evaluation of
  the full pipeline happens on held-out *scenes*.

A separate SSDD training experiment would require reviewed duplicate/overlap groups and a
new manifest version. Use the [data-layer guide](../../docs/data_layer.md) for examples.
