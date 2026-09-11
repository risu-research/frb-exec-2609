#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "artifact" / "INTEGRITY_CONTRACT.json"

REQUIRED_GUARDS = (
    "DO_NOT_CITE",
    "STAGING_ONLY",
    "PERFORMANCE_LOCKED",
    "NO_TIMING",
    "STATIC_ONLY",
)

ALLOWED_ROLES = {"NON_AUTHORITY_EXECUTION_CARRIER"}
HEX40 = set("0123456789abcdef")


def die(msg: str) -> None:
    print(json.dumps({"status": "FAIL", "reason": msg}, sort_keys=True))
    raise SystemExit(1)


def is_hex40(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(c in HEX40 for c in value)
    )


def main() -> None:
    if not CONTRACT.is_file():
        die("missing integrity contract")

    try:
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"invalid integrity contract: {type(exc).__name__}")

    if data.get("schema") != "frb.execution-artifact.integrity.v1":
        die("unexpected schema")
    if data.get("authority_role") not in ALLOWED_ROLES:
        die("carrier must remain non-authority")
    if data.get("timing_enabled") is not False:
        die("artifact-v1 must not enable timing")
    if data.get("scientific_sources_mutable") is not False:
        die("scientific sources must remain immutable")
    if data.get("may_replace_first_complete_authority") is not False:
        die("first-complete authority replacement forbidden")
    if data.get("paper_metadata_exported") is not False:
        die("paper metadata must not be exported")
    if data.get("private_authority_identifiers_exported") is not False:
        die("private authority identifiers must not be exported")

    base = data.get("carrier_base_commit")
    if not is_hex40(base):
        die("carrier_base_commit must be a lowercase 40-hex commit")

    missing = [name for name in REQUIRED_GUARDS if not (ROOT / name).is_file()]
    if missing:
        die("missing repository guards: " + ",".join(missing))

    tracked = [
        ROOT / "artifact" / "README.md",
        ROOT / "artifact" / "INTEGRITY_CONTRACT.json",
        ROOT / "artifact" / "verify_bundle.py",
    ]
    missing_tracked = [p.relative_to(ROOT).as_posix() for p in tracked if not p.is_file()]
    if missing_tracked:
        die("missing artifact-v1 files: " + ",".join(missing_tracked))

    digests = {}
    for path in tracked:
        raw = path.read_bytes()
        digests[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()

    report = {
        "schema": "frb.execution-artifact.integrity-report.v1",
        "status": "PASS",
        "authority_role": data["authority_role"],
        "timing_enabled": False,
        "scientific_sources_mutable": False,
        "required_guards": list(REQUIRED_GUARDS),
        "artifact_sha256": digests,
    }
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
