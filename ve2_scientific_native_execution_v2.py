from __future__ import annotations

"""Prospective v2 shim: repair only Old-history manifest handoff binding.

The v1 producer records both raw and canonical manifest digests. Its handoff
loader compared the raw field with a canonical recomputation. V2 changes only
that comparison to the already-recorded canonical field and otherwise delegates
all execution to frozen v1.
"""

import json
from pathlib import Path
from typing import Any

import ve2_scientific_native_execution_v1 as base

IMPLEMENTATION = "replaymark.ve2.scientific-native-execution.v2"


def _load_history_v2(
    path: Path,
    transition: str,
    replica: int,
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    doc = json.loads(path.read_bytes())
    if doc.get("schema") != base.SCHEMA or doc.get("stage") != "old_history":
        raise AssertionError("historical-handoff-stage")
    if doc.get("transition") != transition or doc.get("replica") != replica:
        raise AssertionError("historical-handoff-identity")
    if doc.get("manifest_canonical_sha256") != base._sha(manifest):
        raise AssertionError("historical-handoff-manifest-canonical")
    supplied = doc.get("result_sha256")
    body = dict(doc); body.pop("result_sha256", None)
    if supplied != base._sha(body):
        raise AssertionError("historical-handoff-digest")
    rows = doc.get("rows")
    if not isinstance(rows, list) or len(rows) != manifest["state_count"]:
        raise AssertionError("historical-handoff-row-count")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        rr = dict(row)
        row_hash = rr.pop("row_sha256", None)
        if row_hash != base._sha(rr):
            raise AssertionError("historical-row-digest")
        if row.get("status") != "COMPLETE_OBSERVED":
            raise AssertionError("historical-row-incomplete")
        behavior = row.get("historical_behavior")
        base.e0r.validate_behavior(behavior)
        sid = row.get("opaque_state_id")
        if not isinstance(sid, str) or sid in out:
            raise AssertionError("historical-row-id")
        out[sid] = row
    expected = [r["opaque_state_id"] for r in manifest["states"]]
    if list(out) != expected:
        raise AssertionError("historical-row-order")
    return out


base._load_history = _load_history_v2

if __name__ == "__main__":
    base.main()
