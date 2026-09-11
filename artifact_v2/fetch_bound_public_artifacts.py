#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

API = "https://api.github.com"
UA = "replaymark-artifact-v2-preserver"


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
        if not location or not location.startswith("https://"):
            fail("artifact redirect missing or non-HTTPS")
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
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                fail(f"zip extraction collision: {dst}")
            with zf.open(info) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)


def download_one(repo: str, expected: dict[str, Any], out: Path) -> dict[str, Any]:
    artifact_id = int(expected["id"])
    meta = get_json(f"{API}/repos/{repo}/actions/artifacts/{artifact_id}")
    if meta.get("id") != artifact_id:
        fail(f"artifact id mismatch: {artifact_id}")
    if meta.get("name") != expected["name"]:
        fail(f"artifact name mismatch for {artifact_id}")
    if meta.get("expired") is not False:
        fail(f"artifact is expired: {expected['name']}")
    github_digest = meta.get("digest")
    wanted_digest = expected["zip_sha256"]
    if github_digest != f"sha256:{wanted_digest}":
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
    got = h.hexdigest()
    if got != wanted_digest:
        tmp.unlink(missing_ok=True)
        fail(f"downloaded digest mismatch: {expected['name']} got={got} want={wanted_digest}")

    target = out / expected["target_dir"]
    if target.exists():
        shutil.rmtree(target)
    try:
        safe_extract(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    return {
        "id": meta["id"],
        "name": meta["name"],
        "digest": meta["digest"],
        "expired": meta["expired"],
        "archive_download_url": meta["archive_download_url"],
        "workflow_run": wr,
        "download_transport": transport,
        "github_token_forwarded_to_signed_redirect": False,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-manifest", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    source = json.loads(Path(args.source_manifest).read_text(encoding="utf-8"))
    public = source["public_source_run"]
    if args.repo != public["repository"]:
        fail("repository does not match frozen source manifest")

    authority = source["sealed_authority_artifact"]
    enforcement = source["sealed_enforcement_artifact"]
    expectations = [
        {
            "id": authority["id"],
            "name": authority["name"],
            "zip_sha256": authority["zip_sha256"],
            "run_id": public["run_id"],
            "head_sha": public["head_sha"],
            "target_dir": "authority",
        },
        {
            "id": enforcement["id"],
            "name": enforcement["name"],
            "zip_sha256": enforcement["zip_sha256"],
            "run_id": public["run_id"],
            "head_sha": public["head_sha"],
            "target_dir": "enforcement",
        },
    ]
    for item in source["fresh_public_claim_artifacts"]:
        expectations.append({
            **item,
            "run_id": public["run_id"],
            "head_sha": public["head_sha"],
            "target_dir": f"bound/{item['name']}",
        })

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [download_one(args.repo, expected, out) for expected in expectations]
    meta = {
        "schema": "replaymark.artifact-v2.bound-public-artifacts.v1",
        "source_run": public,
        "artifacts": rows,
    }
    (out / "SOURCE_RUN_ARTIFACTS_METADATA.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"ARTIFACT_V2_FETCH_PASS={len(rows)}")


if __name__ == "__main__":
    main()
