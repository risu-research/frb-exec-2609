import csv, hashlib, io, json, os, re, sys, urllib.request, zipfile
from collections import Counter, defaultdict
from pathlib import Path

JOB = "j-7f2a"
OUT = Path("runs") / JOB / "out"
OUT.mkdir(parents=True, exist_ok=True)
ZIP_PATH = Path("/tmp/source.zip")
URLS = [
    "https://ss3.scayle.es/riubu-1/GICAP/2026_Martin_DAYPSCI_v1.zip",
    "https://riubu.ubu.es/bitstream/handle/10259/11686/2026_Martin_DAYPSCI_v1.zip?sequence=6&isAllowed=y",
]

def download():
    errors = []
    for url in URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research-repro/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r, open(ZIP_PATH, "wb") as f:
                total = 0
                while True:
                    b = r.read(8 * 1024 * 1024)
                    if not b:
                        break
                    f.write(b)
                    total += len(b)
            if ZIP_PATH.stat().st_size > 100_000_000:
                return url
            errors.append(f"{url}: suspicious size {ZIP_PATH.stat().st_size}")
        except Exception as e:
            errors.append(f"{url}: {type(e).__name__}: {e}")
    raise RuntimeError("download failed: " + " | ".join(errors))

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())

def choose_col(cols, wanted):
    lut = {norm(c): c for c in cols}
    for w in wanted:
        if norm(w) in lut:
            return lut[norm(w)]
    return None

def to_num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        x = float(s)
        return int(x) if x.is_integer() else x
    except Exception:
        return s

def state_val(v):
    x = to_num(v)
    return x

def read_csv_from_zip(zf, member):
    raw = zf.read(member)
    # UTF-8 first, then latin-1 fallback.
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = txt[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t|")
        delim = dialect.delimiter
    except Exception:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    rdr = csv.DictReader(io.StringIO(txt), delimiter=delim)
    rows = list(rdr)
    return rdr.fieldnames or [], rows

def batch_no(name):
    m = re.search(r"batch\s*0*([0-9]+)", name, re.I)
    return int(m.group(1)) if m else None

def safe_sort_key(v):
    x = to_num(v)
    if isinstance(x, (int, float)):
        return (0, float(x))
    return (1, "" if x is None else str(x))

def tuple_state(row, state_cols):
    return tuple(state_val(row.get(c)) for c in state_cols)

def apply_delta(state, delta, idx):
    x = list(state)
    for k, v in delta.items():
        x[idx[k]] = v
    return tuple(x)

def delta_between(a, b, state_cols):
    d = {}
    for c in state_cols:
        av, bv = state_val(a.get(c)), state_val(b.get(c))
        if av != bv:
            d[c] = bv
    return d

def dist_json(vals):
    c = Counter(str(to_num(v)) for v in vals)
    return json.dumps(dict(sorted(c.items())), sort_keys=True)

source_url = download()
zip_sha = sha256_file(ZIP_PATH)
zip_size = ZIP_PATH.stat().st_size

with zipfile.ZipFile(ZIP_PATH) as zf:
    infos = zf.infolist()
    members = [i.filename for i in infos]
    csv_members = [n for n in members if n.lower().endswith(".csv") and batch_no(n) is not None]
    csv_members.sort(key=lambda n: (batch_no(n), n))
    md_members = [n for n in members if n.lower().endswith((".md", ".txt"))]
    pcap_members = [n for n in members if n.lower().endswith((".pcapng", ".pcap"))]

    manifest = {
        "job": JOB,
        "source_url_used": source_url,
        "source_urls_attempted": URLS,
        "zip_bytes": zip_size,
        "zip_sha256": zip_sha,
        "archive_entries": len(infos),
        "csv_entries": len(csv_members),
        "pcap_entries": len(pcap_members),
        "text_entries": len(md_members),
        "csv_members": csv_members,
        "pcap_members": pcap_members,
        "text_members": md_members,
    }
    (OUT / "archive_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Preserve small experiment descriptions for auditability.
    desc_chunks = []
    for n in md_members:
        try:
            b = zf.read(n)
            if len(b) <= 500_000:
                txt = b.decode("utf-8", "replace")
                desc_chunks.append(f"\n===== {n} =====\n{txt}\n")
        except Exception as e:
            desc_chunks.append(f"\n===== {n} =====\n[read error: {e}]\n")
    (OUT / "descriptions.txt").write_text("".join(desc_chunks), encoding="utf-8")

    population_rows = []
    cache = {}

    for member in csv_members:
        cols, rows = read_csv_from_zip(zf, member)
        bno = batch_no(member)
        cache[bno] = (member, cols, rows)

        part = choose_col(cols, ["part_id", "partid"])
        scan = choose_col(cols, ["scan_id", "scanid"])
        order = choose_col(cols, ["event_order", "eventorder"])
        evseq = choose_col(cols, ["event_seq", "eventseq"])
        evid = choose_col(cols, ["event_id", "eventid"])
        dt = choose_col(cols, ["delta_time_ms", "deltatimems"])
        anomaly = choose_col(cols, ["anomaly"])
        fault = choose_col(cols, ["fault"])
        gemma = choose_col(cols, ["gemma"])
        exp = choose_col(cols, ["experiment_id", "experimentid"])
        batchc = choose_col(cols, ["batch_id", "batchid"])

        parts = set(str(r.get(part)) for r in rows) if part else set()
        scans = set((str(r.get(part)) if part else "", str(r.get(scan))) for r in rows) if scan else set()
        scan_counts = Counter((str(r.get(part)) if part else "", str(r.get(scan))) for r in rows) if scan else Counter()
        multi_scans = sum(1 for _, v in scan_counts.items() if v > 1)
        multi_rows = sum(v for v in scan_counts.values() if v > 1)
        zero_dt = sum(1 for r in rows if dt and to_num(r.get(dt)) == 0)
        event_ids = set(str(r.get(evid)) for r in rows) if evid else set()

        # Check current file row order against explicit canonical keys, within part.
        inversions = 0
        if part and scan and order:
            prev = {}
            for r in rows:
                p = str(r.get(part))
                k = (safe_sort_key(r.get(scan)), safe_sort_key(r.get(order)), safe_sort_key(r.get(evseq)) if evseq else (0,0))
                if p in prev and k < prev[p]:
                    inversions += 1
                prev[p] = k

        population_rows.append({
            "batch": bno,
            "member": member,
            "rows_events": len(rows),
            "parts": len(parts),
            "part_scan_pairs": len(scans),
            "multi_event_scans": multi_scans,
            "rows_in_multi_event_scans": multi_rows,
            "zero_delta_rows": zero_dt,
            "distinct_event_ids": len(event_ids),
            "max_event_order": max([to_num(r.get(order)) for r in rows if order and isinstance(to_num(r.get(order)), (int,float))] or [None]),
            "anomaly_distribution": dist_json([r.get(anomaly) for r in rows]) if anomaly else "{}",
            "fault_distribution": dist_json([r.get(fault) for r in rows]) if fault else "{}",
            "gemma_distribution": dist_json([r.get(gemma) for r in rows]) if gemma else "{}",
            "experiment_ids": dist_json([r.get(exp) for r in rows]) if exp else "{}",
            "batch_ids": dist_json([r.get(batchc) for r in rows]) if batchc else "{}",
            "canonical_order_inversions_in_file": inversions,
        })

    with open(OUT / "population.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(population_rows[0].keys()))
        w.writeheader(); w.writerows(population_rows)

    # Pilot: baseline, first sensor, first valve.
    selected = [b for b in (1, 2, 8) if b in cache]
    pilot_summary = {
        "job": JOB,
        "selected_batches": selected,
        "definition": {
            "canonical_order": "within part_id: scan_id, event_order, event_seq",
            "message_model": "state-field deltas derived from consecutive canonical full-state rows",
            "perturbation": "single adjacent inversion of consecutive events inside the same scan_id",
            "primary_endpoint": "intermediate/final materialized state absent from canonical states observed in the same part; batch-level absence also reported",
            "note": "absence from a finite trace is reported as trace-inconsistent, not by itself a proof of physical impossibility",
        },
        "batches": {}
    }
    ex_rows = []
    changed_count_rows = []

    for bno in selected:
        member, cols, rows = cache[bno]
        part = choose_col(cols, ["part_id"])
        scan = choose_col(cols, ["scan_id"])
        order = choose_col(cols, ["event_order"])
        evseq = choose_col(cols, ["event_seq"])
        dt = choose_col(cols, ["delta_time_ms"])
        gemma = choose_col(cols, ["gemma"])

        desired = ["gemma","a0","a1","b0","b1","c0","c1","B_1","B_2","YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]
        # exact-normalized lookup while retaining all distinct names
        lut = {norm(c): c for c in cols}
        state_cols = []
        for d in desired:
            c = lut.get(norm(d))
            if c and c not in state_cols:
                state_cols.append(c)
        if len(state_cols) < 8:
            # fallback: actuator/internal state-looking fields only
            candidates = []
            for c in cols:
                if re.fullmatch(r"(gemma|[abc][01]|b_[12]|y[abc]_[pm])", c, re.I):
                    candidates.append(c)
            state_cols = list(dict.fromkeys(candidates))

        if not (part and scan and order and len(state_cols) >= 2):
            pilot_summary["batches"][str(bno)] = {"error":"missing required columns","columns":cols,"state_cols":state_cols}
            continue

        by_part = defaultdict(list)
        for r in rows:
            by_part[str(r.get(part))].append(r)

        # Batch canonical state set, for stricter/generalized check.
        batch_states = set()
        for p, rr in by_part.items():
            rr.sort(key=lambda r: (safe_sort_key(r.get(scan)), safe_sort_key(r.get(order)), safe_sort_key(r.get(evseq)) if evseq else (0,0)))
            for r in rr:
                batch_states.add(tuple_state(r, state_cols))

        n_events_after_first = 0
        n_zero_change = 0
        change_hist = Counter()
        eligible_pairs = 0
        s1_part_bad = s2_part_bad = 0
        s1_batch_bad = s2_batch_bad = 0
        any_part_bad = any_batch_bad = 0
        final_divergent = 0
        overlapping_delta_pairs = 0
        pair_both_nonempty = 0
        opposed_command_conflicts = 0
        vulnerable_scans = set()
        all_eligible_scans = set()

        idx = {c:i for i,c in enumerate(state_cols)}
        # identify opposed command pairs if present
        opp_pairs = []
        for prefix in ("YA","YB","YC"):
            cp = next((c for c in state_cols if norm(c)==norm(prefix+"_p")), None)
            cm = next((c for c in state_cols if norm(c)==norm(prefix+"_m")), None)
            if cp and cm:
                opp_pairs.append((cp,cm))

        for p, rr in by_part.items():
            rr.sort(key=lambda r: (safe_sort_key(r.get(scan)), safe_sort_key(r.get(order)), safe_sort_key(r.get(evseq)) if evseq else (0,0)))
            canon = [tuple_state(r, state_cols) for r in rr]
            part_states = set(canon)

            deltas = [None]
            for i in range(1, len(rr)):
                d = delta_between(rr[i-1], rr[i], state_cols)
                deltas.append(d)
                n_events_after_first += 1
                change_hist[len(d)] += 1
                if len(d)==0: n_zero_change += 1

            for i in range(1, len(rr)-1):
                # A=event i, B=event i+1; pre is row i-1.
                if str(rr[i].get(scan)) != str(rr[i+1].get(scan)):
                    continue
                A, B = deltas[i], deltas[i+1]
                if A is None or B is None:
                    continue
                eligible_pairs += 1
                skey = (p, str(rr[i].get(scan)))
                all_eligible_scans.add(skey)
                if A and B:
                    pair_both_nonempty += 1
                if set(A).intersection(B):
                    overlapping_delta_pairs += 1

                pre = canon[i-1]
                s1 = apply_delta(pre, B, idx)
                s2 = apply_delta(s1, A, idx)
                p1 = s1 not in part_states
                p2 = s2 not in part_states
                b1 = s1 not in batch_states
                b2 = s2 not in batch_states
                if p1: s1_part_bad += 1
                if p2: s2_part_bad += 1
                if b1: s1_batch_bad += 1
                if b2: s2_batch_bad += 1
                if p1 or p2:
                    any_part_bad += 1
                    vulnerable_scans.add(skey)
                if b1 or b2: any_batch_bad += 1
                if s2 != canon[i+1]: final_divergent += 1

                conflict = False
                for cp, cm in opp_pairs:
                    if state_val(s1[idx[cp]]) == 1 and state_val(s1[idx[cm]]) == 1:
                        conflict = True
                    if state_val(s2[idx[cp]]) == 1 and state_val(s2[idx[cm]]) == 1:
                        conflict = True
                if conflict:
                    opposed_command_conflicts += 1

                if (p1 or p2 or b1 or b2 or s2 != canon[i+1]) and len(ex_rows) < 300:
                    ex_rows.append({
                        "batch": bno, "part_id": p, "scan_id": rr[i].get(scan),
                        "event_order_A": rr[i].get(order), "event_order_B": rr[i+1].get(order),
                        "delta_A": json.dumps(A, sort_keys=True),
                        "delta_B": json.dumps(B, sort_keys=True),
                        "s1_absent_part": int(p1), "s2_absent_part": int(p2),
                        "s1_absent_batch": int(b1), "s2_absent_batch": int(b2),
                        "final_divergent": int(s2 != canon[i+1]),
                        "canonical_A": json.dumps(canon[i]),
                        "canonical_B": json.dumps(canon[i+1]),
                        "swapped_after_B": json.dumps(s1),
                        "swapped_after_A": json.dumps(s2),
                    })

        for k,v in sorted(change_hist.items()):
            changed_count_rows.append({"batch":bno,"changed_state_fields":k,"events":v})

        def rate(n,d): return (n/d) if d else None
        pilot_summary["batches"][str(bno)] = {
            "member": member,
            "rows": len(rows),
            "parts": len(by_part),
            "state_columns": state_cols,
            "canonical_unique_states_batch": len(batch_states),
            "events_after_initial": n_events_after_first,
            "zero_state_change_events": n_zero_change,
            "state_change_field_count_distribution": dict(sorted(change_hist.items())),
            "eligible_within_scan_adjacent_pairs": eligible_pairs,
            "pairs_with_both_nonempty_deltas": pair_both_nonempty,
            "pairs_with_overlapping_delta_fields": overlapping_delta_pairs,
            "trace_inconsistent_after_first_swapped_message_part": s1_part_bad,
            "trace_inconsistent_after_second_swapped_message_part": s2_part_bad,
            "pairs_any_trace_inconsistent_part": any_part_bad,
            "pair_vulnerability_rate_part": rate(any_part_bad, eligible_pairs),
            "trace_inconsistent_after_first_swapped_message_batch": s1_batch_bad,
            "trace_inconsistent_after_second_swapped_message_batch": s2_batch_bad,
            "pairs_any_trace_inconsistent_batch": any_batch_bad,
            "pair_vulnerability_rate_batch": rate(any_batch_bad, eligible_pairs),
            "final_state_divergent_from_canonical_after_both": final_divergent,
            "final_divergence_rate": rate(final_divergent, eligible_pairs),
            "eligible_multi_event_scans": len(all_eligible_scans),
            "vulnerable_scans_part_reference": len(vulnerable_scans),
            "vulnerable_scan_rate_part_reference": rate(len(vulnerable_scans), len(all_eligible_scans)),
            "opposed_solenoid_command_conflict_pairs": opposed_command_conflicts,
        }

    (OUT / "pilot_summary.json").write_text(json.dumps(pilot_summary, indent=2), encoding="utf-8")

    if ex_rows:
        with open(OUT / "pair_examples.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(ex_rows[0].keys()))
            w.writeheader(); w.writerows(ex_rows)

    if changed_count_rows:
        with open(OUT / "change_histogram.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(changed_count_rows[0].keys()))
            w.writeheader(); w.writerows(changed_count_rows)

    report = []
    report.append(f"# {JOB}\n")
    report.append(f"source_zip_bytes: {zip_size}\n")
    report.append(f"source_zip_sha256: {zip_sha}\n")
    report.append(f"archive_csv_entries: {len(csv_members)}\n")
    report.append(f"selected_batches: {selected}\n\n")
    for b in selected:
        s = pilot_summary["batches"].get(str(b), {})
        report.append(f"## batch {b}\n")
        for k,v in s.items():
            if k not in ("member","state_columns","state_change_field_count_distribution"):
                report.append(f"- {k}: {v}\n")
        report.append(f"- state_columns: {s.get('state_columns')}\n")
        report.append(f"- change_hist: {s.get('state_change_field_count_distribution')}\n")
    (OUT / "report.md").write_text("".join(report), encoding="utf-8")

print(json.dumps({
    "status":"ok",
    "job":JOB,
    "zip_bytes":zip_size,
    "zip_sha256":zip_sha,
    "csv_count":len(csv_members),
    "selected":selected,
    "out":str(OUT)
}, indent=2))
