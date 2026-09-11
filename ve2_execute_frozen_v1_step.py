from __future__ import annotations

"""Execute one exact shell run-block from the frozen VE2 v1 authority workflow.

This is orchestration-only. It verifies the complete frozen workflow byte digest,
extracts one named `run: |` block without editing its contents, records the exact
block digest to stderr, and executes that block under bash with errexit/pipefail.
"""

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_run_block(text: str, step_name: str) -> str:
    lines = text.splitlines(keepends=True)
    marker = f"      - name: {step_name}\n"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise RuntimeError(f"step-not-found:{step_name}") from exc

    run_index = None
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.startswith("      - "):
            break
        if line == "        run: |\n":
            run_index = i
            break
    if run_index is None:
        raise RuntimeError(f"run-block-not-found:{step_name}")

    body: list[str] = []
    for line in lines[run_index + 1 :]:
        if line.startswith("      - "):
            break
        if line.strip() == "":
            body.append("\n")
            continue
        if not line.startswith("          "):
            raise RuntimeError(f"unexpected-run-indentation:{step_name}:{line!r}")
        body.append(line[10:])
    block = "".join(body)
    if not block.strip():
        raise RuntimeError(f"empty-run-block:{step_name}")
    return block


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--expected-sha256", required=True)
    ap.add_argument("--step-name", required=True)
    args = ap.parse_args()

    path = Path(args.workflow)
    observed = file_sha256(path)
    if observed != args.expected_sha256:
        raise SystemExit(f"workflow-sha256-mismatch:{observed}")
    text = path.read_text(encoding="utf-8")
    block = extract_run_block(text, args.step_name)
    digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
    print(f"FROZEN_RUN_BLOCK {args.step_name} sha256={digest}", file=sys.stderr)
    subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail"],
        input=block,
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
