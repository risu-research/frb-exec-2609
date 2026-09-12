from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "Concrete.lean"

EXPECTED = [
    *(f"C.c{i}_{suffix}" for i in range(6) for suffix in ("weaker", "channel", "qa", "qb", "full")),
    *(f"C.c{i}_exact" for i in range(6)),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    text = text.replace("import Std.Tactic.Omega", "import Lean.Elab.Tactic.Omega")
    repl = {
        "structure C0 where r : Int; a : Bool; o : Int": "structure C0 where\n  r : Int\n  a : Bool\n  o : Int",
        "structure C1 where x : Int; l : Int; a : Bool": "structure C1 where\n  x : Int\n  l : Int\n  a : Bool",
        "structure C2 where a : Bool; w : Bool; y : Bool": "structure C2 where\n  a : Bool\n  w : Bool\n  y : Bool",
        "structure C3 where s : Int; o : Int": "structure C3 where\n  s : Int\n  o : Int",
        "structure C4 where x : Int; y : Int; ox : Int; oy : Int": "structure C4 where\n  x : Int\n  y : Int\n  ox : Int\n  oy : Int",
        "structure C5 where n : Int; o : Int": "structure C5 where\n  n : Int\n  o : Int",
        "cases a <;> simp [i0,s0] at hi ⊢ <;> omega": "cases a <;> simp [d0,i0,s0] at hd hi ⊢ <;> omega",
        "simp [b5,s5] at hb ⊢\n    omega": "simp [d5,b5,s5] at hd hb ⊢\n    omega",
    }
    for old, new in repl.items():
        if old not in text:
            raise SystemExit(f"NORMALIZATION_INPUT_MISSING:{old}")
        text = text.replace(old, new, 1)
    if "Std.Tactic.Omega" in text:
        raise SystemExit("NORMALIZATION_FAILED:old_omega_import")
    return text


def blocks(body: str):
    lines = body.splitlines(keepends=True)
    starts = []
    for idx, line in enumerate(lines):
        if re.match(r"^(structure|def|theorem)\s+", line):
            starts.append(idx)
    starts.append(len(lines))
    out = []
    for a, b in zip(starts, starts[1:]):
        block = "".join(lines[a:b]).rstrip() + "\n"
        kind = re.match(r"^(structure|def|theorem)\s+", lines[a]).group(1)
        out.append((kind, block))
    return out


def theorem_name_and_statement(block: str):
    first = block.splitlines()[0]
    m = re.match(r"^theorem\s+([A-Za-z0-9_]+)\s*:\s*(.*?)\s*:=\s*(.*)$", first)
    if not m:
        raise SystemExit(f"UNSUPPORTED_THEOREM_HEADER:{first}")
    return m.group(1), m.group(2)


raw = SRC.read_text()
normalized = normalize(raw)
if "sorry" in normalized:
    raise SystemExit("SOURCE_CONTAINS_SORRY")

m = re.search(r"namespace C\nopen P\n(?P<body>.*)\nend C\s*$", normalized, re.S)
if not m:
    raise SystemExit("NAMESPACE_SHAPE_MISMATCH")
body = m.group("body")
parsed = blocks(body)

def_blocks = [b for kind, b in parsed if kind in {"structure", "def"}]
thm_blocks = [b for kind, b in parsed if kind == "theorem"]

names = []
challenge_thms = []
for b in thm_blocks:
    name, statement = theorem_name_and_statement(b)
    names.append(f"C.{name}")
    challenge_thms.append(f"theorem {name} : {statement} := by\n  sorry\n")

if names != EXPECTED:
    raise SystemExit("THEOREM_SET_OR_ORDER_MISMATCH:" + json.dumps(names))

normalized_path = ROOT / "ConcreteNormalized.lean"
defs_path = ROOT / "ConcreteDefs.lean"
challenge_path = ROOT / "ConcreteChallenge.lean"
solution_path = ROOT / "ConcreteSolution.lean"
config_path = ROOT / "comparator_concrete.json"
lake_path = ROOT / "lakefile.toml"

normalized_path.write_text(normalized)
defs_path.write_text("import Defs\n\nnamespace C\nopen P\n\n" + "\n".join(def_blocks) + "\nend C\n")
challenge_path.write_text("import ConcreteDefs\n\nnamespace C\nopen P\n\n" + "\n".join(challenge_thms) + "\nend C\n")
solution_path.write_text(
    "import ConcreteDefs\nimport Solution\nimport Lean.Elab.Tactic.Omega\n\nnamespace C\nopen P\n\n"
    + "\n".join(thm_blocks)
    + "\nend C\n"
)
config_path.write_text(json.dumps({
    "challenge_module": "ConcreteChallenge",
    "solution_module": "ConcreteSolution",
    "theorem_names": EXPECTED,
    "permitted_axioms": ["propext", "Quot.sound", "Classical.choice"],
    "enable_nanoda": True,
}, indent=2) + "\n")
lake_path.write_text(
    'name = "j4b2c82ad"\n'
    'version = "0.1.0"\n'
    'defaultTargets = ["P"]\n\n'
    '[[lean_lib]]\n'
    'name = "P"\n'
    'roots = ["Defs", "Challenge", "Solution", "ConcreteDefs", "ConcreteChallenge", "ConcreteSolution"]\n'
)

manifest = {
    "schema": "pc-target-integrity.concrete-gate.v1",
    "input_sha256": hashlib.sha256(raw.encode()).hexdigest(),
    "normalized_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
    "defs_sha256": sha(defs_path),
    "challenge_sha256": sha(challenge_path),
    "solution_sha256": sha(solution_path),
    "comparator_config_sha256": sha(config_path),
    "theorem_count": len(EXPECTED),
    "theorem_names": EXPECTED,
}
(ROOT / "concrete_gate_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest, sort_keys=True))
