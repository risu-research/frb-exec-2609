from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The scientific acceptance policy is intentionally outside the agent workspace.
# This stable client exposes one identical verifier entry point in every run.
proc = subprocess.run(
    ["/opt/exec/bin/verify-candidate", str(ROOT)],
    text=True,
    capture_output=True,
)
print(proc.stdout, end="")
if proc.stderr:
    print(proc.stderr, end="")
raise SystemExit(proc.returncode)
