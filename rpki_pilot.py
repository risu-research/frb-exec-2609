#!/usr/bin/env python3
import csv, gzip, hashlib, ipaddress, json, lzma, os, re, shutil, subprocess, sys, time, urllib.request
from collections import defaultdict, Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "_rpki_pilot_data"
OUT = BASE / "results" / "rpki_handoff_pilot_20261002"
DATA.mkdir(exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

# Frozen pilot window: pre / post / persistence check.
DATES = ["20260901", "20260908", "20260915"]
RRC = "rrc00"
MIN_PEERS = 8
DOM_SHARE = 0.80
TARGET_N = 100
USER_AGENT = "risu-research-rpki-pilot/1.0"


def log(msg):
    print(msg, flush=True)


def fetch(url, dest, retries=4):
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, length=1024*1024)
            tmp.replace(dest)
            log(f"downloaded {url} -> {dest} ({dest.stat().st_size} bytes)")
            return dest
        except Exception as e:
            log(f"download failed [{i+1}/{retries}] {url}: {e}")
            try: tmp.unlink()
            except FileNotFoundError: pass
            time.sleep(2 ** i)
    raise RuntimeError(f"failed download: {url}")


def bview_url(date):
    ym = date[:4] + "." + date[4:6]
    return f"https://data.ris.ripe.net/{RRC}/{ym}/bview.{date}.0000.gz"


def parse_bview(date, only_prefixes=None):
    gz = fetch(bview_url(date), DATA / f"bview.{date}.0000.gz")
    counts = defaultdict(Counter)
    totals = Counter()
    cmd = ["bgpdump", "-m", str(gz)]
    log("parsing " + " ".join(cmd))
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    assert p.stdout is not None
    for line in p.stdout:
        parts = line.rstrip("\n").split("|")
        if len(parts) < 7:
            continue
        prefix = parts[5]
        if only_prefixes is not None and prefix not in only_prefixes:
            continue
        if ":" in prefix:
            continue
        as_path = parts[6].strip()
        if not as_path:
            continue
        origin = as_path.split()[-1]
        if not origin.isdigit():
            continue
        try:
            net = ipaddress.ip_network(prefix, strict=False)
            if net.version != 4:
                continue
        except ValueError:
            continue
        counts[prefix][origin] += 1
        totals[prefix] += 1
    err = p.stderr.read() if p.stderr else ""
    rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"bgpdump failed rc={rc}: {err[-4000:]}")
    dom = {}
    for prefix, c in counts.items():
        n = totals[prefix]
        origin, k = c.most_common(1)[0]
        dom[prefix] = {"origin": origin, "share": k / n, "peers": n, "origins": len(c)}
    log(f"{date}: {len(dom)} IPv4 prefixes")
    return dom


def get_root_anchors():
    req = urllib.request.Request("https://ftp.ripe.net/rpki/", headers={"User-Agent": USER_AGENT})
    html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    hrefs = re.findall(r'href=["\']([^"\']+/)["\']', html, flags=re.I)
    anchors = []
    for h in hrefs:
        h = h.strip()
        if h in ("../", "./") or "://" in h:
            continue
        name = h.strip("/")
        if name and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            anchors.append(name)
    anchors = sorted(set(anchors))
    log(f"archive anchors discovered: {anchors}")
    return anchors


def find_col(fieldnames, candidates):
    norm = {re.sub(r"[^a-z0-9]", "", x.lower()): x for x in fieldnames if x}
    for cand in candidates:
        c = re.sub(r"[^a-z0-9]", "", cand.lower())
        if c in norm:
            return norm[c]
    return None


def load_vrps_for_candidates(date, candidates, anchors):
    # Return candidate prefix -> list of covering VRPs. We intentionally preserve
    # covering aggregate ROAs, since exact-prefix-only joins are incorrect.
    cand_nets = {}
    by_octet = defaultdict(list)
    for pfx in candidates:
        net = ipaddress.ip_network(pfx, strict=False)
        cand_nets[pfx] = net
        by_octet[int(str(net.network_address).split('.')[0])].append(pfx)
    out = defaultdict(list)
    files_ok = []
    y, m, d = date[:4], date[4:6], date[6:8]
    for anchor in anchors:
        url = f"https://ftp.ripe.net/rpki/{anchor}/{y}/{m}/{d}/roas.csv.xz"
        dest = DATA / f"roas.{anchor}.{date}.csv.xz"
        try:
            fetch(url, dest, retries=2)
        except Exception:
            continue
        files_ok.append(anchor)
        with lzma.open(dest, "rt", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                continue
            pcol = find_col(reader.fieldnames, ["IP Prefix", "prefix"])
            acol = find_col(reader.fieldnames, ["ASN", "asn"])
            mcol = find_col(reader.fieldnames, ["Max Length", "maxLength", "max_length"])
            if not pcol or not acol:
                raise RuntimeError(f"unexpected ROA CSV header {reader.fieldnames}")
            for row in reader:
                rawp = (row.get(pcol) or "").strip()
                rawa = (row.get(acol) or "").strip().upper().removeprefix("AS")
                if not rawp or not rawa.isdigit() or ":" in rawp:
                    continue
                try:
                    vnet = ipaddress.ip_network(rawp, strict=False)
                except ValueError:
                    continue
                if vnet.version != 4:
                    continue
                rawm = (row.get(mcol) or "").strip() if mcol else ""
                try:
                    maxlen = int(rawm) if rawm else vnet.prefixlen
                except ValueError:
                    maxlen = vnet.prefixlen
                if vnet.prefixlen >= 8:
                    octs = [int(str(vnet.network_address).split('.')[0])]
                    plist = by_octet.get(octs[0], [])
                else:
                    plist = candidates
                if not plist:
                    continue
                vs, ve = int(vnet.network_address), int(vnet.broadcast_address)
                for pfx in plist:
                    cnet = cand_nets[pfx]
                    cs, ce = int(cnet.network_address), int(cnet.broadcast_address)
                    if vs <= cs and ce <= ve:
                        out[pfx].append((rawa, vnet.prefixlen, maxlen, rawp, anchor))
    log(f"{date}: loaded covering VRPs from {len(files_ok)} anchors: {files_ok}")
    return out, files_ok


def status(pfx, origin, coverings):
    plen = ipaddress.ip_network(pfx, strict=False).prefixlen
    cov = coverings.get(pfx, [])
    if not cov:
        return "notfound"
    for asn, _vplen, maxlen, _rawp, _anchor in cov:
        if asn == str(origin) and plen <= maxlen:
            return "valid"
    return "invalid"


def hkey(s):
    return hashlib.sha256(s.encode()).hexdigest()


def main():
    d0, d1, d2 = DATES
    dom0 = parse_bview(d0)
    dom1 = parse_bview(d1)
    candidates = []
    for pfx, a in dom0.items():
        b = dom1.get(pfx)
        if not b:
            continue
        if a["origin"] == b["origin"]:
            continue
        if min(a["peers"], b["peers"]) < MIN_PEERS:
            continue
        if min(a["share"], b["share"]) < DOM_SHARE:
            continue
        candidates.append(pfx)
    log(f"raw dominant-origin changes {d0}->{d1}: {len(candidates)}")
    dom2 = parse_bview(d2, set(candidates))
    persistent = []
    for pfx in candidates:
        c = dom2.get(pfx)
        if not c:
            continue
        if c["origin"] != dom1[pfx]["origin"]:
            continue
        if c["peers"] < MIN_PEERS or c["share"] < DOM_SHARE:
            continue
        persistent.append(pfx)
    log(f"persistent through {d2}: {len(persistent)}")
    selected = sorted(persistent, key=hkey)[:TARGET_N]
    if len(selected) < min(50, TARGET_N):
        raise RuntimeError(f"too few persistent transitions: {len(selected)}")
    log(f"deterministic sample size: {len(selected)}")

    anchors = get_root_anchors()
    cov = {}
    anchor_meta = {}
    for date in DATES:
        cov[date], anchor_meta[date] = load_vrps_for_candidates(date, selected, anchors)

    rows = []
    for pfx in selected:
        A = dom0[pfx]["origin"]
        B = dom1[pfx]["origin"]
        rec = {
            "prefix": pfx,
            "old_origin_A": A,
            "new_origin_B": B,
            "d0": d0, "d1": d1, "d2": d2,
            "A_share_d0": round(dom0[pfx]["share"], 4),
            "B_share_d1": round(dom1[pfx]["share"], 4),
            "B_share_d2": round(dom2[pfx]["share"], 4),
            "peers_d0": dom0[pfx]["peers"],
            "peers_d1": dom1[pfx]["peers"],
            "peers_d2": dom2[pfx]["peers"],
            "A_status_d0": status(pfx, A, cov[d0]),
            "B_status_d0": status(pfx, B, cov[d0]),
            "A_status_d1": status(pfx, A, cov[d1]),
            "B_status_d1": status(pfx, B, cov[d1]),
            "A_status_d2": status(pfx, A, cov[d2]),
            "B_status_d2": status(pfx, B, cov[d2]),
            "covering_vrps_d0": len(cov[d0].get(pfx, [])),
            "covering_vrps_d1": len(cov[d1].get(pfx, [])),
            "covering_vrps_d2": len(cov[d2].get(pfx, [])),
        }
        rec["new_preauthorized_d0"] = rec["B_status_d0"] == "valid"
        rec["new_invalid_d1"] = rec["B_status_d1"] == "invalid"
        rec["new_notvalid_d1"] = rec["B_status_d1"] != "valid"
        rec["old_lingering_valid_d1"] = rec["A_status_d1"] == "valid"
        rec["old_lingering_valid_d2"] = rec["A_status_d2"] == "valid"
        rec["dual_valid_d1"] = rec["A_status_d1"] == "valid" and rec["B_status_d1"] == "valid"
        rows.append(rec)

    with open(OUT / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    n = len(rows)
    def count(k): return sum(bool(r[k]) for r in rows)
    summary = {
        "design": {
            "collector": RRC,
            "dates": DATES,
            "min_peer_observations": MIN_PEERS,
            "dominant_origin_share_threshold": DOM_SHARE,
            "sampling": "sha256(prefix)-ordered deterministic first N",
            "target_n": TARGET_N,
            "raw_origin_changes": len(candidates),
            "persistent_origin_changes": len(persistent),
            "sample_n": n,
            "note": "Pilot uses three RIB/VRP snapshots. It establishes coarse-grained signal, not exact handoff timestamps or ownership intent. 'Lingering' means the old origin remained RPKI-valid after B became persistently dominant; it is not automatically stale/misconfigured.",
        },
        "rpki_archive_anchors_used": anchor_meta,
        "counts": {
            "new_origin_preauthorized_at_d0": count("new_preauthorized_d0"),
            "new_origin_invalid_at_d1": count("new_invalid_d1"),
            "new_origin_not_valid_at_d1": count("new_notvalid_d1"),
            "old_origin_still_valid_at_d1": count("old_lingering_valid_d1"),
            "old_origin_still_valid_at_d2": count("old_lingering_valid_d2"),
            "both_old_and_new_valid_at_d1": count("dual_valid_d1"),
        },
    }
    summary["rates"] = {k: (v/n if n else None) for k,v in summary["counts"].items()}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# RPKI origin-handoff pilot (2026-10-02)", "",
        "## Frozen design", "",
        f"- RIPE RIS collector: `{RRC}`", f"- RIB dates: {', '.join(DATES)}",
        f"- Dominance: >= {DOM_SHARE:.0%}, >= {MIN_PEERS} peer observations",
        f"- Persistent transition: A at d0; B at d1 and d2 with the same dominance rule",
        f"- Deterministic sample: SHA-256(prefix) order, first {n}",
        "- RPKI validity computed from all covering VRPs, including aggregate ROAs and maxLength.",
        "- This is a coarse kill/keep pilot, not a minute-level handoff-timing estimate.", "",
        "## Results", "",
    ]
    for k,v in summary["counts"].items():
        lines.append(f"- **{k}**: {v}/{n} ({(v/n if n else 0):.1%})")
    lines += ["", "## Interpretation guardrail", "",
              "`old_origin_still_valid` is deliberately called *lingering authorization*, not stale authorization: a multi-origin/failover configuration can legitimately authorize A after B becomes dominant. A full study must classify intent or use stronger transition filters before making a security claim.", ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    log(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
