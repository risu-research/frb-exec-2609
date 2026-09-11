#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import zipfile
from pathlib import Path
from typing import Any


def fail(message: str) -> None:
    raise SystemExit(f"ARTIFACT_V2_OFFLINE_FAIL: {message}")


def require(ok: bool, message: str) -> None:
    if not ok:
        fail(message)


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json_bytes(value: bytes) -> Any:
    return json.loads(value.decode("utf-8"))


def zip_read(zf: zipfile.ZipFile, name: str) -> bytes:
    require(name in zf.namelist(), f"missing zip member {name}")
    return zf.read(name)


def fmt(value: float, places: int) -> str:
    return f"{float(value):.{places}f}"


RAW_MAPPING = {
    "s6-online-f12-A": ("online-f12-A.json", "raw/s6-online-f12-A/online-f12-A.json"),
    "s6-online-f12-B": ("online-f12-B.json", "raw/s6-online-f12-B/online-f12-B.json"),
    "s6-e3b-budget-A": ("e3b-A.json", "raw/s6-e3b-budget-A/e3b-A.json"),
    "s6-e3b-budget-B": ("e3b-B.json", "raw/s6-e3b-budget-B/e3b-B.json"),
    "s6-anchors-A": ("anchors-A.json", "raw/s6-anchors-A/anchors-A.json"),
    "s6-anchors-B": ("anchors-B.json", "raw/s6-anchors-B/anchors-B.json"),
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-manifest", required=True)
    p.add_argument("--zips-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    source = json.loads(Path(args.source_manifest).read_text(encoding="utf-8"))
    zips_dir = Path(args.zips_dir)
    public = source["public_source_run"]
    authority = source["sealed_authority_artifact"]
    enforcement_manifest = source["sealed_enforcement_artifact"]

    authority_zip = zips_dir / f"{authority['name']}.zip"
    enforcement_zip = zips_dir / f"{enforcement_manifest['name']}.zip"
    require(sha_file(authority_zip) == authority["zip_sha256"], "authority zip digest mismatch")
    require(sha_file(enforcement_zip) == enforcement_manifest["zip_sha256"], "enforcement zip digest mismatch")

    with zipfile.ZipFile(authority_zip) as authority_zf, zipfile.ZipFile(enforcement_zip) as enforcement_zf:
        aggregate_bytes = zip_read(authority_zf, authority["aggregate_path"])
        require(sha_bytes(aggregate_bytes) == authority["aggregate_sha256"], "aggregate digest mismatch")
        aggregate = load_json_bytes(aggregate_bytes)
        companion = zip_read(authority_zf, "aggregate/S6_X86_FIRST_COMPLETE_AGGREGATE_V1.sha256").decode("utf-8")
        require(authority["aggregate_sha256"] in companion, "aggregate companion digest mismatch")
        run_open = load_json_bytes(zip_read(authority_zf, "provenance/RUN_OPEN.json"))

        members = enforcement_zf.namelist()
        require(members == [enforcement_manifest["enforcement_path"]], f"unexpected enforcement members: {members}")
        enforcement = load_json_bytes(zip_read(enforcement_zf, enforcement_manifest["enforcement_path"]))
        require(enforcement.get("aggregate_authority_sha256") == authority["aggregate_sha256"], "enforcement aggregate binding mismatch")
        require(enforcement.get("status") == enforcement_manifest["required_status"], "enforcement status mismatch")
        require(enforcement.get("authority_rewritten") is False, "authority rewritten")
        require(enforcement.get("thresholds_changed_after_observation") is False, "threshold changed after observation")
        require(aggregate.get("unfavorable_results_preserved") is True, "unfavorable results not preserved")
        require(aggregate.get("completeness", {}).get("complete") is True, "aggregate incomplete")
        require(aggregate.get("authority_status") == "AGGREGATED_BEFORE_VERDICT_ENFORCEMENT", "aggregate pre-enforcement status mismatch")

        require(run_open.get("public_run_id") == public["run_id"], "RUN_OPEN run mismatch")
        require(run_open.get("public_harness_head") == public["head_sha"], "RUN_OPEN head mismatch")
        for key in (
            "scientific_code_changed_for_substrate",
            "protocol_or_threshold_change",
            "selection_by_performance_value",
            "source_valid_records_rerun",
        ):
            require(run_open.get(key) is False, f"RUN_OPEN hygiene violated: {key}")

        selection = aggregate.get("continuation_provenance", {}).get("selection_rule", {})
        require(selection.get("all_eligible_source_records_inherited") is True, "source inheritance was selective")
        require(selection.get("performance_values_consulted_to_select_inherited_or_missing_records") is False, "performance-based source selection")
        require(selection.get("source_record_rerun_permitted") is False, "source-record rerun permitted")

        raw_docs: dict[str, Any] = {}
        for item in source["fresh_public_claim_artifacts"]:
            name = item["name"]
            path = zips_dir / f"{name}.zip"
            require(sha_file(path) == item["zip_sha256"], f"{name} zip digest mismatch")
            member, embedded = RAW_MAPPING[name]
            with zipfile.ZipFile(path) as zf:
                require(zf.namelist() == [member], f"{name} unexpected zip members")
                raw_bytes = zip_read(zf, member)
            require(sha_bytes(raw_bytes) == sha_bytes(zip_read(authority_zf, embedded)), f"{name} bytes differ from authority raw member")
            raw_docs[name] = load_json_bytes(raw_bytes)

        for replica in ("A", "B"):
            online = raw_docs[f"s6-online-f12-{replica}"]
            environment = online.get("environment", {})
            require(str(environment.get("github_run_id")) == str(public["run_id"]), f"online {replica} run mismatch")
            require(environment.get("github_sha") == public["head_sha"], f"online {replica} head mismatch")
            require(online.get("all_qualified_specs_measured") is True, f"online {replica} incomplete")
            require(online.get("setup_errors") == [], f"online {replica} setup errors")
            for stem in ("e3b-budget", "anchors"):
                row = raw_docs[f"s6-{stem}-{replica}"]
                require(row.get("performance_head") == public["head_sha"], f"{stem} {replica} head mismatch")
                require(row.get("status") == "QUALIFIED", f"{stem} {replica} not qualified")

        # Raw -> aggregate cross-check for the F1 headline ratio. The frozen
        # aggregate uses certify_reuse p50 over N={32,64,128,256} per replica/seed.
        raw_ratios: dict[tuple[str, int], float] = {}
        raw_n_levels: dict[tuple[str, int], list[int]] = {}
        for replica in ("A", "B"):
            online = raw_docs[f"s6-online-f12-{replica}"]
            rows = [
                row
                for row in online["condition_records"]
                if row.get("status") == "QUALIFIED"
                and row.get("entrypoint") == "certify_reuse"
                and row.get("spec", {}).get("family") == "F1"
            ]
            seeds = sorted({int(row["spec"]["seed"]) for row in rows})
            for seed in seeds:
                seed_rows = sorted(
                    [row for row in rows if int(row["spec"]["seed"]) == seed],
                    key=lambda row: int(row["spec"]["N"]),
                )
                n_levels = [int(row["spec"]["N"]) for row in seed_rows]
                p50_values = [float(row["summary_ns"]["p50_ns"]) for row in seed_rows]
                require(n_levels == [32, 64, 128, 256], f"F1 raw N levels mismatch {replica}/{seed}: {n_levels}")
                raw_ratios[(replica, seed)] = max(p50_values) / min(p50_values)
                raw_n_levels[(replica, seed)] = n_levels

        f1 = aggregate["online_estimators"]["F1_online_N_decoupling"]
        blocks = f1["eligible_replica_seed_blocks"]
        require(len(blocks) == 10, "F1 aggregate block count is not 10")
        for block in blocks:
            key = (block["replica"], int(block["seed"]))
            require(key in raw_ratios, f"F1 aggregate block missing raw evidence: {key}")
            require(abs(float(block["max_min_p50_ratio"]) - raw_ratios[key]) < 1e-15, f"F1 raw/aggregate ratio mismatch: {key}")
            require(list(block["N_levels"]) == raw_n_levels[key], f"F1 raw/aggregate N mismatch: {key}")
        largest_ratio = max(raw_ratios.values())
        all_flat = all(block.get("flat_predicate") is True for block in blocks) and f1.get("empirically_flat_predicate") is True

        raw_e3b = []
        for replica in ("A", "B"):
            report = raw_docs[f"s6-e3b-budget-{replica}"]
            for stratum, row in report["strata"].items():
                raw_e3b.append(
                    (
                        replica,
                        stratum,
                        float(row["summary_ns"]["p99_ns"]),
                        float(row["summary_ns"]["p99_9_ns"]),
                        float(row["p99_budget_percent"]),
                        float(row["p99_9_budget_percent"]),
                    )
                )
        aggregate_e3b = []
        for report in aggregate["real_E3b_100ms_budget"]:
            for stratum, row in report["strata"].items():
                aggregate_e3b.append(
                    (
                        report["replica"],
                        stratum,
                        float(row["summary_ns"]["p99_ns"]),
                        float(row["summary_ns"]["p99_9_ns"]),
                        float(row["p99_budget_percent"]),
                        float(row["p99_9_budget_percent"]),
                    )
                )
        require(sorted(raw_e3b) == sorted(aggregate_e3b), "E3b raw summaries differ from aggregate")
        worst_p99_ns = max(row[2] for row in raw_e3b)
        worst_p99_9_ns = max(row[3] for row in raw_e3b)
        worst_p99_percent = max(row[4] for row in raw_e3b)
        worst_p99_9_percent = max(row[5] for row in raw_e3b)

        thermostat_ms: list[float] = []
        e3b_compile_ms: list[float] = []
        peak_rss_bytes: list[float] = []
        aggregate_anchors = {row["replica"]: row for row in aggregate["real_controller_anchors"]}
        for replica in ("A", "B"):
            raw = raw_docs[f"s6-anchors-{replica}"]
            aggregate_row = aggregate_anchors[replica]
            for anchor, metric in (("better_thermostat", "q_compile_wall_ns"), ("e3b", "full_compile_wall_ns")):
                trials = [
                    float(trial["result"][metric])
                    for trial in raw["anchors"][anchor]["trials"]
                    if trial.get("terminal") == "COMPLETE"
                ]
                median = float(statistics.median(trials))
                require(median == float(raw["anchors"][anchor]["median_complete_metrics"][metric]), f"{anchor} {replica} raw median mismatch")
                require(median == float(aggregate_row["anchors"][anchor]["median_complete_metrics"][metric]), f"{anchor} {replica} aggregate median mismatch")
                if anchor == "better_thermostat":
                    thermostat_ms.append(median / 1_000_000.0)
                else:
                    e3b_compile_ms.append(median / 1_000_000.0)
                peak_rss_bytes.append(float(raw["anchors"][anchor]["median_complete_metrics"]["peak_rss_bytes"]))

        interpretations = enforcement["interpretations"]
        positive_offline_scaling = not (
            interpretations.get("full_contract_wall_time") == "INSUFFICIENT_SUPPORT"
            and interpretations.get("q_only_wall_time") == "SEMANTIC_SEPARATION_NOT_ESTABLISHED"
        )
        projected = {
            "f1_online_N_levels": [32, 64, 128, 256],
            "f1_eligible_replica_seed_blocks": len(blocks),
            "f1_all_blocks_flat": all_flat,
            "largest_p50_max_min_ratio_3dp": fmt(largest_ratio, 3),
            "worst_e3b_p99_ms_3dp": fmt(worst_p99_ns / 1_000_000.0, 3),
            "worst_e3b_p99_9_ms_3dp": fmt(worst_p99_9_ns / 1_000_000.0, 3),
            "worst_e3b_p99_budget_percent_3dp": fmt(worst_p99_percent, 3),
            "worst_e3b_p99_9_budget_percent_3dp": fmt(worst_p99_9_percent, 3),
            "thermostat_q_compile_median_ms_range_2dp": [fmt(min(thermostat_ms), 2), fmt(max(thermostat_ms), 2)],
            "e3b_full_compile_median_ms_range_1dp": [fmt(min(e3b_compile_ms), 1), fmt(max(e3b_compile_ms), 1)],
            "anchor_peak_rss_lt_decimal_mb": 30 if max(peak_rss_bytes) / 1_000_000.0 < 30.0 else None,
            "positive_offline_scaling_claim": positive_offline_scaling,
        }
        require(projected == source["paper_projection_v91"], f"paper projection mismatch: {projected!r}")

        receipt = {
            "schema": "replaymark.artifact-v2.offline-s6-verification.v1",
            "status": "PASS_SELF_CONTAINED_EXACT_V91_REPRODUCTION",
            "manuscript_snapshot": source["manuscript_snapshot"],
            "public_source_run": public,
            "verified_zip_sha256": {
                authority["name"]: authority["zip_sha256"],
                enforcement_manifest["name"]: enforcement_manifest["zip_sha256"],
                **{item["name"]: item["zip_sha256"] for item in source["fresh_public_claim_artifacts"]},
            },
            "aggregate_sha256": authority["aggregate_sha256"],
            "paper_projection_v91": projected,
            "exact_unrounded": {
                "largest_p50_max_min_ratio": largest_ratio,
                "worst_e3b_p99_ns": worst_p99_ns,
                "worst_e3b_p99_9_ns": worst_p99_9_ns,
                "worst_e3b_p99_budget_percent": worst_p99_percent,
                "worst_e3b_p99_9_budget_percent": worst_p99_9_percent,
                "thermostat_q_compile_median_ms_by_replica": thermostat_ms,
                "e3b_full_compile_median_ms_by_replica": e3b_compile_ms,
                "max_anchor_peak_rss_bytes": max(peak_rss_bytes),
            },
            "hygiene": {
                "authority_zip_exact": True,
                "fresh_claim_zips_exact": True,
                "fresh_claim_bytes_identical_to_authority_raw_members": True,
                "raw_to_aggregate_cross_checks": True,
                "aggregate_status": "AGGREGATED_BEFORE_VERDICT_ENFORCEMENT",
                "sealed_complete_enforcement": True,
                "authority_rewritten": False,
                "thresholds_changed_after_observation": False,
                "performance_value_selection": False,
                "source_valid_record_rerun": False,
                "unfavorable_results_preserved": True,
                "stronger_offline_scaling_claim_permitted": False,
            },
            "frozen_interpretations": interpretations,
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("ARTIFACT_V2_OFFLINE_VERIFY=PASS")
    print(f"largest_p50_ratio={largest_ratio}")
    print(f"worst_p99_ms={worst_p99_ns / 1_000_000.0}")
    print(f"worst_p99_9_ms={worst_p99_9_ns / 1_000_000.0}")


if __name__ == "__main__":
    main()
