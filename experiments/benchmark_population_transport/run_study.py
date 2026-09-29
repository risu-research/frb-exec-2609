#!/usr/bin/env python3
"""OpenML benchmark-selection / target-population execution study.

Scientific separation:
  A. Freeze the *current active* OpenML supervised-classification registry.
  B. Define the primary target population outcome-independently as unique
     (dataset_id, target_feature) classification problems.
  C. Mark whether each problem is represented by OpenML-CC18 (suite 99), and
     audit metadata support without reusing CC18's curation rules as eligibility.
  D. Reuse historical public TabZilla outcomes only as an outcome-rich validation
     oracle before spending compute on a fresh, common-protocol algorithm matrix.

No new model is trained in this stage.
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
BOOT = int(os.environ.get("BOOT_REPS", "5000"))
TABZILLA_COMMIT = "feca5e554148bdc4ac17c3379984c2a71244cd32"
RAW_BASE = f"https://raw.githubusercontent.com/naszilla/tabzilla/{TABZILLA_COMMIT}"
URL_COMPLETE = RAW_BASE + "/tabzilla_analysis/final-selected18-algs/cleaned_results/tuned_aggregated_results.csv"
URL_BROAD = RAW_BASE + "/tabzilla_analysis/results/tuned_aggregated_results.csv"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def download_csv(url: str, stem: str) -> pd.DataFrame:
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    (OUT / f"source_{stem}.csv").write_bytes(r.content)
    return pd.read_csv(OUT / f"source_{stem}.csv")


def normalize_task_frame(tasks: pd.DataFrame) -> pd.DataFrame:
    tasks = tasks.copy().reset_index(drop=False)
    rename = {}
    for c in tasks.columns:
        cl = str(c).lower()
        if cl in {"task_id", "tid"}:
            rename[c] = "tid"
        elif cl in {"data_id", "did"}:
            rename[c] = "did"
    tasks = tasks.rename(columns=rename)
    if "tid" not in tasks.columns and "index" in tasks.columns:
        tasks = tasks.rename(columns={"index": "tid"})
    if "tid" not in tasks.columns:
        raise RuntimeError(f"OpenML task listing has no task id column: {list(tasks.columns)}")
    tasks["tid"] = pd.to_numeric(tasks["tid"], errors="coerce").astype("Int64")
    if "did" in tasks.columns:
        tasks["did"] = pd.to_numeric(tasks["did"], errors="coerce").astype("Int64")
    if "status" in tasks.columns:
        tasks = tasks.loc[tasks["status"].astype(str).str.lower().eq("active")].copy()
    return tasks.sort_values("tid").reset_index(drop=True)


def get_openml_registry():
    import openml
    try:
        from openml.tasks import TaskType
        task_type = TaskType.SUPERVISED_CLASSIFICATION
    except Exception:
        task_type = 1

    # Current openml-python returns DataFrame directly; older versions accepted
    # output_format. Keep both routes for a durable execution artifact.
    try:
        tasks = openml.tasks.list_tasks(task_type=task_type, status="active")
    except TypeError:
        tasks = openml.tasks.list_tasks(
            task_type=task_type, status="active", output_format="dataframe"
        )
    if not isinstance(tasks, pd.DataFrame):
        tasks = pd.DataFrame(tasks).T
    return openml, normalize_task_frame(tasks)


def get_suite_task_ids(openml, suite_id: int) -> list[int]:
    try:
        suite = openml.study.get_suite(suite_id)
        return sorted({int(x) for x in suite.tasks})
    except Exception as exc:
        print(f"get_suite({suite_id}) failed; REST fallback: {exc!r}", file=sys.stderr)
        r = requests.get(f"https://www.openml.org/api/v1/json/study/{suite_id}", timeout=120)
        r.raise_for_status()
        j = r.json()
        st = j.get("study", j)
        candidates = []
        if isinstance(st, dict):
            x = st.get("tasks", st.get("task", []))
            if isinstance(x, dict):
                x = x.get("task", x.get("tasks", []))
            candidates = x if isinstance(x, list) else []
        vals = []
        for x in candidates:
            if isinstance(x, dict):
                x = x.get("task_id", x.get("id"))
            if x is not None:
                vals.append(int(x))
        if not vals:
            raise RuntimeError(f"Could not parse task IDs from suite {suite_id}")
        return sorted(set(vals))


def find_col(df: pd.DataFrame, aliases: list[str]):
    lut = {str(c).lower(): c for c in df.columns}
    for a in aliases:
        if a.lower() in lut:
            return lut[a.lower()]
    return None


def build_problem_frame(tasks: pd.DataFrame, cc18_tids: list[int], tab_tids: list[int]):
    t = tasks.copy()
    t["in_cc18_task"] = t["tid"].isin(cc18_tids)
    t["in_tabzilla379_task"] = t["tid"].isin(tab_tids)

    did_col = find_col(t, ["did", "data_id"])
    target_col = find_col(t, ["target_feature", "target_name"])
    if did_col is None:
        raise RuntimeError("OpenML task registry has no dataset id; cannot define problem population")

    if target_col is None:
        # Conservative fallback: task-object population only; this should be rare.
        t["_problem_target"] = "__TARGET_UNAVAILABLE__" + t["tid"].astype(str)
        target_col = "_problem_target"
    else:
        # Missing target labels should not silently collapse unrelated tasks.
        miss = t[target_col].isna()
        t.loc[miss, target_col] = "__TARGET_UNAVAILABLE__" + t.loc[miss, "tid"].astype(str)

    keys = [did_col, target_col]
    g = t.groupby(keys, dropna=False, sort=True)
    first = g.head(1).copy().set_index(keys)
    agg = g.agg(
        openml_task_count=("tid", "size"),
        min_task_id=("tid", "min"),
        in_cc18=("in_cc18_task", "max"),
        in_tabzilla379=("in_tabzilla379_task", "max"),
    )
    problems = first.drop(columns=[c for c in ["openml_task_count", "in_cc18", "in_tabzilla379"] if c in first.columns], errors="ignore").join(agg).reset_index()
    problems["problem_id"] = problems[did_col].astype(str) + "::" + problems[target_col].astype(str)
    return t, problems


def numeric(df, aliases):
    c = find_col(df, aliases)
    if c is None:
        return None
    return pd.to_numeric(df[c], errors="coerce")


def add_meta(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    n = numeric(x, ["NumberOfInstances", "number_of_instances"])
    p = numeric(x, ["NumberOfFeatures", "number_of_features"])
    mn = numeric(x, ["MinorityClassSize", "minority_class_size"])
    mx = numeric(x, ["MajorityClassSize", "majority_class_size"])
    cls = numeric(x, ["NumberOfClasses", "number_of_classes"])
    miss = numeric(x, ["NumberOfMissingValues", "number_of_missing_values"])
    if n is not None:
        x["meta_log1p_instances"] = np.log1p(n)
        x["cc18_proxy_under_500"] = n < 500
        x["cc18_proxy_over_100k"] = n > 100000
    if p is not None:
        x["meta_log1p_features"] = np.log1p(p)
        # CC18's real rule concerns one-hot dimensions. Raw p>5000 is only a
        # transparent lower-fidelity proxy and is named accordingly.
        x["cc18_proxy_over_5000_raw_features"] = p > 5000
    if n is not None and p is not None:
        x["meta_feature_instance_ratio"] = p / n.replace(0, np.nan)
    if mn is not None and mx is not None:
        x["meta_minority_majority_ratio"] = mn / mx.replace(0, np.nan)
        x["cc18_proxy_imbalance_le_005"] = x["meta_minority_majority_ratio"] <= 0.05
        x["cc18_proxy_minority_lt20"] = mn < 20
    if cls is not None:
        x["meta_classes"] = cls
    if miss is not None and n is not None and p is not None:
        x["meta_missing_fraction"] = miss / (n * p).replace(0, np.nan)
    proxy = [c for c in x.columns if str(c).startswith("cc18_proxy_")]
    if proxy:
        x["cc18_known_numeric_proxy_exclusion"] = x[proxy].fillna(False).any(axis=1)
    return x


def balance_table(problems: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "meta_log1p_instances", "meta_log1p_features", "meta_feature_instance_ratio",
        "meta_minority_majority_ratio", "meta_classes", "meta_missing_fraction",
    ]
    rows = []
    s = problems["in_cc18"].astype(bool)
    for m in metrics:
        if m not in problems:
            continue
        a = pd.to_numeric(problems.loc[s, m], errors="coerce").dropna().to_numpy(float)
        b = pd.to_numeric(problems.loc[~s, m], errors="coerce").dropna().to_numpy(float)
        if len(a) < 2 or len(b) < 2:
            continue
        denom = max(len(a) + len(b) - 2, 1)
        pooled = math.sqrt(((len(a)-1)*np.var(a, ddof=1) + (len(b)-1)*np.var(b, ddof=1))/denom)
        smd = (a.mean()-b.mean())/pooled if pooled > 0 else np.nan
        ks = stats.ks_2samp(a, b)
        rows.append({
            "metric": m, "n_cc18": len(a), "n_non_cc18": len(b),
            "cc18_mean": a.mean(), "non_cc18_mean": b.mean(),
            "cc18_median": np.median(a), "non_cc18_median": np.median(b),
            "standardized_mean_difference_cc18_minus_non": smd,
            "ks_statistic": ks.statistic,
            "ks_pvalue_descriptive_only": ks.pvalue,
        })
    return pd.DataFrame(rows)


def parse_tid(name):
    m = re.search(r"__(\d+)$", str(name))
    return int(m.group(1)) if m else np.nan


def bootstrap_mean(x, reps: int, seed: int):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 2: return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(reps, len(x)))
    vals = x[idx].mean(axis=1)
    return tuple(np.quantile(vals, [0.025, 0.975]))


def bootstrap_diff(x, y, reps: int, seed: int):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    y = np.asarray(y, float); y = y[np.isfinite(y)]
    if len(x) < 2 or len(y) < 2: return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    ix = rng.integers(0, len(x), size=(reps, len(x)))
    iy = rng.integers(0, len(y), size=(reps, len(y)))
    vals = x[ix].mean(axis=1) - y[iy].mean(axis=1)
    return tuple(np.quantile(vals, [0.025, 0.975]))


def pairwise_matrix(df, cc18_tids: set[int], label: str, metric: str):
    d = df.copy()
    needed = {"dataset_name", "alg_name", metric}
    if not needed.issubset(d.columns):
        raise RuntimeError(f"{label}/{metric} missing {sorted(needed-set(d.columns))}")
    d["tid"] = d["dataset_name"].map(parse_tid)
    d[metric] = pd.to_numeric(d[metric], errors="coerce")
    d = d.dropna(subset=["tid", metric]).copy()
    d["tid"] = d["tid"].astype(int)
    d["in_cc18"] = d["tid"].isin(cc18_tids)
    algs = sorted(d.alg_name.dropna().unique())
    rows = []
    for pair_no, (a,b) in enumerate(itertools.combinations(algs, 2)):
        aa = d.loc[d.alg_name.eq(a), ["tid", metric, "in_cc18"]].rename(columns={metric:"ya"})
        bb = d.loc[d.alg_name.eq(b), ["tid", metric]].rename(columns={metric:"yb"})
        m = aa.merge(bb, on="tid", how="inner")
        if m.empty: continue
        diff = (m.ya-m.yb).to_numpy(float)
        inside = (m.loc[m.in_cc18, "ya"]-m.loc[m.in_cc18, "yb"]).to_numpy(float)
        outside = (m.loc[~m.in_cc18, "ya"]-m.loc[~m.in_cc18, "yb"]).to_numpy(float)
        dt = float(np.mean(diff)); di = float(np.mean(inside)) if len(inside) else np.nan
        do = float(np.mean(outside)) if len(outside) else np.nan
        s0 = SEED + 100003*pair_no + sum(ord(c) for c in metric)
        ct = bootstrap_mean(diff, BOOT, s0)
        ci = bootstrap_mean(inside, BOOT, s0+1)
        co = bootstrap_mean(outside, BOOT, s0+2)
        cx = bootstrap_diff(inside, outside, BOOT, s0+3)
        pi = len(inside)/len(diff)
        # Accuracy/F1 differences lie in [-1,1]. Under equal target weights and
        # no assumption on unobserved tasks, these finite-frame endpoints are sharp.
        if len(inside):
            observed_contribution = pi*di
            lo, hi = observed_contribution-(1-pi), observed_contribution+(1-pi)
        else:
            lo, hi = -1.0, 1.0
        identified = "a>b" if lo>0 else ("a<b" if hi<0 else "unidentified")
        rows.append({
            "validation_frame":label, "metric":metric, "algorithm_a":a, "algorithm_b":b,
            "n_pair_target":len(diff), "n_pair_cc18":len(inside), "n_pair_non_cc18":len(outside),
            "coverage_pi":pi,
            "delta_target_a_minus_b":dt, "delta_target_ci_low":ct[0], "delta_target_ci_high":ct[1],
            "delta_cc18_a_minus_b":di, "delta_cc18_ci_low":ci[0], "delta_cc18_ci_high":ci[1],
            "delta_non_cc18_a_minus_b":do, "delta_non_cc18_ci_low":co[0], "delta_non_cc18_ci_high":co[1],
            "suite_to_target_bias":di-dt if np.isfinite(di) else np.nan,
            "interaction_cc18_minus_non":di-do if np.isfinite(di) and np.isfinite(do) else np.nan,
            "interaction_ci_low":cx[0], "interaction_ci_high":cx[1],
            "interaction_ci_excludes_zero":bool(np.isfinite(cx[0]) and (cx[0]>0 or cx[1]<0)),
            "sign_reversal_cc18_vs_target":bool(np.isfinite(di) and di!=0 and dt!=0 and np.sign(di)!=np.sign(dt)),
            "sign_reversal_cc18_vs_non":bool(np.isfinite(di) and np.isfinite(do) and di!=0 and do!=0 and np.sign(di)!=np.sign(do)),
            "ignorance_bound_low":lo, "ignorance_bound_high":hi,
            "identified_order_under_ignorance_bounds":identified,
        })
    return pd.DataFrame(rows), d


def algorithm_summary(d, metric, frame):
    rows=[]
    for alg,g in d.groupby("alg_name"):
        allv=pd.to_numeric(g[metric],errors="coerce").dropna()
        inv=pd.to_numeric(g.loc[g.in_cc18,metric],errors="coerce").dropna()
        outv=pd.to_numeric(g.loc[~g.in_cc18,metric],errors="coerce").dropna()
        rows.append({"validation_frame":frame,"algorithm":alg,"n_all":len(allv),"mean_all":allv.mean(),
                     "n_cc18":len(inv),"mean_cc18":inv.mean(),"n_non_cc18":len(outv),"mean_non_cc18":outv.mean()})
    return pd.DataFrame(rows)


def gate_summary(pairdf):
    if pairdf.empty:
        return {"decision":"PIVOT_OR_REPAIR_DATA","reason":"No pairwise validation data"}
    ok=pairdf.dropna(subset=["delta_cc18_a_minus_b","delta_target_a_minus_b"])
    bias=ok.suite_to_target_bias.abs(); inter=ok.interaction_cc18_minus_non.abs().dropna()
    rr=float(ok.sign_reversal_cc18_vs_target.mean()) if len(ok) else np.nan
    f5=float((bias>.005).mean()) if len(bias) else np.nan
    mb=float(bias.max()) if len(bias) else np.nan
    cont=bool((rr>=.05) or (f5>=.25) or (mb>=.02))
    return {
        "decision":"CONTINUE_TO_FRESH_FULL_MATRIX" if cont else "KILL_OR_PIVOT_BEFORE_FRESH_MATRIX",
        "gate_is_confirmatory":False,
        "note":"Execution-triage threshold fixed after an earlier exploratory public pilot; not preregistered inference.",
        "pair_count":int(len(ok)),
        "cc18_vs_target_sign_reversal_rate":rr,
        "fraction_abs_suite_to_target_bias_gt_0_005":f5,
        "max_abs_suite_to_target_bias":mb,
        "median_abs_cc18_vs_non_interaction":float(inter.median()) if len(inter) else np.nan,
        "fraction_interaction_bootstrap_ci_excludes_zero":float(ok.interaction_ci_excludes_zero.mean()) if len(ok) else np.nan,
        "fraction_pair_order_identified_by_assumption_free_bounds":float((ok.identified_order_under_ignorance_bounds!="unidentified").mean()) if len(ok) else np.nan,
    }


def main():
    provenance={"started_utc":now_iso(),"seed":SEED,"bootstrap_reps":BOOT,
                "tabzilla_commit":TABZILLA_COMMIT,
                "design":"active OpenML problem-frame audit + historical public-outcome validation"}
    openml,tasks=get_openml_registry()
    provenance["openml_python_version"]=getattr(openml,"__version__","unknown")
    provenance["task_columns"]=list(map(str,tasks.columns))

    cc18=get_suite_task_ids(openml,99)
    try:
        tab379=get_suite_task_ids(openml,379)
    except Exception as exc:
        print(f"Suite 379 unavailable: {exc!r}",file=sys.stderr); tab379=[]
        provenance["suite379_error"]=repr(exc)

    task_frame,problems=build_problem_frame(tasks,cc18,tab379)
    problems=add_meta(problems)
    task_frame.to_csv(OUT/"openml_active_supervised_classification_task_objects.csv",index=False)
    problems.to_csv(OUT/"openml_target_problem_frame.csv",index=False)
    pd.DataFrame({"task_id":cc18}).to_csv(OUT/"cc18_task_ids.csv",index=False)
    pd.DataFrame({"task_id":tab379}).to_csv(OUT/"tabzilla_suite379_task_ids.csv",index=False)

    bal=balance_table(problems); bal.to_csv(OUT/"cc18_vs_target_metadata_balance.csv",index=False)
    proxy={}
    for c in [x for x in problems.columns if str(x).startswith("cc18_proxy_")]:
        v=problems[c].fillna(False).astype(bool)
        proxy[c]={"count":int(v.sum()),"fraction":float(v.mean())}

    summary={
        "freeze_utc":now_iso(),
        "active_supervised_classification_task_objects":int(len(task_frame)),
        "unique_dataset_target_problems_primary_frame":int(len(problems)),
        "problems_with_multiple_openml_task_objects":int((problems.openml_task_count>1).sum()),
        "cc18_task_count_official":int(len(cc18)),
        "cc18_tasks_present_in_active_registry":int(task_frame.in_cc18_task.sum()),
        "cc18_unique_problems_in_primary_frame":int(problems.in_cc18.sum()),
        "tabzilla_suite379_task_count":int(len(tab379)),
        "tabzilla379_unique_problems_in_primary_frame":int(problems.in_tabzilla379.sum()),
        "known_numeric_cc18_proxy_exclusions_in_primary_frame":proxy,
    }
    write_json(OUT/"population_summary.json",summary)

    complete=download_csv(URL_COMPLETE,"tabzilla_complete18_historical")
    broad=download_csv(URL_BROAD,"tabzilla_broad_historical")
    complete.to_csv(OUT/"tabzilla_historical_complete18x104.csv",index=False)
    broad.to_csv(OUT/"tabzilla_historical_broad_outcomes.csv",index=False)

    pc,dc=pairwise_matrix(complete,set(cc18),"TabZilla_complete_18_algorithm_frame","Accuracy__test_mean")
    pc.to_csv(OUT/"pairwise_complete18_accuracy.csv",index=False)
    algorithm_summary(dc,"Accuracy__test_mean","TabZilla_complete_18_algorithm_frame").to_csv(OUT/"algorithm_summary_complete18_accuracy.csv",index=False)

    pb,db=pairwise_matrix(broad,set(cc18),"TabZilla_broad_pairwise_complete_frame","Accuracy__test_mean")
    pb.to_csv(OUT/"pairwise_broad_accuracy.csv",index=False)
    algorithm_summary(db,"Accuracy__test_mean","TabZilla_broad_pairwise_complete_frame").to_csv(OUT/"algorithm_summary_broad_accuracy.csv",index=False)

    sensitivity={}
    for metric in ["F1__test_mean","normalized_Accuracy__test_mean","normalized_F1__test_mean"]:
        if metric in broad.columns:
            px,_=pairwise_matrix(broad,set(cc18),"TabZilla_broad_pairwise_complete_frame",metric)
            px.to_csv(OUT/("pairwise_broad_"+re.sub(r"[^A-Za-z0-9]+","_",metric).strip("_")+".csv"),index=False)
            sensitivity[metric]=gate_summary(px)

    gate=gate_summary(pc); gate["broad_pairwise_gate"]=gate_summary(pb); gate["sensitivity_gates"]=sensitivity
    write_json(OUT/"gate_decision.json",gate)

    protocol=f"""# Frozen execution protocol\n\nFreeze UTC: {now_iso()}\n\n## Scientific unit and estimand\nPrimary target units are unique active OpenML supervised-classification (dataset_id, target_feature) problems. OpenML task objects are retained as provenance/sensitivity units, not multiplied into independent scientific problems. Under one common evaluation protocol, D_ab(T)=Y_a(T)-Y_b(T) and Delta^P_ab=E_P[D_ab(T)].\n\n## Selection exposure\nA target problem is CC18-covered iff at least one active task object for the same dataset-target problem belongs to OpenML suite 99. The exact CC18 task-ID analysis is retained separately in the public-outcome validation.\n\n## Outcome-independent eligibility\nNo problem is excluded merely for being small, large, imbalanced, high-dimensional, or outside CC18. Those properties are part of the target support to be audited.\n\n## Public-outcome validation\nHistorical TabZilla outcomes from commit {TABZILLA_COMMIT} are a validation oracle only. The 104-problem complete-18-algorithm subset is explicitly not called the population because complete outcome availability is itself selective. A broader pairwise-complete analysis is a second validation frame.\n\n## Assumption-free finite-frame bound\nFor target weights summing to 1 and metric differences D_ab in [-1,1], if benchmark-covered target mass is W_B, Delta_ab lies sharply in [sum_(i in B) w_i D_i -(1-W_B), sum_(i in B) w_i D_i +(1-W_B)]. Only pair intervals excluding zero induce an identified dominance edge.\n\n## Operational continuation gate\nNot confirmatory/preregistered: continue to fresh common-protocol execution if public validation shows >=5% CC18-vs-validation-target pairwise sign reversals, or >=25% pairs with absolute contrast bias >0.005, or any absolute contrast bias >=0.02. Otherwise kill/pivot before costly fresh training.\n\nSeed {SEED}; bootstrap reps {BOOT}.\n"""
    (OUT/"FROZEN_PROTOCOL.md").write_text(protocol,encoding="utf-8")
    provenance["finished_utc"]=now_iso(); write_json(OUT/"provenance.json",provenance)
    print("POPULATION_SUMMARY="+json.dumps(summary,sort_keys=True))
    print("GATE_DECISION="+json.dumps(gate,sort_keys=True))


if __name__=="__main__":
    try: main()
    except Exception:
        traceback.print_exc(); raise
