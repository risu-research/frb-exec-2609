#!/usr/bin/env python3
"""Freeze an OpenML classification target frame and run a public-outcome validation study.

This script intentionally separates:
  1) a live OpenML task/dataset population audit,
  2) OpenML-CC18 membership/support diagnostics, and
  3) a historical public TabZilla outcome matrix used as an outcome-rich validation oracle.

No new model is trained here. The point is to decide whether the selection x algorithm
performance interaction is strong enough to justify fresh large-scale execution.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from scipy import stats

OUT = Path(os.environ.get("OUT_DIR", "out"))
OUT.mkdir(parents=True, exist_ok=True)
SEED = 260929
RNG = np.random.default_rng(SEED)
BOOT = int(os.environ.get("BOOT_REPS", "5000"))
TABZILLA_COMMIT = "feca5e554148bdc4ac17c3379984c2a71244cd32"
RAW_BASE = f"https://raw.githubusercontent.com/naszilla/tabzilla/{TABZILLA_COMMIT}"
URL_COMPLETE = RAW_BASE + "/tabzilla_analysis/final-selected18-algs/cleaned_results/tuned_aggregated_results.csv"
URL_BROAD = RAW_BASE + "/tabzilla_analysis/results/tuned_aggregated_results.csv"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def download_csv(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest = OUT / ("source_" + url.rsplit("/", 1)[-1].replace(".csv", "") + "_" + str(abs(hash(url))) + ".csv")
    dest.write_bytes(r.content)
    return pd.read_csv(dest)


def robust_openml_registry():
    import openml
    try:
        from openml.tasks import TaskType
        task_type = TaskType.SUPERVISED_CLASSIFICATION
    except Exception:
        task_type = 1

    # Primary route: Python client, which handles pagination and schema normalization.
    try:
        tasks = openml.tasks.list_tasks(task_type=task_type, output_format="dataframe")
        if not isinstance(tasks, pd.DataFrame):
            tasks = pd.DataFrame(tasks).T
    except Exception as e:
        print("openml.tasks.list_tasks failed, trying REST fallback:", repr(e), file=sys.stderr)
        url = "https://www.openml.org/api/v1/json/task/list/type/1/limit/10000"
        j = requests.get(url, timeout=120).json()
        rows = j.get("tasks", {}).get("task", [])
        tasks = pd.DataFrame(rows)

    tasks = tasks.reset_index(drop=False)
    rename = {}
    for c in tasks.columns:
        cl = str(c).lower()
        if cl in {"task_id", "tid"}:
            rename[c] = "tid"
        elif cl in {"data_id", "did"}:
            rename[c] = "did"
    tasks = tasks.rename(columns=rename)
    if "tid" not in tasks.columns:
        if "index" in tasks.columns:
            tasks = tasks.rename(columns={"index": "tid"})
        else:
            raise RuntimeError(f"No task id column in {list(tasks.columns)}")
    tasks["tid"] = pd.to_numeric(tasks["tid"], errors="coerce").astype("Int64")
    if "did" in tasks.columns:
        tasks["did"] = pd.to_numeric(tasks["did"], errors="coerce").astype("Int64")

    # Active dataset registry supplies both status and standard OpenML qualities.
    try:
        dsets = openml.datasets.list_datasets(status="active", output_format="dataframe")
        if not isinstance(dsets, pd.DataFrame):
            dsets = pd.DataFrame(dsets).T
    except TypeError:
        dsets = openml.datasets.list_datasets(output_format="dataframe")
        if not isinstance(dsets, pd.DataFrame):
            dsets = pd.DataFrame(dsets).T
        if "status" in dsets.columns:
            dsets = dsets.loc[dsets["status"].astype(str).str.lower().eq("active")]
    dsets = dsets.reset_index(drop=False)
    drename = {}
    for c in dsets.columns:
        cl = str(c).lower()
        if cl in {"data_id", "did"}:
            drename[c] = "did"
    dsets = dsets.rename(columns=drename)
    if "did" not in dsets.columns and "index" in dsets.columns:
        dsets = dsets.rename(columns={"index": "did"})
    dsets["did"] = pd.to_numeric(dsets["did"], errors="coerce").astype("Int64")

    return openml, tasks, dsets


def get_suite_ids(openml, suite_id):
    try:
        s = openml.study.get_suite(suite_id)
        return sorted(map(int, s.tasks)), sorted(map(int, s.data_ids if hasattr(s, "data_ids") else []))
    except Exception:
        # REST fallback.
        j = requests.get(f"https://www.openml.org/api/v1/json/study/{suite_id}", timeout=120).json()
        st = j.get("study", j)
        tids = st.get("tasks", {}).get("task", []) if isinstance(st, dict) else []
        if tids and isinstance(tids[0], dict):
            tids = [x.get("task_id", x.get("id")) for x in tids]
        dids = st.get("data", {}).get("dataset", []) if isinstance(st, dict) else []
        if dids and isinstance(dids[0], dict):
            dids = [x.get("data_id", x.get("id")) for x in dids]
        return sorted(int(x) for x in tids if x is not None), sorted(int(x) for x in dids if x is not None)


def find_col(df, names):
    lut = {str(c).lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lut:
            return lut[n.lower()]
    return None


def build_population(tasks: pd.DataFrame, dsets: pd.DataFrame, cc18_tids, cc18_dids, tab_tids, tab_dids):
    tasks = tasks.copy()
    dsets = dsets.copy()
    tasks["in_cc18_task"] = tasks["tid"].astype("Int64").isin(cc18_tids)
    tasks["in_tabzilla379_task"] = tasks["tid"].astype("Int64").isin(tab_tids)
    if "did" in tasks.columns:
        tasks["in_cc18_data"] = tasks["did"].astype("Int64").isin(cc18_dids)
        tasks["in_tabzilla379_data"] = tasks["did"].astype("Int64").isin(tab_dids)
    else:
        tasks["in_cc18_data"] = False
        tasks["in_tabzilla379_data"] = False

    # Avoid accidental duplicate columns by suffixing dataset metadata.
    if "did" in tasks.columns:
        merged = tasks.merge(dsets, on="did", how="left", suffixes=("_task", "_data"), indicator="_dataset_join")
    else:
        merged = tasks.copy()
        merged["_dataset_join"] = "unknown"

    # Main task-object frame: all supervised classification tasks whose underlying dataset is active.
    target = merged.loc[merged["_dataset_join"].eq("both")].copy() if "_dataset_join" in merged else merged.copy()

    # Canonical dataset-target sensitivity frame. We do not use it to redefine the main estimand.
    target_feature = find_col(target, ["target_feature", "target_name", "target_feature_task"])
    keys = ["did"] if "did" in target.columns else ["tid"]
    if target_feature:
        keys.append(target_feature)
    canonical = target.sort_values("tid").drop_duplicates(keys, keep="first").copy()

    return merged, target, canonical


def numeric_series(df, aliases):
    c = find_col(df, aliases)
    if c is None:
        return None, None
    return c, pd.to_numeric(df[c], errors="coerce")


def add_derived_metadata(df):
    df = df.copy()
    c_n, n = numeric_series(df, ["NumberOfInstances", "number_of_instances"])
    c_p, p = numeric_series(df, ["NumberOfFeatures", "number_of_features"])
    c_min, mn = numeric_series(df, ["MinorityClassSize", "minority_class_size"])
    c_max, mx = numeric_series(df, ["MajorityClassSize", "majority_class_size"])
    c_cls, cls = numeric_series(df, ["NumberOfClasses", "number_of_classes"])
    c_miss, miss = numeric_series(df, ["NumberOfMissingValues", "number_of_missing_values"])
    if n is not None:
        df["meta_log1p_instances"] = np.log1p(n)
        df["cc18_proxy_under_500"] = n < 500
        df["cc18_proxy_over_100k"] = n > 100000
    if p is not None:
        df["meta_log1p_features"] = np.log1p(p)
        df["cc18_proxy_over_5000_raw_features"] = p > 5000
    if n is not None and p is not None:
        df["meta_feature_instance_ratio"] = p / n.replace(0, np.nan)
    if mn is not None and mx is not None:
        df["meta_minority_majority_ratio"] = mn / mx.replace(0, np.nan)
        df["cc18_proxy_imbalance_le_005"] = df["meta_minority_majority_ratio"] <= 0.05
        df["cc18_proxy_minority_lt20"] = mn < 20
    if cls is not None:
        df["meta_classes"] = cls
    if miss is not None and n is not None and p is not None:
        denom = n * p
        df["meta_missing_fraction"] = miss / denom.replace(0, np.nan)
    proxy_cols = [c for c in df.columns if str(c).startswith("cc18_proxy_")]
    if proxy_cols:
        df["cc18_known_numeric_proxy_exclusion"] = df[proxy_cols].fillna(False).any(axis=1)
    return df


def balance_table(df):
    metrics = [
        "meta_log1p_instances", "meta_log1p_features", "meta_feature_instance_ratio",
        "meta_minority_majority_ratio", "meta_classes", "meta_missing_fraction"
    ]
    rows = []
    sflag = df["in_cc18_task"].astype(bool) | df["in_cc18_data"].astype(bool)
    for m in metrics:
        if m not in df.columns:
            continue
        x = pd.to_numeric(df.loc[sflag, m], errors="coerce").dropna().to_numpy(float)
        y = pd.to_numeric(df.loc[~sflag, m], errors="coerce").dropna().to_numpy(float)
        z = pd.to_numeric(df[m], errors="coerce").dropna().to_numpy(float)
        if len(x) < 2 or len(y) < 2:
            continue
        pooled = math.sqrt(((len(x)-1)*np.var(x, ddof=1) + (len(y)-1)*np.var(y, ddof=1)) / max(len(x)+len(y)-2, 1))
        smd = (np.mean(x)-np.mean(y))/pooled if pooled > 0 else np.nan
        ks = stats.ks_2samp(x, y, alternative="two-sided", method="auto")
        rows.append({
            "metric": m,
            "n_cc18": len(x), "n_non_cc18": len(y), "n_all": len(z),
            "cc18_mean": np.mean(x), "non_cc18_mean": np.mean(y), "all_mean": np.mean(z),
            "cc18_median": np.median(x), "non_cc18_median": np.median(y), "all_median": np.median(z),
            "standardized_mean_difference_cc18_minus_non": smd,
            "ks_statistic": ks.statistic, "ks_pvalue_descriptive_only": ks.pvalue,
        })
    return pd.DataFrame(rows)


def parse_tid(name):
    m = re.search(r"__(\d+)$", str(name))
    return int(m.group(1)) if m else np.nan


def ci_boot_mean(x, reps=BOOT, rng=None):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return (np.nan, np.nan)
    rng = rng or RNG
    # Chunk to avoid large temporary matrices.
    vals = np.empty(reps)
    for i in range(reps):
        vals[i] = rng.choice(x, size=len(x), replace=True).mean()
    return tuple(np.quantile(vals, [0.025, 0.975]))


def ci_boot_diff_means(x, y, reps=BOOT, rng=None):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    y = np.asarray(y, float); y = y[np.isfinite(y)]
    if len(x) < 2 or len(y) < 2:
        return (np.nan, np.nan)
    rng = rng or RNG
    vals = np.empty(reps)
    for i in range(reps):
        vals[i] = rng.choice(x, size=len(x), replace=True).mean() - rng.choice(y, size=len(y), replace=True).mean()
    return tuple(np.quantile(vals, [0.025, 0.975]))


def pairwise_matrix(df, cc18_tids, label, metric="Accuracy__test_mean"):
    d = df.copy()
    if "dataset_name" not in d.columns or "alg_name" not in d.columns or metric not in d.columns:
        raise RuntimeError(f"Required columns missing in {label}: {list(d.columns)}")
    d["tid"] = d["dataset_name"].map(parse_tid)
    d[metric] = pd.to_numeric(d[metric], errors="coerce")
    d = d.dropna(subset=["tid", metric])
    d["tid"] = d["tid"].astype(int)
    d["in_cc18"] = d["tid"].isin(cc18_tids)
    algs = sorted(d["alg_name"].dropna().unique().tolist())
    rows = []
    for a, b in itertools.combinations(algs, 2):
        da = d.loc[d.alg_name.eq(a), ["tid", metric, "in_cc18"]].rename(columns={metric: "ya"})
        db = d.loc[d.alg_name.eq(b), ["tid", metric]].rename(columns={metric: "yb"})
        m = da.merge(db, on="tid", how="inner")
        m["diff"] = m.ya - m.yb
        allv = m["diff"].to_numpy(float)
        inv = m.loc[m.in_cc18, "diff"].to_numpy(float)
        outv = m.loc[~m.in_cc18, "diff"].to_numpy(float)
        if len(allv) == 0:
            continue
        dt = float(np.mean(allv))
        di = float(np.mean(inv)) if len(inv) else np.nan
        do = float(np.mean(outv)) if len(outv) else np.nan
        cit = ci_boot_mean(allv, rng=RNG)
        cii = ci_boot_mean(inv, rng=RNG) if len(inv)>=2 else (np.nan,np.nan)
        cio = ci_boot_mean(outv, rng=RNG) if len(outv)>=2 else (np.nan,np.nan)
        cix = ci_boot_diff_means(inv, outv, rng=RNG) if len(inv)>=2 and len(outv)>=2 else (np.nan,np.nan)
        pi = len(inv)/len(allv)
        # Retrospective partial identification if only CC18 outcomes were observed and diff in [-1,1].
        if len(inv):
            lo = pi*di + (1-pi)*(-1.0)
            hi = pi*di + (1-pi)*(+1.0)
        else:
            lo, hi = -1.0, 1.0
        identified = "a>b" if lo > 0 else ("a<b" if hi < 0 else "unidentified")
        rows.append({
            "validation_frame": label, "metric": metric, "algorithm_a": a, "algorithm_b": b,
            "n_pair_target": len(allv), "n_pair_cc18": len(inv), "n_pair_non_cc18": len(outv),
            "coverage_pi": pi,
            "delta_target_a_minus_b": dt, "delta_target_ci_low": cit[0], "delta_target_ci_high": cit[1],
            "delta_cc18_a_minus_b": di, "delta_cc18_ci_low": cii[0], "delta_cc18_ci_high": cii[1],
            "delta_non_cc18_a_minus_b": do, "delta_non_cc18_ci_low": cio[0], "delta_non_cc18_ci_high": cio[1],
            "suite_to_target_bias": di-dt if np.isfinite(di) else np.nan,
            "interaction_cc18_minus_non": di-do if np.isfinite(di) and np.isfinite(do) else np.nan,
            "interaction_ci_low": cix[0], "interaction_ci_high": cix[1],
            "sign_reversal_cc18_vs_target": bool(np.isfinite(di) and np.sign(di)!=0 and np.sign(dt)!=0 and np.sign(di)!=np.sign(dt)),
            "sign_reversal_cc18_vs_non": bool(np.isfinite(di) and np.isfinite(do) and np.sign(di)!=0 and np.sign(do)!=0 and np.sign(di)!=np.sign(do)),
            "ignorance_bound_low": lo, "ignorance_bound_high": hi,
            "identified_order_under_ignorance_bounds": identified,
        })
    return pd.DataFrame(rows), d


def algorithm_summary(d, metric, frame):
    x = d.copy()
    rows = []
    for alg, g in x.groupby("alg_name"):
        vals_all = pd.to_numeric(g[metric], errors="coerce").dropna()
        vals_in = pd.to_numeric(g.loc[g.in_cc18, metric], errors="coerce").dropna()
        vals_out = pd.to_numeric(g.loc[~g.in_cc18, metric], errors="coerce").dropna()
        rows.append({
            "validation_frame": frame, "algorithm": alg,
            "n_all": len(vals_all), "mean_all": vals_all.mean(),
            "n_cc18": len(vals_in), "mean_cc18": vals_in.mean(),
            "n_non_cc18": len(vals_out), "mean_non_cc18": vals_out.mean(),
        })
    return pd.DataFrame(rows)


def gate_summary(pairdf):
    if pairdf.empty:
        return {"decision": "PIVOT_OR_REPAIR_DATA", "reason": "No pairwise validation data."}
    ok = pairdf.dropna(subset=["delta_cc18_a_minus_b", "delta_target_a_minus_b"])
    reversal_rate = float(ok.sign_reversal_cc18_vs_target.mean()) if len(ok) else np.nan
    bias = ok.suite_to_target_bias.abs()
    inter = ok.interaction_cc18_minus_non.abs().dropna()
    frac_bias_005 = float((bias > .005).mean()) if len(bias) else np.nan
    max_bias = float(bias.max()) if len(bias) else np.nan
    med_inter = float(inter.median()) if len(inter) else np.nan
    # This is an operational continuation gate, not a preregistered confirmatory hypothesis test.
    cont = bool((reversal_rate >= .05) or (frac_bias_005 >= .25) or (max_bias >= .02))
    return {
        "decision": "CONTINUE_TO_FRESH_FULL_MATRIX" if cont else "KILL_OR_PIVOT_BEFORE_FRESH_MATRIX",
        "gate_is_confirmatory": False,
        "note": "Threshold fixed for execution triage after an earlier small public pilot; do not present as preregistered inference.",
        "pair_count": int(len(ok)),
        "cc18_vs_target_sign_reversal_rate": reversal_rate,
        "fraction_abs_suite_to_target_bias_gt_0_005": frac_bias_005,
        "max_abs_suite_to_target_bias": max_bias,
        "median_abs_cc18_vs_non_interaction": med_inter,
    }


def main():
    provenance = {
        "started_utc": now_iso(), "seed": SEED, "bootstrap_reps": BOOT,
        "tabzilla_commit": TABZILLA_COMMIT,
        "design": "outcome-separated live population audit + public historical outcome validation",
    }
    openml, tasks, dsets = robust_openml_registry()
    provenance["openml_python_version"] = getattr(openml, "__version__", "unknown")
    provenance["task_columns"] = list(map(str, tasks.columns))
    provenance["dataset_columns"] = list(map(str, dsets.columns))

    cc18_tids, cc18_dids = get_suite_ids(openml, 99)
    try:
        tab_tids, tab_dids = get_suite_ids(openml, 379)
    except Exception as e:
        print("OpenML suite 379 unavailable:", repr(e), file=sys.stderr)
        tab_tids, tab_dids = [], []
        provenance["suite379_error"] = repr(e)

    merged, target, canonical = build_population(tasks, dsets, cc18_tids, cc18_dids, tab_tids, tab_dids)
    target = add_derived_metadata(target)
    canonical = add_derived_metadata(canonical)

    merged.to_csv(OUT/"openml_supervised_classification_registry_raw_joined.csv", index=False)
    target.to_csv(OUT/"openml_target_task_frame.csv", index=False)
    canonical.to_csv(OUT/"openml_target_canonical_dataset_target_frame.csv", index=False)
    pd.DataFrame({"task_id": cc18_tids}).to_csv(OUT/"cc18_task_ids.csv", index=False)
    pd.DataFrame({"task_id": tab_tids}).to_csv(OUT/"tabzilla_suite379_task_ids.csv", index=False)

    bal = balance_table(target)
    bal.to_csv(OUT/"cc18_vs_target_metadata_balance.csv", index=False)

    proxy_cols = [c for c in target.columns if str(c).startswith("cc18_proxy_")]
    proxy_summary = {}
    for c in proxy_cols:
        v = target[c].fillna(False).astype(bool)
        proxy_summary[c] = {"count": int(v.sum()), "fraction": float(v.mean())}

    summary = {
        "freeze_utc": now_iso(),
        "raw_supervised_classification_tasks": int(len(tasks)),
        "active_dataset_backed_target_tasks": int(len(target)),
        "canonical_dataset_target_rows": int(len(canonical)),
        "cc18_task_count_official": int(len(cc18_tids)),
        "cc18_task_rows_found_in_target": int(target["in_cc18_task"].sum()),
        "cc18_dataset_rows_found_in_target": int(target["in_cc18_data"].sum()),
        "tabzilla_suite379_task_count": int(len(tab_tids)),
        "tabzilla_suite379_rows_found_in_target": int(target["in_tabzilla379_task"].sum()),
        "known_numeric_cc18_proxy_exclusions_in_target": proxy_summary,
    }
    write_json(OUT/"population_summary.json", summary)

    # Public historical outcome recovery and full matched validation matrix.
    complete = download_csv(URL_COMPLETE)
    broad = download_csv(URL_BROAD)
    complete.to_csv(OUT/"tabzilla_historical_complete18x104.csv", index=False)
    broad.to_csv(OUT/"tabzilla_historical_broad_outcomes.csv", index=False)

    pair_complete, dcomplete = pairwise_matrix(complete, set(cc18_tids), "TabZilla_complete_18_algorithm_frame", "Accuracy__test_mean")
    pair_complete.to_csv(OUT/"pairwise_complete18_accuracy.csv", index=False)
    algorithm_summary(dcomplete, "Accuracy__test_mean", "TabZilla_complete_18_algorithm_frame").to_csv(OUT/"algorithm_summary_complete18_accuracy.csv", index=False)

    # Pairwise-complete broader matrix: retains more tasks for algorithms with sufficient public coverage.
    pair_broad, dbroad = pairwise_matrix(broad, set(cc18_tids), "TabZilla_broad_pairwise_complete_frame", "Accuracy__test_mean")
    pair_broad.to_csv(OUT/"pairwise_broad_accuracy.csv", index=False)
    algorithm_summary(dbroad, "Accuracy__test_mean", "TabZilla_broad_pairwise_complete_frame").to_csv(OUT/"algorithm_summary_broad_accuracy.csv", index=False)

    # Sensitivity metrics where available.
    sensitivity = {}
    for metric in ["F1__test_mean", "normalized_Accuracy__test_mean", "normalized_F1__test_mean"]:
        if metric in broad.columns:
            p, _ = pairwise_matrix(broad, set(cc18_tids), "TabZilla_broad_pairwise_complete_frame", metric)
            p.to_csv(OUT/("pairwise_broad_" + re.sub(r"[^A-Za-z0-9]+", "_", metric).strip("_") + ".csv"), index=False)
            sensitivity[metric] = gate_summary(p)

    gate = gate_summary(pair_complete)
    gate["broad_pairwise_gate"] = gate_summary(pair_broad)
    gate["sensitivity_gates"] = sensitivity
    write_json(OUT/"gate_decision.json", gate)

    protocol = f"""# Frozen execution protocol\n\nFreeze time (UTC): {now_iso()}\n\n## Target estimand\nFor algorithm pair (a,b), D_ab(T)=Y_a(T)-Y_b(T) under a fixed evaluation protocol and target task population P. The primary estimand is Delta^P_ab = E_P[D_ab(T)].\n\n## Population frames\n- Main registry audit: all OpenML supervised-classification task objects whose underlying dataset is active at freeze time.\n- Canonical sensitivity: one representative task per dataset-target key when the target feature is available.\n- CC18: OpenML suite 99, used as the curated benchmark selection indicator, not as the target population.\n- TabZilla public outcomes: historical validation oracle only. The 18-algorithm complete subset is not called a population because completeness itself induces selection.\n\n## Outcome-independent exclusions\nNo task is removed merely for being small, large, imbalanced, high-dimensional, or outside CC18. Broken/inactive underlying datasets are excluded from the main live frame. Fresh model execution will use a single prespecified evaluation protocol rather than inheriting heterogeneous task estimation procedures.\n\n## Primary diagnostics before fresh training\n1. CC18 vs target metadata support / distribution shift.\n2. Pairwise algorithm-performance interaction in public outcomes.\n3. CC18-to-validation-target pairwise contrast bias and sign reversal.\n4. Retrospective partial-identification bounds when only CC18 outcomes are revealed.\n\n## Continuation gate\nOperational triage only (not preregistered confirmatory inference): continue if any of: >=5% pairwise CC18-vs-target sign reversals; >=25% pairs have absolute contrast bias >0.005 accuracy; or maximum absolute contrast bias >=0.02. Otherwise kill/pivot before costly fresh training.\n\n## Reproducibility\nRandom seed: {SEED}; bootstrap replicates: {BOOT}; historical TabZilla commit: {TABZILLA_COMMIT}.\n"""
    (OUT/"FROZEN_PROTOCOL.md").write_text(protocol, encoding="utf-8")
    provenance["finished_utc"] = now_iso()
    write_json(OUT/"provenance.json", provenance)

    print("POPULATION_SUMMARY=" + json.dumps(summary, sort_keys=True))
    print("GATE_DECISION=" + json.dumps(gate, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
