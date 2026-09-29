#!/usr/bin/env python3
"""Design-based analysis of the fresh probability-sampled algorithm matrix.

The target is the frozen registry-defined empirical population. CC18 is a
certainty stratum; all non-CC18 strata are SRSWOR with known N_h and n_h.
Execution failures are never silently discarded: pairwise estimands receive
[-1,1] sample-estimator bounds for missing task contrasts in addition to any
point/SE estimate available under complete response.
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

N_SPLITS = 5
METRICS = ["balanced_accuracy", "accuracy", "f1_macro"]


def read_many(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern, recursive=True))
    if not files:
        return pd.DataFrame()
    frames=[]
    for f in files:
        try:
            x=pd.read_csv(f)
            x["_source_file"]=f
            frames.append(x)
        except Exception:
            pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def task_level(folds: pd.DataFrame, metric: str) -> pd.DataFrame:
    ok=folds.loc[folds.status.eq("ok")].copy()
    ok[metric]=pd.to_numeric(ok[metric], errors="coerce")
    ok=ok.dropna(subset=[metric])
    g=(ok.groupby(["sample_order","problem_id","did","in_cc18","sampling_stratum",
                   "stratum_N","stratum_n","inclusion_probability","design_weight","algorithm"],
                  dropna=False)
         .agg(fold_successes=(metric,"size"), value=(metric,"mean"))
         .reset_index())
    # A scientific task outcome is defined only by the complete common 5-fold protocol.
    g.loc[g.fold_successes.ne(N_SPLITS),"value"]=np.nan
    return g


def pair_sample(manifest: pd.DataFrame, t: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    base=manifest[["sample_order","problem_id","did","in_cc18","sampling_stratum",
                   "stratum_N","stratum_n","inclusion_probability","design_weight"]].copy()
    aa=t.loc[t.algorithm.eq(a),["sample_order","value","fold_successes"]].rename(columns={"value":"ya","fold_successes":"folds_a"})
    bb=t.loc[t.algorithm.eq(b),["sample_order","value","fold_successes"]].rename(columns={"value":"yb","fold_successes":"folds_b"})
    m=base.merge(aa,on="sample_order",how="left").merge(bb,on="sample_order",how="left")
    m["d"]=m.ya-m.yb
    m["pair_observed"]=m.d.notna()
    return m


def stratified_estimate(m: pd.DataFrame, restrict_noncc18=False):
    x=m.loc[~m.in_cc18.astype(bool)].copy() if restrict_noncc18 else m.copy()
    N_total=int(x.groupby("sampling_stratum").stratum_N.first().sum())
    total_hat=0.0; var_total=0.0; lower_total=0.0; upper_total=0.0
    all_complete=True; by=[]
    for h,g in x.groupby("sampling_stratum",sort=True):
        Nh=int(g.stratum_N.iloc[0]); nh=int(g.stratum_n.iloc[0])
        vals=pd.to_numeric(g.d,errors="coerce")
        obs=vals.dropna().to_numpy(float); mh=nh-len(obs)
        complete=(mh==0)
        all_complete &= complete
        # Point is only scientifically designated when the probability sample has
        # complete pair response. We still compute midpoint for diagnostics.
        filled_mid=np.where(vals.notna(),vals,0.0).astype(float)
        mean_mid=float(np.mean(filled_mid))
        total_hat += Nh*mean_mid
        lower_mean=(np.nansum(vals.to_numpy(float))-mh)/nh
        upper_mean=(np.nansum(vals.to_numpy(float))+mh)/nh
        lower_total += Nh*lower_mean; upper_total += Nh*upper_mean
        if complete and nh>1:
            s2=float(np.var(obs,ddof=1)); f=nh/Nh
            var_total += (Nh**2)*(1-f)*s2/nh
        elif complete and nh==Nh:
            pass
        elif not complete:
            var_total=np.nan
        by.append({"stratum":h,"N_h":Nh,"n_h":nh,"observed_pair_n":len(obs),"missing_pair_n":mh,
                   "mean_midpoint":mean_mid,"lower_mean_missing_minus1":lower_mean,"upper_mean_missing_plus1":upper_mean})
    est=total_hat/N_total
    lo=lower_total/N_total; hi=upper_total/N_total
    se=math.sqrt(var_total)/N_total if np.isfinite(var_total) else np.nan
    return {"N":N_total,"complete_response":bool(all_complete),"estimate":est if all_complete else np.nan,
            "diagnostic_midpoint_estimate":est,"design_se":se,"ci95_low":est-1.96*se if all_complete else np.nan,
            "ci95_high":est+1.96*se if all_complete else np.nan,
            "execution_missing_bound_low":lo,"execution_missing_bound_high":hi,"strata":by}


def cc18_estimate(m: pd.DataFrame):
    x=m.loc[m.in_cc18.astype(bool)].copy(); vals=pd.to_numeric(x.d,errors="coerce")
    n=len(vals); obs=vals.dropna(); miss=n-len(obs)
    lo=(obs.sum()-miss)/n if n else np.nan; hi=(obs.sum()+miss)/n if n else np.nan
    return {"N":n,"complete_response":miss==0,"estimate":float(obs.mean()) if miss==0 and n else np.nan,
            "execution_missing_bound_low":lo,"execution_missing_bound_high":hi,
            "observed_n":len(obs),"missing_n":miss}


def public_cc18_ignorance_bound(cc18_delta: float, target_N: int, cc18_N: int):
    # If the only known target outcomes were the CC18 tasks, with equal target weights.
    w=cc18_N/target_N
    return (w*cc18_delta-(1-w), w*cc18_delta+(1-w))


def source_family_flags(name: str):
    s=str(name).lower()
    return {
        "name_flag_bng": s.startswith("bng(") or "bng(" in s,
        "name_flag_meta_album": "meta_album" in s or "meta-album" in s,
        "name_flag_synthetic_token": any(z in s for z in ["synthetic","artificial","gametes","friedman","xor","parity"]),
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest",required=True)
    ap.add_argument("--fold-glob",required=True)
    ap.add_argument("--task-status-glob",default="")
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    manifest=pd.read_csv(args.manifest).sort_values("sample_order").reset_index(drop=True)
    folds=read_many(args.fold_glob)
    statuses=read_many(args.task_status_glob) if args.task_status_glob else pd.DataFrame()
    if folds.empty:
        raise RuntimeError("No fold result files found")

    # Deduplicate exact task/algorithm/fold keys in case artifacts are collected twice.
    key=["sample_order","algorithm","fold"]
    folds=folds.sort_values(key).drop_duplicates(key,keep="last")
    algorithms=sorted(folds.algorithm.dropna().unique())
    summary={"sample_N":len(manifest),"target_N":int(manifest.groupby("sampling_stratum").stratum_N.first().sum()),
             "cc18_target_N":int(manifest.loc[manifest.in_cc18.astype(bool)].stratum_N.iloc[0]) if manifest.in_cc18.astype(bool).any() else 0,
             "algorithms":algorithms,"fold_rows":len(folds)}

    # Execution reliability is an outcome, not a filter.
    reliability=[]
    full_index=pd.MultiIndex.from_product([manifest.sample_order,algorithms,range(N_SPLITS)],names=["sample_order","algorithm","fold"])
    tmp=folds.set_index(key)
    for alg in algorithms:
        ix=pd.MultiIndex.from_product([manifest.sample_order,[alg],range(N_SPLITS)],names=full_index.names)
        sub=tmp.reindex(ix).reset_index()
        success=sub.status.eq("ok")
        joined=sub[["sample_order"]].merge(manifest[["sample_order","design_weight","in_cc18","sampling_stratum"]],on="sample_order",how="left")
        # Per-task complete response for this algorithm.
        taskok=(sub.assign(ok=success).groupby("sample_order").ok.sum().eq(N_SPLITS)).rename("complete")
        jj=manifest[["sample_order","design_weight","in_cc18","sampling_stratum"]].merge(taskok,on="sample_order",how="left")
        jj.complete=jj.complete.fillna(False)
        weighted=float((jj.design_weight*jj.complete.astype(float)).sum()/ (jj.groupby("sampling_stratum").design_weight.sum().sum()))
        reliability.append({"algorithm":alg,"fold_attempt_grid":len(sub),"fold_success_n":int(success.sum()),
                            "fold_success_fraction":float(success.mean()),"task_complete_n":int(jj.complete.sum()),
                            "sample_task_complete_fraction":float(jj.complete.mean()),"design_weighted_task_complete_fraction":weighted})
    pd.DataFrame(reliability).to_csv(out/"execution_reliability.csv",index=False)

    pair_rows=[]; strata_rows=[]
    for metric in METRICS:
        if metric not in folds.columns: continue
        t=task_level(folds,metric); t.to_csv(out/f"task_level_{metric}.csv",index=False)
        for a,b in itertools.combinations(algorithms,2):
            m=pair_sample(manifest,t,a,b)
            target=stratified_estimate(m,False)
            non=stratified_estimate(m,True)
            suite=cc18_estimate(m)
            if suite["complete_response"]:
                ign_lo,ign_hi=public_cc18_ignorance_bound(suite["estimate"],target["N"],suite["N"])
            else:
                ign_lo,ign_hi=np.nan,np.nan
            reversal=(suite["complete_response"] and target["complete_response"] and suite["estimate"]!=0 and target["estimate"]!=0 and np.sign(suite["estimate"])!=np.sign(target["estimate"]))
            pair_rows.append({
                "metric":metric,"algorithm_a":a,"algorithm_b":b,
                "target_N":target["N"],"target_complete_response":target["complete_response"],
                "delta_target":target["estimate"],"target_design_se":target["design_se"],
                "target_ci95_low":target["ci95_low"],"target_ci95_high":target["ci95_high"],
                "target_missing_bound_low":target["execution_missing_bound_low"],"target_missing_bound_high":target["execution_missing_bound_high"],
                "noncc18_N":non["N"],"delta_noncc18":non["estimate"],"noncc18_design_se":non["design_se"],
                "cc18_N":suite["N"],"cc18_complete_response":suite["complete_response"],"delta_cc18":suite["estimate"],
                "cc18_missing_bound_low":suite["execution_missing_bound_low"],"cc18_missing_bound_high":suite["execution_missing_bound_high"],
                "suite_to_target_shift":suite["estimate"]-target["estimate"] if suite["complete_response"] and target["complete_response"] else np.nan,
                "cc18_vs_noncc18_interaction":suite["estimate"]-non["estimate"] if suite["complete_response"] and non["complete_response"] else np.nan,
                "cc18_vs_target_sign_reversal":bool(reversal),
                "target_order_design_ci":("a>b" if target["ci95_low"]>0 else ("a<b" if target["ci95_high"]<0 else "uncertain")) if target["complete_response"] else "missingness_bounded",
                "cc18_only_assumption_free_bound_low":ign_lo,"cc18_only_assumption_free_bound_high":ign_hi,
                "cc18_only_identified_order":("a>b" if np.isfinite(ign_lo) and ign_lo>0 else ("a<b" if np.isfinite(ign_hi) and ign_hi<0 else "unidentified")),
            })
            for sr in target["strata"]:
                strata_rows.append({"metric":metric,"algorithm_a":a,"algorithm_b":b,**sr})
    pair=pd.DataFrame(pair_rows); pair.to_csv(out/"fresh_pairwise_design_based.csv",index=False)
    pd.DataFrame(strata_rows).to_csv(out/"fresh_pairwise_by_sampling_stratum.csv",index=False)

    # Algorithm-level target performance by the same design; outcomes lie [0,1],
    # so execution missingness bounds use [0,1] rather than pair [-1,1].
    alg_rows=[]
    for metric in METRICS:
        if metric not in folds.columns: continue
        t=task_level(folds,metric)
        for alg in algorithms:
            base=manifest[["sample_order","in_cc18","sampling_stratum","stratum_N","stratum_n","design_weight"]].copy()
            v=t.loc[t.algorithm.eq(alg),["sample_order","value"]]
            m=base.merge(v,on="sample_order",how="left")
            N=int(m.groupby("sampling_stratum").stratum_N.first().sum()); total=0.; lo=0.; hi=0.; complete=True
            for h,g in m.groupby("sampling_stratum"):
                Nh=int(g.stratum_N.iloc[0]); nh=int(g.stratum_n.iloc[0]); vals=pd.to_numeric(g.value,errors="coerce")
                miss=int(vals.isna().sum()); complete &= miss==0
                total += Nh*vals.fillna(0).mean(); lo += Nh*(vals.fillna(0).sum()/nh); hi += Nh*((vals.fillna(0).sum()+miss)/nh)
            alg_rows.append({"metric":metric,"algorithm":alg,"target_complete_response":complete,
                             "target_mean":total/N if complete else np.nan,"target_missing_bound_low":lo/N,"target_missing_bound_high":hi/N})
    pd.DataFrame(alg_rows).to_csv(out/"fresh_algorithm_target_means.csv",index=False)

    # Registry-family name flags for transparent post hoc sensitivity diagnostics.
    ff=[]
    for _,r in manifest.iterrows(): ff.append({"sample_order":r.sample_order,"name":r.get("name",""),**source_family_flags(r.get("name",""))})
    pd.DataFrame(ff).to_csv(out/"sample_source_family_name_flags.csv",index=False)

    primary=pair.loc[pair.metric.eq("balanced_accuracy")]
    complete_pairs=primary.loc[primary.target_complete_response & primary.cc18_complete_response]
    summary.update({
        "primary_metric":"balanced_accuracy","pair_count":len(primary),
        "complete_response_pair_count":len(complete_pairs),
        "sign_reversal_rate_among_complete_pairs":float(complete_pairs.cc18_vs_target_sign_reversal.mean()) if len(complete_pairs) else None,
        "median_abs_suite_to_target_shift":float(complete_pairs.suite_to_target_shift.abs().median()) if len(complete_pairs) else None,
        "max_abs_suite_to_target_shift":float(complete_pairs.suite_to_target_shift.abs().max()) if len(complete_pairs) else None,
        "fraction_target_pair_design_ci_excludes_zero":float((complete_pairs.target_order_design_ci!="uncertain").mean()) if len(complete_pairs) else None,
        "fraction_cc18_only_pair_order_identified_assumption_free":float((complete_pairs.cc18_only_identified_order!="unidentified").mean()) if len(complete_pairs) else None,
    })
    (out/"fresh_analysis_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")
    print("FRESH_ANALYSIS_SUMMARY="+json.dumps(summary,sort_keys=True))

if __name__=="__main__":
    main()
