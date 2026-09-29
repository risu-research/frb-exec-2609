#!/usr/bin/env python3
"""Reconstruct and verify the frozen registry-defined empirical target, then sample it.

The script deliberately aborts if the live OpenML registry no longer matches the
freeze used to design the experiment. This prevents silent population drift.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from run_study import add_meta, build_problem_frame, get_openml_registry, get_suite_task_ids

FREEZE_DIGEST = "b38bab764eae61fe5d90679b061c0694246eb1c908c7d89a47a842003bc39e40"
EXPECTED_TASK_OBJECTS = 5577
EXPECTED_PROBLEMS = 2812
EXPECTED_EMPIRICAL_N = 2336
EXPECTED_CC18 = 72
SAMPLE_SEED = 260930
NON_CC18_SAMPLE_N = 288
EXPECTED_STRATA = {
    "CC18_CERTAINTY": 72,
    "L_R_I": 87,
    "L_R_R": 246,
    "M_H_I": 2,
    "M_H_R": 4,
    "M_R_I": 141,
    "M_R_R": 1402,
    "S_H_I": 1,
    "S_H_R": 8,
    "S_R_R": 373,
}

DIGEST_FIELDS = [
    "problem_id", "did", "target_feature", "min_task_id", "NumberOfInstances",
    "NumberOfFeatures", "MinorityClassSize", "MajorityClassSize",
    "NumberOfClasses", "meta_minority_majority_ratio", "in_cc18",
]


def canon(v):
    if pd.isna(v):
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return round(float(v), 12)
    return str(v)


def frame_digest(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.sort_values("problem_id").iterrows():
        rows.append([canon(r[f]) for f in DIGEST_FIELDS])
    blob = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def empirical_eligibility(p: pd.DataFrame) -> pd.Series:
    n = pd.to_numeric(p["NumberOfInstances"], errors="coerce")
    d = pd.to_numeric(p["NumberOfFeatures"], errors="coerce")
    m = pd.to_numeric(p["MinorityClassSize"], errors="coerce")
    k = pd.to_numeric(p["NumberOfClasses"], errors="coerce")
    # Outcome-independent evaluation-validity/resource envelope. These are NOT
    # CC18's thresholds: the frame retains n<500, n>100k, severe imbalance and
    # raw p>5000 regions.
    return n.between(40, 1_000_000) & (d <= 10_000) & (m >= 5) & (k <= 100)


def stratum_of(r: pd.Series) -> str:
    if bool(r["in_cc18"]):
        return "CC18_CERTAINTY"
    n = float(r["NumberOfInstances"])
    p = float(r["NumberOfFeatures"])
    ratio = float(r["meta_minority_majority_ratio"])
    size = "S" if n < 500 else ("L" if n > 100_000 else "M")
    dim = "H" if p > 5000 else "R"
    imb = "I" if ratio <= 0.05 else "R"
    return f"{size}_{dim}_{imb}"


def allocate_sqrt(counts: dict[str, int], total: int) -> dict[str, int]:
    # Small cells get a minimum census-like floor; remaining draws are assigned
    # by a deterministic square-root allocation, oversampling rare support cells
    # relative to proportional allocation while preserving known inclusion probs.
    alloc = {h: min(8, N) for h, N in counts.items()}
    remaining = total - sum(alloc.values())
    if remaining < 0:
        raise RuntimeError("Sampling floor exceeds requested sample size")
    while remaining:
        eligible = [h for h, N in counts.items() if alloc[h] < N]
        if not eligible:
            raise RuntimeError("No capacity left before sample allocation completed")
        h = max(eligible, key=lambda z: (counts[z] ** 0.5) / (alloc[z] + 1))
        alloc[h] += 1
        remaining -= 1
    return alloc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="fresh_prep")
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    openml, tasks = get_openml_registry()
    cc18 = get_suite_task_ids(openml, 99)
    task_frame, problems = build_problem_frame(tasks, cc18, [])
    problems = add_meta(problems)

    if len(task_frame) != EXPECTED_TASK_OBJECTS:
        raise RuntimeError(f"Registry drift: task objects {len(task_frame)} != {EXPECTED_TASK_OBJECTS}")
    if len(problems) != EXPECTED_PROBLEMS:
        raise RuntimeError(f"Registry drift: problems {len(problems)} != {EXPECTED_PROBLEMS}")
    digest = frame_digest(problems)
    if digest != FREEZE_DIGEST:
        raise RuntimeError(f"Registry drift: problem-frame digest {digest} != {FREEZE_DIGEST}")

    empirical = problems.loc[empirical_eligibility(problems)].copy()
    empirical["sampling_stratum"] = empirical.apply(stratum_of, axis=1)
    if len(empirical) != EXPECTED_EMPIRICAL_N:
        raise RuntimeError(f"Empirical frame drift: {len(empirical)} != {EXPECTED_EMPIRICAL_N}")
    if int(empirical.in_cc18.sum()) != EXPECTED_CC18:
        raise RuntimeError(f"CC18 coverage drift: {int(empirical.in_cc18.sum())} != {EXPECTED_CC18}")
    counts = empirical.sampling_stratum.value_counts().sort_index().to_dict()
    if counts != EXPECTED_STRATA:
        raise RuntimeError(f"Stratum drift: {counts} != {EXPECTED_STRATA}")

    non_counts = {h: N for h, N in counts.items() if h != "CC18_CERTAINTY"}
    alloc = allocate_sqrt(non_counts, NON_CC18_SAMPLE_N)
    rng = np.random.default_rng(SAMPLE_SEED)
    sampled = []
    for h, g in empirical.groupby("sampling_stratum", sort=True):
        N = len(g)
        if h == "CC18_CERTAINTY":
            s = g.copy(); n = N
        else:
            n = alloc[h]
            chosen = rng.choice(g.index.to_numpy(), size=n, replace=False)
            s = empirical.loc[chosen].copy()
        s["stratum_N"] = N
        s["stratum_n"] = n
        s["inclusion_probability"] = n / N
        s["design_weight"] = N / n
        sampled.append(s)
    sample = pd.concat(sampled, ignore_index=True)
    sample = sample.iloc[rng.permutation(len(sample))].reset_index(drop=True)
    sample["sample_order"] = np.arange(len(sample))
    sample["shard_12"] = sample.sample_order % 12
    sample["retrieval_task_id"] = pd.to_numeric(sample["min_task_id"], errors="coerce").fillna(sample["tid"]).astype(int)

    cols = [
        "sample_order", "shard_12", "problem_id", "did", "target_feature",
        "retrieval_task_id", "name", "NumberOfInstances", "NumberOfFeatures",
        "MinorityClassSize", "MajorityClassSize", "NumberOfClasses",
        "meta_minority_majority_ratio", "in_cc18", "sampling_stratum",
        "stratum_N", "stratum_n", "inclusion_probability", "design_weight",
    ]
    sample[cols].to_csv(out / "fresh_probability_sample_manifest.csv", index=False)
    empirical[[
        "problem_id", "did", "target_feature", "min_task_id", "name",
        "NumberOfInstances", "NumberOfFeatures", "MinorityClassSize",
        "MajorityClassSize", "NumberOfClasses", "meta_minority_majority_ratio",
        "in_cc18", "sampling_stratum",
    ]].to_csv(out / "fresh_empirical_target_frame.csv", index=False)

    design = {
        "registry_problem_frame_sha256": digest,
        "sampling_seed": SAMPLE_SEED,
        "empirical_target_N": len(empirical),
        "cc18_certainty_N": int(empirical.in_cc18.sum()),
        "non_cc18_target_N": int((~empirical.in_cc18.astype(bool)).sum()),
        "non_cc18_sample_n": NON_CC18_SAMPLE_N,
        "total_fresh_sample_n": len(sample),
        "eligibility": {
            "NumberOfInstances_min": 40,
            "NumberOfInstances_max": 1_000_000,
            "NumberOfFeatures_max": 10_000,
            "MinorityClassSize_min": 5,
            "NumberOfClasses_max": 100,
        },
        "strata_counts": counts,
        "strata_sample_n": sample.sampling_stratum.value_counts().sort_index().to_dict(),
    }
    (out / "fresh_sampling_design.json").write_text(json.dumps(design, indent=2, sort_keys=True) + "\n")
    print("FRESH_SAMPLING_DESIGN=" + json.dumps(design, sort_keys=True))


if __name__ == "__main__":
    main()
