#!/usr/bin/env python3
import csv, hashlib, ipaddress, io, json, lzma, os, statistics, sys, time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests
from pybgpkit_parser import Parser

START_DT = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
END_DT = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
RIB0 = "https://data.ris.ripe.net/rrc00/2026.09/bview.20260915.0000.gz"
RIB1 = "https://data.ris.ripe.net/rrc00/2026.10/bview.20261001.0000.gz"
CACHE = ".cache"
MAX_CANDIDATES = 60
MIN_ENTRIES = 12
TALS = ["afrinic.tal", "apnic.tal", "arin.tal", "lacnic.tal", "ripencc.tal"]
RPKI_START = date(2026, 9, 1)
RPKI_END = date(2026, 10, 2)
OUTDIR = "out"

os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUTDIR, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "public-measurement-pilot/1.0"})


def origin_from_path(path):
    if not path:
        return None
    tok = str(path).strip().split()[-1]
    if not tok.isdigit():
        return None
    n = int(tok)
    if n <= 0 or n == 23456:
        return None
    return n


def ipv4_ok(prefix):
    if ":" in prefix:
        return False
    try:
        n = ipaddress.ip_network(prefix, strict=False)
        return n.version == 4 and 8 <= n.prefixlen <= 24
    except Exception:
        return False


def scan_unanimous(url):
    origins = {}
    counts = defaultdict(int)
    p = Parser(url=url, cache_dir=CACHE)
    fields = ["prefix", "as_path"]
    for batch in p.iter_tuple_batches(fields, batch_size=100000):
        for prefix, as_path in batch:
            if not ipv4_ok(prefix):
                continue
            origin = origin_from_path(as_path)
            if origin is None:
                continue
            counts[prefix] += 1
            prev = origins.get(prefix)
            if prev is None:
                origins[prefix] = origin
            elif prev != 0 and prev != origin:
                origins[prefix] = 0
    return origins, counts


def collect_peer_states(url, prefixes):
    wanted = set(prefixes)
    states = {p: {} for p in prefixes}
    parser = Parser(url=url, cache_dir=CACHE)
    fields = ["peer_ip", "prefix", "as_path"]
    for batch in parser.iter_tuple_batches(fields, batch_size=100000):
        for peer_ip, prefix, as_path in batch:
            if prefix not in wanted:
                continue
            o = origin_from_path(as_path)
            if o is None:
                continue
            old = states[prefix].get(peer_ip)
            if old is None:
                states[prefix][peer_ip] = o
            elif old != o:
                states[prefix][peer_ip] = 0
    for p in prefixes:
        states[p] = {k:v for k,v in states[p].items() if v}
    return states


def ripe_updates(prefix, old_asn, new_asn, initial_peer_state):
    params = {
        "resource": prefix,
        "starttime": START_DT.isoformat().replace("+00:00", "Z"),
        "endtime": END_DT.isoformat().replace("+00:00", "Z"),
        "rrcs": "0",
        "unix_timestamps": "TRUE",
    }
    url = "https://stat.ripe.net/data/bgp-updates/data.json"
    r = S.get(url, params=params, timeout=90)
    r.raise_for_status()
    data = r.json().get("data", {})
    updates = data.get("updates", [])

    state = dict(initial_peer_state)
    first_b = None
    b50 = None
    b90 = None
    a_zero = None
    max_active = 0
    exact_events = 0

    def frac_counts():
        vals = [v for v in state.values() if v]
        if not vals:
            return 0, 0, 0
        a = sum(v == old_asn for v in vals)
        b = sum(v == new_asn for v in vals)
        return a, b, len(vals)

    for u in updates:
        attrs = u.get("attrs", {}) or {}
        if attrs.get("target_prefix") != prefix:
            continue
        exact_events += 1
        src = str(attrs.get("source_id", ""))
        peer = src.split("-", 1)[1] if "-" in src else src
        typ = u.get("type")
        ts_raw = u.get("timestamp")
        try:
            ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
        except Exception:
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            except Exception:
                continue
        if typ == "A":
            path = attrs.get("path") or []
            if path:
                try:
                    o = int(path[-1])
                except Exception:
                    o = None
                if o:
                    state[peer] = o
                    if o == new_asn and first_b is None:
                        first_b = ts
        elif typ == "W":
            state[peer] = None
        a, b, n = frac_counts()
        max_active = max(max_active, n)
        if n >= 5 and b / n >= 0.5 and b50 is None:
            b50 = ts
        if n >= 5 and b / n >= 0.9 and b90 is None:
            b90 = ts
        if b50 is not None and a == 0 and n >= 5 and a_zero is None:
            a_zero = ts

    return {
        "nr_updates": data.get("nr_updates", len(updates)),
        "exact_events": exact_events,
        "first_new": first_b.isoformat() if first_b else None,
        "new_50": b50.isoformat() if b50 else None,
        "new_90": b90.isoformat() if b90 else None,
        "old_zero": a_zero.isoformat() if a_zero else None,
        "max_active": max_active,
    }


def supernet_strings(prefix):
    n = ipaddress.ip_network(prefix, strict=False)
    return [str(n)] + [str(x) for x in n.supernets()]


def parse_roa_csv_xz(content, wanted_prefixes):
    raw = lzma.decompress(content).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    out = defaultdict(list)
    for row in reader:
        pfx = row.get("IP Prefix") or row.get("prefix") or row.get("Prefix")
        if not pfx or pfx not in wanted_prefixes:
            continue
        a = row.get("ASN") or row.get("asn")
        ml = row.get("Max Length") or row.get("maxLength") or row.get("max_length")
        if a is None or ml is None:
            continue
        try:
            asn = int(str(a).strip().upper().replace("AS", ""))
            maxlen = int(ml)
        except Exception:
            continue
        out[pfx].append((asn, maxlen))
    return out


def valid_for(prefix, asn, roa_by_prefix, supers):
    plen = ipaddress.ip_network(prefix, strict=False).prefixlen
    for sp in supers[prefix]:
        for ra, ml in roa_by_prefix.get(sp, []):
            if ra == asn and plen <= ml:
                return True
    return False


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def main():
    print("scan start rib", flush=True)
    o0, c0 = scan_unanimous(RIB0)
    print("scan end rib", flush=True)
    o1, c1 = scan_unanimous(RIB1)

    changes = []
    for p in set(o0).intersection(o1):
        a, b = o0[p], o1[p]
        if not a or not b or a == b:
            continue
        support = min(c0.get(p, 0), c1.get(p, 0))
        if support < MIN_ENTRIES:
            continue
        changes.append((support, p, a, b))
    changes.sort(key=lambda x: (-x[0], hashlib.sha256(x[1].encode()).hexdigest()))
    chosen = changes[:MAX_CANDIDATES]
    if len(chosen) < 20:
        raise RuntimeError(f"too few candidate changes: {len(chosen)}")

    prefixes = [x[1] for x in chosen]
    print(f"candidate changes={len(changes)} chosen={len(chosen)}", flush=True)
    peer0 = collect_peer_states(RIB0, prefixes)
    peer1 = collect_peer_states(RIB1, prefixes)

    records = []
    for i, (support, p, a, b) in enumerate(chosen, 1):
        rec = {
            "prefix": p, "old_asn": a, "new_asn": b, "rib_support": support,
            "start_peers": len(peer0[p]), "end_peers": len(peer1[p]),
            "end_new_fraction": (sum(v == b for v in peer1[p].values()) / len(peer1[p])) if peer1[p] else None,
        }
        try:
            rec["bgp"] = ripe_updates(p, a, b, peer0[p])
        except Exception as e:
            rec["bgp"] = {"error": repr(e)}
        records.append(rec)
        print(f"updates {i}/{len(chosen)}", flush=True)
        time.sleep(0.08)

    supers = {p: supernet_strings(p) for p in prefixes}
    wanted_roa_prefixes = set(x for p in prefixes for x in supers[p])
    daily = {p: {} for p in prefixes}

    for d in daterange(RPKI_START, RPKI_END):
        merged = defaultdict(list)
        ok_files = 0
        for tal in TALS:
            u = f"https://ftp.ripe.net/rpki/{tal}/{d.year:04d}/{d.month:02d}/{d.day:02d}/roas.csv.xz"
            try:
                r = S.get(u, timeout=90)
                if r.status_code != 200:
                    continue
                part = parse_roa_csv_xz(r.content, wanted_roa_prefixes)
                for k, vals in part.items():
                    merged[k].extend(vals)
                ok_files += 1
            except Exception as e:
                print(f"roa fetch/parse skip {d} {tal}: {e}", flush=True)
        if ok_files == 0:
            print(f"no roa files {d}", flush=True)
            continue
        ds = d.isoformat()
        by_p = {r["prefix"]: r for r in records}
        for p in prefixes:
            rec = by_p[p]
            daily[p][ds] = {
                "old": valid_for(p, rec["old_asn"], merged, supers),
                "new": valid_for(p, rec["new_asn"], merged, supers),
            }
        print(f"roa day {d} files={ok_files}", flush=True)

    def parse_ts(x):
        return datetime.fromisoformat(x.replace("Z", "+00:00")) if x else None

    for rec in records:
        p = rec["prefix"]
        states = daily[p]
        days = sorted(states)
        new_days = [d for d in days if states[d]["new"]]
        old_days = [d for d in days if states[d]["old"]]
        first_new = new_days[0] if new_days else None
        last_old = old_days[-1] if old_days else None
        rec["rpki"] = {
            "first_new_day_in_window": first_new,
            "new_preauthorized_at_window_start": bool(days and states[days[0]]["new"]),
            "old_authorized_at_window_end": bool(days and states[days[-1]]["old"]),
            "last_old_day_in_window": last_old,
            "days_observed": len(days),
        }
        t = parse_ts(rec.get("bgp", {}).get("new_50")) or parse_ts(rec.get("bgp", {}).get("first_new"))
        if t and days:
            prev = (t.date() - timedelta(days=1)).isoformat()
            same = t.date().isoformat()
            rec["rpki"]["new_valid_prev_day"] = states.get(prev, {}).get("new")
            rec["rpki"]["new_valid_same_day"] = states.get(same, {}).get("new")
            if first_new:
                rec["rpki"]["new_auth_minus_bgp_days"] = (date.fromisoformat(first_new) - t.date()).days
        tz = parse_ts(rec.get("bgp", {}).get("old_zero"))
        if tz and days:
            nextd = (tz.date() + timedelta(days=1)).isoformat()
            rec["rpki"]["old_valid_next_day"] = states.get(nextd, {}).get("old")
            if last_old:
                rec["rpki"]["old_auth_tail_days_proxy"] = (date.fromisoformat(last_old) - tz.date()).days
                rec["rpki"]["old_tail_right_censored"] = (last_old == days[-1])

    class_counts = defaultdict(int)
    leadlags = []
    tails = []
    for r in records:
        rp = r["rpki"]
        if rp.get("new_valid_prev_day") is True:
            class_counts["preauthorized_prev_day"] += 1
        elif rp.get("new_valid_same_day") is True:
            class_counts["same_day_only"] += 1
        elif rp.get("new_valid_same_day") is False:
            class_counts["not_authorized_same_day"] += 1
        else:
            class_counts["timing_unresolved"] += 1
        if rp.get("old_valid_next_day") is True:
            class_counts["old_still_authorized_next_day"] += 1
        if isinstance(rp.get("new_auth_minus_bgp_days"), int):
            leadlags.append(rp["new_auth_minus_bgp_days"])
        if isinstance(rp.get("old_auth_tail_days_proxy"), int):
            tails.append(rp["old_auth_tail_days_proxy"])

    summary = {
        "window": {"start": START_DT.isoformat(), "end": END_DT.isoformat()},
        "source": {"rrc": 0, "rib_start": RIB0, "rib_end": RIB1},
        "candidate_changes_total": len(changes),
        "candidate_changes_analyzed": len(records),
        "class_counts": dict(class_counts),
        "new_auth_minus_bgp_days_median": statistics.median(leadlags) if leadlags else None,
        "new_auth_minus_bgp_days_min": min(leadlags) if leadlags else None,
        "new_auth_minus_bgp_days_max": max(leadlags) if leadlags else None,
        "old_auth_tail_days_proxy_median": statistics.median(tails) if tails else None,
        "notes": [
            "Candidate population is exact IPv4 prefixes (/8..../24) with unanimous but different origins in two RRC00 RIB snapshots.",
            "BGP transition times replay RRC00 per-peer updates from the start RIB state.",
            "RPKI timing uses daily RIPE NCC historical validated-ROA snapshots; same-day ordering is intentionally not inferred.",
            "old_auth_tail_days_proxy is measured from collector old-origin extinction to the last daily authorization observed and can be right-censored.",
        ],
    }

    with open(os.path.join(OUTDIR, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    with open(os.path.join(OUTDIR, "records.json"), "w") as f:
        json.dump(records, f, indent=2, sort_keys=True)
    with open(os.path.join(OUTDIR, "daily.json"), "w") as f:
        json.dump(daily, f, sort_keys=True)
    with open(os.path.join(OUTDIR, "records.csv"), "w", newline="") as f:
        fields = ["prefix","old_asn","new_asn","rib_support","start_peers","end_peers","first_new","new_50","new_90","old_zero","first_new_day_in_window","new_valid_prev_day","new_valid_same_day","new_auth_minus_bgp_days","last_old_day_in_window","old_valid_next_day","old_auth_tail_days_proxy","old_tail_right_censored"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            row = {k:r.get(k) for k in fields}
            for k in ["first_new","new_50","new_90","old_zero"]:
                row[k] = r.get("bgp",{}).get(k)
            for k in ["first_new_day_in_window","new_valid_prev_day","new_valid_same_day","new_auth_minus_bgp_days","last_old_day_in_window","old_valid_next_day","old_auth_tail_days_proxy","old_tail_right_censored"]:
                row[k] = r.get("rpki",{}).get(k)
            w.writerow(row)
    print(json.dumps(summary, indent=2), flush=True)

if __name__ == "__main__":
    main()
