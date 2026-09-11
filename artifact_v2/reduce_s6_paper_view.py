#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"ARTIFACT_V2_FAIL: {message}")


def fmt(value: float, places: int) -> str:
    return f"{float(value):.{places}f}"


def artifact_map(meta: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = meta.get("artifacts", [])
    require(isinstance(rows, list), "run artifact metadata malformed")
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("name")
        require(isinstance(name, str) and name, "artifact without name")
        require(name not in by_name, f"duplicate artifact name in run metadata: {name}")
        by_name[name] = row
    return by_name


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--authority-root", required=True)
    p.add_argument("--enforcement", required=True)
    p.add_argument("--source-manifest", required=True)
    p.add_argument("--run-artifacts-meta", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    root = Path(args.authority_root)
    source_path = Path(args.source_manifest)
    aggregate_path = root / "aggregate" / "S6_X86_FIRST_COMPLETE_AGGREGATE_V1.json"
    enforcement_path = Path(args.enforcement)
    run_open_path = root / "provenance" / "RUN_OPEN.json"

    source = load(source_path)
    aggregate = load(aggregate_path)
    enforcement = load(enforcement_path)
    run_open = load(run_open_path)
    run_meta = load(Path(args.run_artifacts_meta))

    expected_agg_sha = source["sealed_authority_artifact"]["aggregate_sha256"]
    actual_agg_sha = sha256(aggregate_path)
    require(actual_agg_sha == expected_agg_sha, "aggregate SHA-256 mismatch")
    require(
        enforcement.get("aggregate_authority_sha256") == actual_agg_sha,
        "enforcement does not bind the preserved aggregate",
    )
    require(
        enforcement.get("status") == source["sealed_enforcement_artifact"]["required_status"],
        "sealed enforcement is not complete authority",
    )
    require(enforcement.get("authority_rewritten") is False, "authority was rewritten")
    require(
        enforcement.get("thresholds_changed_after_observation") is False,
        "threshold changed after observation",
    )
    require(aggregate.get("unfavorable_results_preserved") is True, "unfavorable results not preserved")
    require(aggregate.get("completeness", {}).get("complete") is True, "aggregate incomplete")

    public = source["public_source_run"]
    require(run_open.get("public_run_id") == public["run_id"], "RUN_OPEN run mismatch")
    require(run_open.get("public_harness_head") == public["head_sha"], "RUN_OPEN head mismatch")
    require(run_open.get("scientific_code_changed_for_substrate") is False, "scientific code changed in public substrate")
    require(run_open.get("protocol_or_threshold_change") is False, "protocol/threshold changed in public substrate")
    require(run_open.get("selection_by_performance_value") is False, "performance-value selection detected")
    require(run_open.get("source_valid_records_rerun") is False, "valid inherited record rerun detected")

    continuation = aggregate.get("continuation_provenance", {})
    selection = continuation.get("selection_rule", {})
    require(selection.get("all_eligible_source_records_inherited") is True, "source inheritance was selective")
    require(selection.get("performance_values_consulted_to_select_inherited_or_missing_records") is False, "inherited data selected by performance")
    require(selection.get("source_record_rerun_permitted") is False, "source-record rerun was permitted")

    # GitHub's own run metadata binds the paper-positive runtime/anchor components
    # to this public run.  We do not infer freshness merely from filenames in the
    # aggregate, because the aggregate intentionally also contains immutable V5
    # continuation records.
    by_name = artifact_map(run_meta)
    fresh_meta: list[dict[str, Any]] = []
    for expected in source["fresh_public_claim_artifacts"]:
        row = by_name.get(expected["name"])
        require(row is not None, f"fresh public artifact missing: {expected['name']}")
        require(row.get("id") == expected["id"], f"artifact id mismatch: {expected['name']}")
        require(row.get("digest") == f"sha256:{expected['zip_sha256']}", f"artifact digest mismatch: {expected['name']}")
        require(row.get("expired") is False, f"source artifact already expired: {expected['name']}")
        wr = row.get("workflow_run", {})
        require(wr.get("id") == public["run_id"], f"artifact run mismatch: {expected['name']}")
        require(wr.get("head_sha") == public["head_sha"], f"artifact head mismatch: {expected['name']}")
        fresh_meta.append({
            "id": row["id"],
            "name": row["name"],
            "digest": row["digest"],
            "run_id": wr["id"],
            "head_sha": wr["head_sha"],
        })

    # Cross-check the fresh online records themselves.  The scientific estimator
    # remains the frozen aggregate; this only proves that the manuscript-positive
    # online timing inputs were measured on the public run rather than inherited.
    online_records = []
    for replica in ("A", "B"):
        path = root / "raw" / f"s6-online-f12-{replica}" / f"online-f12-{replica}.json"
        row = load(path)
        env = row.get("environment", {})
        require(str(env.get("github_run_id")) == str(public["run_id"]), f"online {replica} run mismatch")
        require(env.get("github_sha") == public["head_sha"], f"online {replica} head mismatch")
        require(row.get("all_qualified_specs_measured") is True, f"online {replica} incomplete")
        require(row.get("setup_errors") == [], f"online {replica} setup errors")
        online_records.append({
            "replica": replica,
            "json_sha256": sha256(path),
            "github_run_id": str(env["github_run_id"]),
            "github_sha": env["github_sha"],
            "runner_os": env.get("runner_os"),
            "runner_arch": env.get("runner_arch"),
            "python": env.get("python"),
            "cpu_model": env.get("cpu_model"),
        })

    fresh_runtime_records = []
    for replica in ("A", "B"):
        for stem, filename in (("e3b-budget", f"e3b-{replica}.json"), ("anchors", f"anchors-{replica}.json")):
            path = root / "raw" / f"s6-{stem}-{replica}" / filename
            row = load(path)
            require(row.get("performance_head") == public["head_sha"], f"{stem} {replica} head mismatch")
            require(row.get("status") == "QUALIFIED", f"{stem} {replica} not qualified")
            fresh_runtime_records.append({
                "kind": stem,
                "replica": replica,
                "json_sha256": sha256(path),
                "performance_head": row["performance_head"],
            })

    # Project the frozen authority into exactly the quantities stated in v91.
    f1 = aggregate["online_estimators"]["F1_online_N_decoupling"]
    blocks = f1["eligible_replica_seed_blocks"]
    n_sets = {tuple(row["N_levels"]) for row in blocks}
    require(len(n_sets) == 1, "F1 eligible blocks disagree on N levels")
    n_levels = list(next(iter(n_sets)))
    largest_ratio = max(float(row["max_min_p50_ratio"]) for row in blocks)
    all_flat = all(row.get("flat_predicate") is True for row in blocks)
    require(f1.get("empirically_flat_predicate") is True and all_flat, "F1 flatness not established")

    e3b_rows = []
    for replica_report in aggregate["real_E3b_100ms_budget"]:
        require(replica_report.get("status") == "QUALIFIED", "real E3b replica unqualified")
        for stratum, row in replica_report["strata"].items():
            e3b_rows.append({
                "replica": replica_report["replica"],
                "stratum": stratum,
                "p99_ns": float(row["summary_ns"]["p99_ns"]),
                "p99_9_ns": float(row["summary_ns"]["p99_9_ns"]),
                "p99_budget_percent": float(row["p99_budget_percent"]),
                "p99_9_budget_percent": float(row["p99_9_budget_percent"]),
            })
    worst_p99_ns = max(row["p99_ns"] for row in e3b_rows)
    worst_p99_9_ns = max(row["p99_9_ns"] for row in e3b_rows)
    worst_p99_pct = max(row["p99_budget_percent"] for row in e3b_rows)
    worst_p99_9_pct = max(row["p99_9_budget_percent"] for row in e3b_rows)

    thermostat_ms = []
    e3b_compile_ms = []
    peak_rss_bytes = []
    for report in aggregate["real_controller_anchors"]:
        require(report.get("status") == "QUALIFIED", "controller anchor replica unqualified")
        bt = report["anchors"]["better_thermostat"]["median_complete_metrics"]
        e3 = report["anchors"]["e3b"]["median_complete_metrics"]
        thermostat_ms.append(float(bt["q_compile_wall_ns"]) / 1_000_000.0)
        e3b_compile_ms.append(float(e3["full_compile_wall_ns"]) / 1_000_000.0)
        peak_rss_bytes.extend([float(bt["peak_rss_bytes"]), float(e3["peak_rss_bytes"])])

    interpretations = enforcement["interpretations"]
    positive_offline_scaling = not (
        interpretations.get("full_contract_wall_time") == "INSUFFICIENT_SUPPORT"
        and interpretations.get("q_only_wall_time") == "SEMANTIC_SEPARATION_NOT_ESTABLISHED"
    )

    projected = {
        "f1_online_N_levels": n_levels,
        "f1_eligible_replica_seed_blocks": len(blocks),
        "f1_all_blocks_flat": all_flat,
        "largest_p50_max_min_ratio_3dp": fmt(largest_ratio, 3),
        "worst_e3b_p99_ms_3dp": fmt(worst_p99_ns / 1_000_000.0, 3),
        "worst_e3b_p99_9_ms_3dp": fmt(worst_p99_9_ns / 1_000_000.0, 3),
        "worst_e3b_p99_budget_percent_3dp": fmt(worst_p99_pct, 3),
        "worst_e3b_p99_9_budget_percent_3dp": fmt(worst_p99_9_pct, 3),
        "thermostat_q_compile_median_ms_range_2dp": [fmt(min(thermostat_ms), 2), fmt(max(thermostat_ms), 2)],
        "e3b_full_compile_median_ms_range_1dp": [fmt(min(e3b_compile_ms), 1), fmt(max(e3b_compile_ms), 1)],
        "anchor_peak_rss_lt_decimal_mb": 30 if max(peak_rss_bytes) / 1_000_000.0 < 30.0 else None,
        "positive_offline_scaling_claim": positive_offline_scaling,
    }
    expected = source["paper_projection_v91"]
    require(projected == expected, f"authority projection does not match v91 paper claims: {projected!r}")

    receipt = {
        "schema": "replaymark.artifact-v2.s6-paper-view.v1",
        "status": "PASS_EXACT_V91_PROJECTION_FROM_SEALED_AUTHORITY",
        "source": {
            "public_run": public,
            "authority_artifact": source["sealed_authority_artifact"],
            "enforcement_artifact": source["sealed_enforcement_artifact"],
            "aggregate_sha256": actual_agg_sha,
            "enforcement_sha256": sha256(enforcement_path),
            "run_open_sha256": sha256(run_open_path),
        },
        "scientific_hygiene": {
            "aggregate_complete": True,
            "sealed_complete_authority": True,
            "authority_rewritten": False,
            "thresholds_changed_after_observation": False,
            "performance_value_selection": False,
            "source_valid_record_rerun": False,
            "unfavorable_results_preserved": True,
            "fresh_positive_runtime_and_anchor_components_bound_to_public_run": True,
            "inherited_V5_records_used_as_source_of_positive_paper_runtime_numbers": False,
        },
        "fresh_public_artifact_bindings": fresh_meta,
        "fresh_public_record_bindings": online_records + fresh_runtime_records,
        "paper_projection_v91": projected,
        "exact_unrounded": {
            "largest_p50_max_min_ratio": largest_ratio,
            "worst_e3b_p99_ns": worst_p99_ns,
            "worst_e3b_p99_9_ns": worst_p99_9_ns,
            "worst_e3b_p99_budget_percent": worst_p99_pct,
            "worst_e3b_p99_9_budget_percent": worst_p99_9_pct,
            "thermostat_q_compile_median_ms_by_replica": thermostat_ms,
            "e3b_full_compile_median_ms_by_replica": e3b_compile_ms,
            "max_anchor_peak_rss_bytes": max(peak_rss_bytes),
        },
        "frozen_interpretations": interpretations,
        "paper_scope": {
            "positive_online_F1_claim": interpretations.get("F1_online_N_decoupling"),
            "real_E3b_budget": interpretations.get("real_E3b_100ms_budget"),
            "offline_full_contract_scaling": interpretations.get("full_contract_wall_time"),
            "offline_q_scaling": interpretations.get("q_only_wall_time"),
            "stronger_offline_scaling_claim_permitted": False,
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("ARTIFACT_V2_S6_PAPER_VIEW=PASS")
    print(f"aggregate_sha256={actual_agg_sha}")
    print(f"largest_p50_ratio={largest_ratio}")
    print(f"worst_p99_ms={worst_p99_ns / 1_000_000.0}")
    print(f"worst_p99_9_ms={worst_p99_9_ns / 1_000_000.0}")


if __name__ == "__main__":
    main()
