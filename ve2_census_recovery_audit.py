from __future__ import annotations

"""Classification-free raw Git-history recovery for VE2 census repair."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

SNAPSHOT = "d24bcf2da30b8dbaaf99c0a14ec91f3c3b58e942"
UPSTREAM = "https://github.com/KartoffelToby/better_thermostat.git"


def sh(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def versions(repo: Path, path: str) -> list[dict[str, str]]:
    commits = sh("git", "log", "--format=%H", "--reverse", SNAPSHOT, "--", path, cwd=repo).splitlines()
    out: list[dict[str, str]] = []
    for commit in commits:
        try:
            blob = sh("git", "rev-parse", f"{commit}:{path}", cwd=repo)
        except subprocess.CalledProcessError:
            continue
        if not out or out[-1]["blob"] != blob:
            out.append({"commit": commit, "blob": blob})
    return out


def safe_name(path: str) -> str:
    return path.replace("/", "__").removesuffix(".yaml")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--work", required=True)
    p.add_argument("--out-root", required=True)
    args = p.parse_args()
    work = Path(args.work)
    root = Path(args.out_root)
    work.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    repo = work / "better_thermostat"
    subprocess.check_call(["git", "clone", "--quiet", "--no-tags", UPSTREAM, str(repo)])
    sh("git", "cat-file", "-e", f"{SNAPSHOT}^{{commit}}", cwd=repo)

    paths = sh("git", "ls-tree", "-r", "--name-only", SNAPSHOT, "--", "blueprints", cwd=repo).splitlines()
    paths = sorted(x for x in paths if x.startswith("blueprints/") and "/" not in x[len("blueprints/"):])
    histories: dict[str, list[dict[str, str]]] = {}
    pair_count = 0
    source_records: list[dict[str, str | int]] = []
    diff_records: list[dict[str, str | int]] = []

    for path in paths:
        hist = versions(repo, path)
        assert hist, path
        histories[path] = hist
        stem = safe_name(path)
        source_dir = root / "sources" / stem
        diff_dir = root / "diffs" / stem
        source_dir.mkdir(parents=True, exist_ok=True)
        diff_dir.mkdir(parents=True, exist_ok=True)
        for idx, item in enumerate(hist):
            raw = subprocess.check_output(["git", "show", f"{item['commit']}:{path}"], cwd=repo)
            assert sh("git", "rev-parse", f"{item['commit']}:{path}", cwd=repo) == item["blob"]
            out = source_dir / f"{idx:02d}-{item['commit']}.yaml"
            out.write_bytes(raw)
            source_records.append({
                "path": path,
                "index": idx,
                "commit": item["commit"],
                "git_blob_sha1": item["blob"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "artifact_path": out.relative_to(root).as_posix(),
            })
        for idx, (old, new) in enumerate(zip(hist, hist[1:])):
            pair_count += 1
            patch = subprocess.check_output(
                ["git", "diff", "--no-ext-diff", "--unified=20", old["commit"], new["commit"], "--", path],
                cwd=repo,
            )
            out = diff_dir / f"{idx:02d}-{old['commit'][:12]}-to-{new['commit'][:12]}.patch"
            out.write_bytes(patch)
            diff_records.append({
                "path": path,
                "pair_index": idx,
                "old_commit": old["commit"],
                "old_blob": old["blob"],
                "new_commit": new["commit"],
                "new_blob": new["blob"],
                "patch_sha256": hashlib.sha256(patch).hexdigest(),
                "artifact_path": out.relative_to(root).as_posix(),
            })

    result = {
        "schema": "replaymark.ve2.raw-history-recovery.v1",
        "status": "PASS",
        "upstream_repository": "KartoffelToby/better_thermostat",
        "snapshot_head": SNAPSHOT,
        "paths": paths,
        "file_count": len(paths),
        "histories": histories,
        "file_version_count": sum(len(v) for v in histories.values()),
        "adjacent_pair_count": pair_count,
        "source_records": source_records,
        "diff_records": diff_records,
        "eligibility_classification_performed": False,
        "frontier_prediction_opened": False,
        "scientific_result_opened": False,
        "ve2_home_assistant_scientific_cells": 0,
        "ve2_replaymark_scientific_cells": 0,
    }
    (root / "VE2_RAW_HISTORY_RECOVERY_V1.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
