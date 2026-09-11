# Artifact V2: sealed-authority replay

Artifact V2 is a self-contained, non-authority reproducibility layer over an already-sealed S6 execution. It does **not** rerun, retune, replace, repair, or reinterpret the scientific authority.

The preservation boundary is fixed by `S6_AUTHORITY_SOURCE_V1.json`. The original public execution run, exact artifact IDs, artifact ZIP SHA-256 digests, aggregate SHA-256, manuscript snapshot hash, and manuscript-facing projection are all bound before preservation.

## Two distinct operations

1. **Authority replay (this directory):** verify preserved bytes, cross-link the separately preserved public-run claim artifacts byte-for-byte to the raw members inside the sealed authority, cross-check raw headline inputs against the sealed aggregate, and deterministically project only the quantities stated in the bound manuscript snapshot.
2. **Fresh replication (not Artifact V2 authority replay):** any future re-execution is replication only. It may not replace the first-complete authority and is not required to reproduce timing values bit-for-bit.

## Self-contained check

After the preservation commit, no source Actions artifact needs to remain live. Run:

```bash
python artifact_v2/verify_preserved_s6.py \
  --source-manifest artifact_v2/S6_AUTHORITY_SOURCE_V1.json \
  --zips-dir artifact_v2/preserved/zips \
  --out /tmp/replaymark-artifact-v2-receipt.json
```

A pass requires exact ZIP digests, exact aggregate digest, separate enforcement binding, no authority rewrite, no threshold change after observation, no performance-value selection of inherited evidence, no rerun of valid inherited source records, byte identity between each separately preserved positive-claim artifact and the corresponding raw member in the sealed authority, raw-to-aggregate headline agreement, and exact agreement with the bound manuscript projection.

The aggregate itself is intentionally recorded as `AGGREGATED_BEFORE_VERDICT_ENFORCEMENT`; the separate frozen enforcement record is what carries `SEALED_COMPLETE_AUTHORITY`. Artifact V2 preserves that ordering rather than collapsing the two stages.
