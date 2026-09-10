from __future__ import annotations

"""Static scientific-hygiene verifier for the VE1 public execution capsule."""

import ast
import hashlib
import json
from pathlib import Path

STATE_PATH = Path("VE1_EXECUTION_STATE_MANIFEST_V1_MIRROR.json")
PRODUCER = Path("ve1_native_execution.py")
VALIDATOR = Path("ve1_independent_validate.py")
ADJUDICATOR = Path("ve1_postrun_adjudicate.py")
E0Q = Path("ve1_e0q_runtime.py")
SCIENCE_WORKFLOW = Path(".github/workflows/ve1-authoritative-first-complete-v1.yml")
E0Q_WORKFLOW = Path(".github/workflows/ve1-e0q-v1.yml")
ROWS_SHA256 = "0ef80acf64bcc192837ee17f6b57ab2e79ee4182c9b793d8cf388d59d2558c20"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def _expected_states() -> list[dict[str, object]]:
    out = []
    index = 0
    for presence in (False, True):
        for motion in (False, True):
            for night in (False, True):
                for current in ("away", "home", "comfort", "sleep"):
                    out.append({
                        "opaque_state_id": f"VE1-S{index:02d}",
                        "fixture": {
                            "presence": presence,
                            "motion": motion,
                            "night": night,
                            "current_preset": current,
                        },
                    })
                    index += 1
    return out


def _verify_manifest() -> dict[str, object]:
    value = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    assert value["schema"] == "replaymark.ve1.execution-state-manifest.v1"
    assert value["status"] == "FROZEN_PRE_SCIENTIFIC_EXECUTION"
    assert value["state_count"] == 32
    assert value["states"] == _expected_states()
    raw = json.dumps(value["states"], sort_keys=True)
    for token in (
        "target_preset", "old_expected_action", "new_expected_action",
        "compatibility", "expected_counts", "COMPATIBLE_ACROSS_VERSION",
        "RETIRED_BY_UPDATE",
    ):
        assert token not in raw, token
    return {
        "state_count": 32,
        "states_sha256": hashlib.sha256(
            json.dumps(value["states"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _verify_independence() -> dict[str, object]:
    validator_imports = _imports(VALIDATOR)
    validator_allowed = {
        "__future__", "argparse", "hashlib", "json", "pathlib", "typing"
    }
    assert validator_imports <= validator_allowed, sorted(validator_imports - validator_allowed)
    adjudicator_imports = _imports(ADJUDICATOR)
    adjudicator_allowed = {
        "__future__", "argparse", "hashlib", "json", "pathlib", "typing"
    }
    assert adjudicator_imports <= adjudicator_allowed, sorted(adjudicator_imports - adjudicator_allowed)
    return {
        "validator_imports": sorted(validator_imports),
        "adjudicator_imports": sorted(adjudicator_imports),
    }


def _verify_firewall() -> dict[str, object]:
    text = PRODUCER.read_text(encoding="utf-8")
    assert "VE1_EXPECTED_CROSS_VERSION_TABLE_V2" not in text
    assert ROWS_SHA256 not in text
    assert "compile_c2_contract(0)" in text
    assert "HaBtCertifiedExecutionGate" in text
    assert "subprocess" not in text
    assert "git diff" not in text
    assert "source_diff" not in text
    assert "source-diff" not in text
    assert "new_direct" in text and "replaymark" in text and "replay_all" in text
    for token in (
        "target_preset", "old_expected_action", "new_expected_action",
        "compatibility", "expected_counts", "COMPATIBLE_ACROSS_VERSION",
        "RETIRED_BY_UPDATE",
    ):
        assert text.count(token) == 1, (token, text.count(token))
    e0q = E0Q.read_text(encoding="utf-8")
    assert "VE1_EXECUTION_STATE_MANIFEST" not in e0q
    assert "611723a7cffd7cbc151afd0415c1a705900754f1" not in e0q
    assert "da6b8f90fa38d91b82f2ec301195f2ef4461deea" not in e0q
    assert "ve1_result_bearing_controller_installed" in e0q
    return {"producer_answer_table_access": False, "e0q_ve1_source_pin_access": False}


def _verify_workflows() -> dict[str, object]:
    science = SCIENCE_WORKFLOW.read_text(encoding="utf-8")
    e0q = E0Q_WORKFLOW.read_text(encoding="utf-8")
    required_science = (
        "GITHUB_RUN_ATTEMPT",
        "fail-fast: false",
        "replica: [0, 1]",
        "VE1_SCIENTIFIC_AUTHORITY_OPEN_V1.json",
        "docker run --rm --network none",
        "old_history",
        "new_direct",
        "replaymark",
        "replay_all",
        "ve1_postrun_adjudicate.py",
        "if: always()",
    )
    for token in required_science:
        assert token in science, token
    stage_calls = ("run_stage old_history ", "run_stage new_direct ", "run_stage replaymark ", "run_stage replay_all ")
    positions = [science.index(x) for x in stage_calls]
    assert positions == sorted(positions), positions
    assert '-v "$PWD/results/new_direct' not in science
    assert '-v "$PWD:/' not in science
    assert "VE1_EXPECTED_CROSS_VERSION_TABLE_V2.json" not in science
    assert "EXPECTED_ROWS_CANONICAL.json" not in science
    assert "611723a7cffd7cbc151afd0415c1a705900754f1" not in e0q
    assert "da6b8f90fa38d91b82f2ec301195f2ef4461deea" not in e0q
    assert "VE1_E0Q_AUTHORITY_OPEN_V1.json" in e0q
    assert "docker run --rm --network none" in e0q
    return {"science_stage_order": ["old_history", "new_direct", "replaymark", "replay_all"]}


def main() -> None:
    result = {
        "schema": "replaymark.ve1.execution-capsule-static-audit.v2",
        "status": "PASS",
        "scientific_result_opened": False,
        "manifest": _verify_manifest(),
        "independence": _verify_independence(),
        "firewall": _verify_firewall(),
        "workflows": _verify_workflows(),
    }
    Path("static-results").mkdir(exist_ok=True)
    Path("static-results/VE1_EXECUTION_CAPSULE_STATIC_AUDIT_V2.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "scientific_result_opened": False}, sort_keys=True))


if __name__ == "__main__":
    main()
