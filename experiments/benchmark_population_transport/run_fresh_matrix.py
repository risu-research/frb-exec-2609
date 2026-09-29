#!/usr/bin/env python3
"""Run the frozen fresh algorithm matrix on one probability-sample shard.

Protocol principles:
- Every sampled problem uses the same 5-fold stratified evaluation protocol.
- Large problems are evaluated at a predeclared 50k-row resource budget rather
  than being excluded, preserving the large-n support region.
- One fold-specific preprocessing transform is shared by all algorithms.
- Individual estimator fits are isolated in child processes with hard timeouts.
- Failures/timeouts are recorded as missing outcomes; they are never silently
  removed. Downstream analysis uses missing-mass identification bounds.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import queue
import time
import traceback
from pathlib import Path

# Limit nested BLAS/OpenMP oversubscription on 4-core hosted runners.
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler

SEED = 260931
MAX_ROWS = 50_000
N_SPLITS = 5
MODEL_TIMEOUT_SECONDS = int(os.environ.get("MODEL_TIMEOUT_SECONDS", "180"))
ALGORITHMS = [
    "LogisticRegression",
    "LinearSVC",
    "DecisionTree",
    "RandomForest",
    "XGBoost",
    "LightGBM",
    "CatBoost",
]


def make_estimator(name: str, seed: int):
    if name == "LogisticRegression":
        from sklearn.linear_model import LogisticRegression
        return LogisticRegression(
            C=1.0, solver="saga", max_iter=1200, random_state=seed, tol=1e-3
        )
    if name == "LinearSVC":
        from sklearn.svm import LinearSVC
        return LinearSVC(C=1.0, max_iter=6000, random_state=seed, tol=1e-4)
    if name == "DecisionTree":
        from sklearn.tree import DecisionTreeClassifier
        return DecisionTreeClassifier(random_state=seed)
    if name == "RandomForest":
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(
            n_estimators=150, max_features="sqrt", n_jobs=2, random_state=seed
        )
    if name == "XGBoost":
        from xgboost import XGBClassifier
        return XGBClassifier(
            n_estimators=150, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, tree_method="hist",
            n_jobs=2, random_state=seed, verbosity=0,
        )
    if name == "LightGBM":
        from lightgbm import LGBMClassifier
        return LGBMClassifier(
            n_estimators=150, num_leaves=31, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, n_jobs=2,
            random_state=seed, verbosity=-1,
        )
    if name == "CatBoost":
        from catboost import CatBoostClassifier
        return CatBoostClassifier(
            iterations=150, depth=6, learning_rate=0.05,
            random_seed=seed, thread_count=2, verbose=False,
            allow_writing_files=False,
        )
    raise KeyError(name)


def _fit_predict_worker(name, Xtr, ytr, Xte, seed, q):
    try:
        t0 = time.perf_counter()
        model = make_estimator(name, seed)
        model.fit(Xtr, ytr)
        pred = model.predict(Xte)
        # Some libraries return shape (n,1).
        pred = np.asarray(pred).reshape(-1)
        q.put({"status": "ok", "fit_predict_seconds": time.perf_counter()-t0, "pred": pred})
    except BaseException as exc:
        q.put({
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
            "traceback": traceback.format_exc(limit=8)[:6000],
        })


def isolated_fit_predict(name, Xtr, ytr, Xte, seed, timeout):
    # Linux GitHub runners support fork. Fork keeps the transformed sparse matrix
    # copy-on-write instead of serializing it for every estimator.
    ctx = mp.get_context("fork")
    q = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_fit_predict_worker, args=(name, Xtr, ytr, Xte, seed, q))
    proc.start(); proc.join(timeout)
    if proc.is_alive():
        proc.terminate(); proc.join(15)
        if proc.is_alive():
            proc.kill(); proc.join()
        return {"status": "timeout", "error_type": "Timeout", "error": f">{timeout}s"}
    try:
        return q.get_nowait()
    except queue.Empty:
        return {
            "status": "error", "error_type": "WorkerNoResult",
            "error": f"child exit code {proc.exitcode}",
        }


def cap_rows(X: pd.DataFrame, y: pd.Series, max_rows: int, seed: int):
    if len(y) <= max_rows:
        return X.reset_index(drop=True), y.reset_index(drop=True), False
    rng = np.random.default_rng(seed)
    y_arr = np.asarray(y)
    classes, inverse, counts = np.unique(y_arr, return_inverse=True, return_counts=True)
    # Empirical target guarantees at least five instances/class before capping.
    reserve = np.minimum(5, counts)
    remaining = max_rows - int(reserve.sum())
    capacity = counts - reserve
    if remaining < 0:
        raise RuntimeError("Row budget smaller than five-per-class reserve")
    extra = rng.multivariate_hypergeometric(capacity, remaining) if remaining else np.zeros_like(counts)
    quota = reserve + extra
    chosen = []
    for k, n_take in enumerate(quota):
        idx = np.flatnonzero(inverse == k)
        chosen.extend(rng.choice(idx, size=int(n_take), replace=False).tolist())
    chosen = np.asarray(chosen, dtype=int)
    rng.shuffle(chosen)
    return X.iloc[chosen].reset_index(drop=True), y.iloc[chosen].reset_index(drop=True), True


def prepare_features(X: pd.DataFrame, categorical_indicator):
    X = X.copy()
    cat_cols, num_cols = [], []
    flags = list(categorical_indicator) if categorical_indicator is not None else [False]*X.shape[1]
    if len(flags) != X.shape[1]:
        flags = [False]*X.shape[1]
    for col, is_cat in zip(X.columns, flags):
        if bool(is_cat):
            cat_cols.append(col)
            X[col] = X[col].astype("string").fillna("__MISSING__").astype(str)
        else:
            num_cols.append(col)
            X[col] = pd.to_numeric(X[col], errors="coerce")
    return X, cat_cols, num_cols


def make_preprocessor(cat_cols, num_cols):
    transformers = []
    if num_cols:
        num = Pipeline([
            ("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler(with_mean=False)),
        ])
        transformers.append(("num", num, num_cols))
    if cat_cols:
        cat = Pipeline([
            ("impute", SimpleImputer(strategy="most_frequent", keep_empty_features=True)),
            ("onehot", OneHotEncoder(
                handle_unknown="ignore", min_frequency=2, max_categories=32,
                sparse_output=True, dtype=np.float32,
            )),
        ])
        transformers.append(("cat", cat, cat_cols))
    if not transformers:
        raise RuntimeError("Dataset has no usable feature columns")
    return ColumnTransformer(transformers, sparse_threshold=1.0, remainder="drop")


def append_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    df = pd.DataFrame(rows)
    df.to_csv(path, mode="a", header=not path.exists(), index=False)


def run_problem(row, algorithms, fold_path: Path):
    import openml
    did = int(row.did); tid = int(row.retrieval_task_id)
    t_load = time.perf_counter()
    task = openml.tasks.get_task(tid, download_data=False)
    dataset = task.get_dataset()
    target = task.target_name or str(row.target_feature)
    X, y, categorical_indicator, _ = dataset.get_data(target=target)
    if y is None:
        raise RuntimeError("OpenML returned no target vector")
    if not isinstance(X, pd.DataFrame):
        X = pd.DataFrame(X)
    if not isinstance(y, pd.Series):
        y = pd.Series(np.asarray(y).reshape(-1))
    valid = ~y.isna()
    X, y = X.loc[valid].reset_index(drop=True), y.loc[valid].reset_index(drop=True)
    X, cat_cols, num_cols = prepare_features(X, categorical_indicator)
    # Labels are encoded once; the encoding does not use features or test outcomes.
    le = LabelEncoder(); y_enc = pd.Series(le.fit_transform(y.astype(str)))
    X, y_enc, capped = cap_rows(X, y_enc, MAX_ROWS, SEED + did)
    counts = y_enc.value_counts()
    if len(counts) < 2:
        raise RuntimeError("Target has fewer than two observed classes")
    if int(counts.min()) < N_SPLITS:
        raise RuntimeError(f"Minimum class count after row cap is {int(counts.min())} < {N_SPLITS}")

    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=SEED + did)
    rows = []
    for fold, (tr, te) in enumerate(skf.split(X, y_enc)):
        pre = make_preprocessor(cat_cols, num_cols)
        tprep = time.perf_counter()
        Xtr = pre.fit_transform(X.iloc[tr])
        Xte = pre.transform(X.iloc[te])
        # Normalize matrix representation for third-party learners.
        if sparse.issparse(Xtr):
            Xtr = Xtr.tocsr().astype(np.float32); Xte = Xte.tocsr().astype(np.float32)
        else:
            Xtr = np.asarray(Xtr, dtype=np.float32); Xte = np.asarray(Xte, dtype=np.float32)
        prep_seconds = time.perf_counter() - tprep
        ytr = y_enc.iloc[tr].to_numpy(); yte = y_enc.iloc[te].to_numpy()
        for alg_no, alg in enumerate(algorithms):
            model_seed = SEED + did*1009 + fold*37 + alg_no
            res = isolated_fit_predict(alg, Xtr, ytr, Xte, model_seed, MODEL_TIMEOUT_SECONDS)
            base = {
                "sample_order": int(row.sample_order), "problem_id": row.problem_id,
                "did": did, "retrieval_task_id": tid, "in_cc18": bool(row.in_cc18),
                "sampling_stratum": row.sampling_stratum,
                "stratum_N": int(row.stratum_N), "stratum_n": int(row.stratum_n),
                "inclusion_probability": float(row.inclusion_probability),
                "design_weight": float(row.design_weight),
                "algorithm": alg, "fold": fold,
                "n_rows_original": int(len(valid)), "n_rows_evaluated": int(len(y_enc)),
                "row_cap_applied": capped, "n_features_raw": int(X.shape[1]),
                "n_features_transformed": int(Xtr.shape[1]),
                "n_classes": int(len(counts)), "preprocess_seconds": prep_seconds,
                "status": res.get("status"),
            }
            if res.get("status") == "ok":
                pred = res.pop("pred")
                base.update({
                    "balanced_accuracy": balanced_accuracy_score(yte, pred),
                    "accuracy": accuracy_score(yte, pred),
                    "f1_macro": f1_score(yte, pred, average="macro", zero_division=0),
                    "fit_predict_seconds": res.get("fit_predict_seconds"),
                })
            else:
                base.update({
                    "error_type": res.get("error_type"), "error": res.get("error"),
                })
            rows.append(base)
            append_csv(fold_path, [base])
    return {
        "status": "ok", "load_and_total_seconds": time.perf_counter()-t_load,
        "n_rows_original": int(len(valid)), "n_rows_evaluated": int(len(y_enc)),
        "row_cap_applied": capped, "n_features_raw": int(X.shape[1]),
        "n_classes": int(len(counts)), "model_fold_attempts": len(rows),
        "model_fold_successes": sum(r["status"] == "ok" for r in rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--n-shards", type=int, default=1)
    ap.add_argument("--task-orders", default="")
    ap.add_argument("--algorithms", default=",​".join(ALGORITHMS).replace("​", ""))
    ap.add_argument("--require-success-fraction", type=float, default=0.0)
    args = ap.parse_args()

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(args.manifest)
    if args.task_orders:
        wanted = {int(x) for x in args.task_orders.split(",") if x.strip()}
        work = manifest.loc[manifest.sample_order.isin(wanted)].copy()
    else:
        work = manifest.loc[(manifest.sample_order % args.n_shards) == args.shard].copy()
    work = work.sort_values("sample_order")
    algorithms = [x.strip() for x in args.algorithms.split(",") if x.strip()]
    unknown = set(algorithms) - set(ALGORITHMS)
    if unknown:
        raise ValueError(f"Unknown algorithms: {sorted(unknown)}")

    fold_path = out / f"fold_results_shard_{args.shard}.csv"
    status_path = out / f"task_status_shard_{args.shard}.csv"
    status_rows = []
    for _, row in work.iterrows():
        print(f"TASK_START order={int(row.sample_order)} did={int(row.did)} name={row['name']} stratum={row.sampling_stratum}", flush=True)
        t0 = time.perf_counter()
        try:
            stat = run_problem(row, algorithms, fold_path)
            stat.update({"sample_order": int(row.sample_order), "problem_id": row.problem_id,
                         "did": int(row.did), "sampling_stratum": row.sampling_stratum,
                         "in_cc18": bool(row.in_cc18)})
        except BaseException as exc:
            stat = {
                "sample_order": int(row.sample_order), "problem_id": row.problem_id,
                "did": int(row.did), "sampling_stratum": row.sampling_stratum,
                "in_cc18": bool(row.in_cc18), "status": "task_error",
                "error_type": type(exc).__name__, "error": str(exc)[:3000],
                "traceback": traceback.format_exc(limit=10)[:8000],
                "load_and_total_seconds": time.perf_counter()-t0,
                "model_fold_attempts": 0, "model_fold_successes": 0,
            }
        status_rows.append(stat); append_csv(status_path, [stat])
        print("TASK_END " + json.dumps({k: stat.get(k) for k in ["sample_order","did","status","model_fold_attempts","model_fold_successes","error_type"]}), flush=True)

    attempted = sum(int(x.get("model_fold_attempts", 0) or 0) for x in status_rows)
    successes = sum(int(x.get("model_fold_successes", 0) or 0) for x in status_rows)
    task_ok = sum(x.get("status") == "ok" for x in status_rows)
    summary = {
        "shard": args.shard, "n_shards": args.n_shards,
        "tasks_selected": len(work), "tasks_loaded_and_folded": task_ok,
        "model_fold_attempts": attempted, "model_fold_successes": successes,
        "model_fold_success_fraction": successes/attempted if attempted else 0.0,
        "algorithms": algorithms, "n_splits": N_SPLITS, "max_rows": MAX_ROWS,
        "model_timeout_seconds": MODEL_TIMEOUT_SECONDS,
    }
    (out / f"run_summary_shard_{args.shard}.json").write_text(json.dumps(summary, indent=2, sort_keys=True)+"\n")
    print("RUN_SUMMARY=" + json.dumps(summary, sort_keys=True), flush=True)
    if summary["model_fold_success_fraction"] < args.require_success_fraction:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
