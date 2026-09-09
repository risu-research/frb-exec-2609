#!/usr/bin/env python3
import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.github.com"
UA = "qx-v6-public-substrate-v2"


def _token():
    token = os.environ.get("SOURCE_READ_TOKEN", "").strip()
    if not token:
        raise SystemExit("SOURCE_READ_TOKEN is required")
    return token


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
    }


def _json(url):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def resolve_repo(sha):
    repos = []
    for page in range(1, 11):
        batch = _json(
            f"{API}/user/repos?per_page=100&page={page}&visibility=private&"
            "affiliation=owner,organization_member,collaborator"
        )
        repos.extend(batch)
        if len(batch) < 100:
            break
    matches = []
    for item in repos:
        full = item.get("full_name")
        if not full:
            continue
        try:
            req = urllib.request.Request(f"{API}/repos/{full}/commits/{sha}", headers=_headers())
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200:
                    matches.append(full)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404, 409, 422):
                continue
            raise
    if len(matches) != 1:
        raise SystemExit(f"exact_source_match_count={len(matches)}; expected=1")
    return matches[0]


def clone_exact(sha, dest):
    repo = resolve_repo(sha)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    subprocess.run(["git", "init", "-q", str(dest)], check=True)
    url = f"https://x-access-token:{_token()}@github.com/{repo}.git"
    subprocess.run(["git", "-C", str(dest), "remote", "add", "origin", url], check=True)
    subprocess.run(["git", "-C", str(dest), "fetch", "-q", "--depth=2", "origin", sha], check=True)
    got = subprocess.check_output(["git", "-C", str(dest), "rev-parse", "FETCH_HEAD"], text=True).strip()
    if got != sha:
        raise SystemExit(f"source sha mismatch: {got}")
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
    subprocess.run(["git", "-C", str(dest), "remote", "remove", "origin"], check=True)
    print("exact_private_source_checkout=PASS")


def snapshot(sha, run_id, out):
    repo = resolve_repo(sha)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base = f"{API}/repos/{repo}/actions/runs/{run_id}"
    docs = {
        "run.json": _json(base),
        "jobs-page1.json": _json(base + "/jobs?per_page=100&page=1"),
        "jobs-page2.json": _json(base + "/jobs?per_page=100&page=2"),
        "artifacts.json": _json(base + "/artifacts?per_page=100&page=1"),
    }
    for name, value in docs.items():
        (out / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("private_source_snapshot=PASS")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_artifact_archive(api_url):
    """Authenticate only to GitHub's archive endpoint, never to its signed redirect target."""
    req = urllib.request.Request(api_url, headers=_headers())
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        return opener.open(req, timeout=120), "direct"
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise
        location = exc.headers.get("Location")
        if not location:
            raise RuntimeError("artifact redirect missing Location header")
        parsed = urllib.parse.urlsplit(location)
        if parsed.scheme.lower() != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise RuntimeError("refusing unsafe artifact redirect target")
        # Deliberately omit Authorization, GitHub Accept, and API version headers.
        # The Location is a short-lived signed object-storage URL and carries its own authorization.
        redirected = urllib.request.Request(location, headers={"User-Agent": UA})
        return urllib.request.urlopen(redirected, timeout=120), "signed-redirect-without-source-token"


def _safe_extract(zf, target, flatten):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        if info.is_dir():
            continue
        raw = Path(info.filename)
        if raw.is_absolute() or ".." in raw.parts:
            raise RuntimeError("unsafe zip path")
        rel = Path(raw.name) if flatten else raw
        dst = target / rel
        if dst.exists():
            raise RuntimeError(f"artifact extraction collision: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(dst, "wb") as dstf:
            shutil.copyfileobj(src, dstf)


def download(sha, run_id, patterns, out, flatten=False, manifest=None):
    repo = resolve_repo(sha)
    meta = _json(f"{API}/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100&page=1")
    artifacts = meta.get("artifacts", [])
    selected = [
        a for a in artifacts
        if not a.get("expired") and any(fnmatch.fnmatch(a.get("name", ""), p) for p in patterns)
    ]
    names = [a["name"] for a in selected]
    if len(names) != len(set(names)):
        raise RuntimeError("duplicate artifact names in source metadata")
    if not selected:
        raise RuntimeError("no artifacts matched requested patterns")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for artifact in sorted(selected, key=lambda a: a["name"]):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
            tmp = Path(tf.name)
            h = hashlib.sha256()
            response, transport = _open_artifact_archive(artifact["archive_download_url"])
            with response as r:
                while True:
                    chunk = r.read(1024 * 1024)
                    if not chunk:
                        break
                    tf.write(chunk)
                    h.update(chunk)
        got_digest = h.hexdigest()
        github_digest = artifact.get("digest")
        if github_digest:
            prefix, sep, want_digest = github_digest.partition(":")
            if sep != ":" or prefix.lower() != "sha256" or len(want_digest) != 64:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"unsupported GitHub artifact digest: {github_digest}")
            if got_digest.lower() != want_digest.lower():
                tmp.unlink(missing_ok=True)
                raise RuntimeError(
                    f"artifact digest mismatch for {artifact['name']}: got={got_digest} want={want_digest}"
                )
        target = out if flatten else out / artifact["name"]
        try:
            with zipfile.ZipFile(tmp) as zf:
                _safe_extract(zf, target, flatten)
        finally:
            tmp.unlink(missing_ok=True)
        manifest_rows.append({
            "artifact_id": artifact["id"],
            "name": artifact["name"],
            "github_digest": github_digest,
            "downloaded_zip_sha256": got_digest,
            "transport": transport,
            "source_token_forwarded_to_redirect": False,
        })
    if manifest:
        Path(manifest).parent.mkdir(parents=True, exist_ok=True)
        Path(manifest).write_text(json.dumps(manifest_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"private_source_artifacts_downloaded={len(selected)}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("clone")
    c.add_argument("--sha", required=True)
    c.add_argument("--dest", required=True)

    s = sub.add_parser("snapshot")
    s.add_argument("--sha", required=True)
    s.add_argument("--run-id", required=True, type=int)
    s.add_argument("--out", required=True)

    d = sub.add_parser("download")
    d.add_argument("--sha", required=True)
    d.add_argument("--run-id", required=True, type=int)
    d.add_argument("--pattern", action="append", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--flatten", action="store_true")
    d.add_argument("--manifest")

    args = p.parse_args()
    if args.cmd == "clone":
        clone_exact(args.sha, args.dest)
    elif args.cmd == "snapshot":
        snapshot(args.sha, args.run_id, args.out)
    elif args.cmd == "download":
        download(args.sha, args.run_id, args.pattern, args.out, args.flatten, args.manifest)


if __name__ == "__main__":
    main()
