# Partition assignments

**What this folder is for.** A *split* assigns every image, chip or scene to exactly one
partition:
- **train**: used to fit models;
- **validation**: used to tune them;
- **test**: used once for the final evaluation.

If near-identical data ends up on both sides, results look better than they are ("leakage").
This folder will hold versioned split files, so that the descriptor-based and CNN approaches are
compared on exactly the same partitions.

**No split has been finalised yet (step 2 deliberately stops before splitting).**

Constraints established by the step-2 validation (see `docs/validation_results.md`):

- **SSDD**: the official train/test split leaks — 10 exact-duplicate groups and 4 near-duplicate
  pairs cross it, and some harbour crops overlap visually. Any split we use for the
  descriptor-vs-CNN comparison must assign whole duplicate clusters (exact MD5 groups, dHash
  near-duplicates, and manually confirmed same-scene crops) to one partition. If results are also
  reported on the official split for literature comparison, flag the leakage.
- **xView3**: split by scene (never by detection/chip). Validation-partition labels are
  human-reviewed; train labels are AIS-derived, have no boxes, and their `confidence` column
  encodes `is_vessel`. Chips cut from one scene must stay in one partition.
- **GFW detection tiles**: group by parent scene (parsed from `detect_id`); GFW's own train/test
  indices share 2 scenes.
- Identical partitions must be used for the traditional-ML and CNN approaches; final evaluation of
  the full pipeline happens on held-out *scenes*.

Planned files: `ssdd_groups.csv` (duplicate clusters), `ssdd_split_v1.csv`,
`xview3_scene_split_v1.csv` — each with a version, seed, and generating script.
