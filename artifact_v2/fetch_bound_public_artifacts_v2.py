#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

API = "https://api.github.com"
UA = "replaymark-artifact-v2-preserver-v2"


def fail(message: str) -> None:
    raise SystemExit(f"ARTIFACT_V2_FETCH_FAIL: {message}")


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN", "").strip()
    if not value:
        fail("GITHUB_TOKEN is required")
    return value


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
    }


def get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers())
    with urllib.request.urlopen(req, timeout=60) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        fail(f"expected JSON object from {url}")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None


def open_archive(api_url: str):
    """Authenticate to GitHub only; never forward GITHUB_TOKEN to signed storage."""
    req = urllib.request.Request(api_url, headers=headers())
    opener = urllib.request.build_opener(NoRedirect)
    try:
        return opener.open(req, timeout=120), "direct"
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        if not location:
            fail("artifact redirect missing Location")
        parsed = urllib.parse.urlsplit(location)
        if parsed.scheme.lower() != "https" or not parsed.netloc or parsed.username or parsed.password:
            fail("refusing unsafe artifact redirect target")
        redirected = urllib.request.Request(location, headers={"User-Agent": UA})
        return urllib.request.urlopen(redirected, timeout=120), "signed-redirect-without-github-token"


def safe_extract(zip_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            raw = Path(info.filename)
            if raw.is_absolute() or ".." in raw.parts:
                fail(f"unsafe zip path: {info.filename}")
            if info.is_dir():
                continue
            dst = target / raw
            if dst.exists():
                fail(f"zip extraction collision: {dst}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)


def download_one(repo: str, expected: dict[str, Any], out: Path, preserve_zips: Path | None) -> dict[str, Any]:
    artifact_id = int(expected["id"])
    meta = get_json(f"{API}/repos/{repo}/actions/artifacts/{artifact_id}")
    if meta.get("id") != artifact_id:
        fail(f"artifact id mismatch: {artifact_id}")
    if meta.get("name") != expected["name"]:
        fail(f"artifact name mismatch for {artifact_id}")
    if meta.get("expired") is not False:
        fail(f"artifact is expired: {expected['name']}")
    wanted_digest = str(expected["zip_sha256"])
    if meta.get("digest") != f"sha256:{wanted_digest}":
        fail(f"GitHub digest mismatch before download: {expected['name']}")
    wr = meta.get("workflow_run") or {}
    if int(wr.get("id", -1)) != int(expected["run_id"]):
        fail(f"workflow run mismatch: {expected['name']}")
    if wr.get("head_sha") != expected["head_sha"]:
        fail(f"workflow head mismatch: {expected['name']}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
        tmp = Path(tf.name)
        h = hashlib.sha256()
        response, transport = open_archive(meta["archive_download_url"])
        with response as r:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                tf.write(chunk)
                h.update(chunk)
    try:
        got = h.hexdigest()
        if got != wanted_digest:
            fail(f"downloaded digest mismatch: {expected['name']} got={got} want={wanted_digest}")
        if preserve_zips is not None:
            preserve_zips.mkdir(parents=True, exist_ok=True)
            dst_zip = preserve_zips / f"{expected['name']}.zip"
            if dst_zip.exists():
                dst_zip.unlink()
            shutil.copyfile(tmp, dst_zip)
        target = out / expected["target_dir"]
        if target.exists():
            shutil.rmtree(target)
        safe_extract(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    return {
        "id": meta["id"],
        "name": meta["name"],
        "digest": meta["digest"],
        "size_in_bytes": meta.get("size_in_bytes"),
        "expired": meta["expired"],
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
        "workflow_run": wr,
        "downloaded_zip_sha256": wanted_digest,
        "download_transport": transport,
        "github_token_forwarded_to_signed_redirect": False,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-manifest", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--preserve-zips-dir")
    args = p.parse_args()

    source = json.loads(Path(args.source_manifest).read_text(encoding="utf-8"))
    public = source["public_source_run"]
    if args.repo != public["repository"]:
        fail("repository does not match frozen source manifest")

    run = get_json(f"{API}/repos/{args.repo}/actions/runs/{public['run_id']}")
    checks = {
        "id": run.get("id") == public["run_id"],
        "run_attempt": run.get("run_attempt") == public["run_attempt"],
        "head_branch": run.get("head_branch") == public["branch"],
        "head_sha": run.get("head_sha") == public["head_sha"],
        "conclusion": run.get("conclusion") == public["workflow_conclusion"],
    }
    if not all(checks.values()):
        fail(f"source run metadata mismatch: {checks}")

    authority = source["sealed_authority_artifact"]
    enforcement = source["sealed_enforcement_artifact"]
    expectations = [
        {**authority, "run_id": public["run_id"], "head_sha": public["head_sha"], "target_dir": "authority"},
        {**enforcement, "run_id": public["run_id"], "head_sha": public["head_sha"], "target_dir": "enforcement"},
    ]
    for item in source["fresh_public_claim_artifacts"]:
        expectations.append({**item, "run_id": public["run_id"], "head_sha": public["head_sha"], "target_dir": f"bound/{item['name']}"})

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    preserve = Path(args.preserve_zips_dir) if args.preserve_zips_dir else None
    rows = [download_one(args.repo, expected, out, preserve) for expected in expectations]
    snapshot = {
        "schema": "replaymark.artifact-v2.bound-public-source-snapshot.v2",
        "source_run_expected": public,
        "source_run_observed": {
            "id": run.get("id"),
            "run_attempt": run.get("run_attempt"),
            "head_branch": run.get("head_branch"),
            "head_sha": run.get("head_sha"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "event": run.get("event"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
        },
        "run_checks": checks,
        "artifacts": rows,
    }
    (out / "SOURCE_RUN_SNAPSHOT.json").write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ARTIFACT_V2_FETCH_PASS={len(rows)}")


if __name__ == "__main__":
    main()
