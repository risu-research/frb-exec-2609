import csv, json, re, statistics, zipfile
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("runs/j-7f2a/out")
OUT.mkdir(parents=True, exist_ok=True)
ZIP = Path("/tmp/source.zip")

STATE_WANTED = ["Gemma","a0","a1","b0","b1","c0","c1","B_1","B_2",
                "YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]

def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())
def choose(cols, names):
    d = defaultdict(list)
    for c in cols: d[norm(c)].append(c)
    for n in names:
        cs=d.get(norm(n),[])
        if len(cs)==1: return cs[0]
        exact=next((c for c in cs if c==n),None)
        if exact: return exact
    return None
def val(x):
    if x is None: return None
    s=str(x).strip()
    if s=="": return None
    try:
        y=float(s); return int(y) if y.is_integer() else y
    except: return s
def sk(x):
    y=val(x)
    return (0,float(y)) if isinstance(y,(int,float)) else (1,str(y))
def tskey(x):
    if x is None or str(x).strip()=="": return float("inf")
    s=str(x).strip().replace("Z","+00:00")
    try:
        d=datetime.fromisoformat(s)
        if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except:
        return s
def bn(s):
    m=re.search(r"batch\s*0*([0-9]+)",s,re.I); return int(m.group(1)) if m else None
def rcsv(z,m):
    txt=z.read(m).decode("utf-8-sig","replace"); sm=txt[:8192]
    try: delim=csv.Sniffer().sniff(sm,delimiters=",;\t|").delimiter
    except: delim=";" if sm.count(";")>sm.count(",") else ","
    r=csv.DictReader(txt.splitlines(),delimiter=delim)
    return r.fieldnames or [], list(r)
def state(row, cols): return tuple(val(row.get(c)) for c in cols)
def delta(a,b,cols):
    return {c:val(b.get(c)) for c in cols if val(a.get(c))!=val(b.get(c))}
def apply(s,d,idx):
    x=list(s)
    for c,v in d.items(): x[idx[c]]=v
    return tuple(x)
def jdump(x): return json.dumps(x,sort_keys=True,separators=(",",":"))

POLICIES = [
    "arrival_only",
    "timestamp_only",
    "timestamp_event_seq",
    "event_seq_only",
    "scan_id_only",
    "scan_id_event_order",
]

def order_events(events, policy):
    # Python sort is stable: when retained metadata ties, arrival order is retained.
    if policy=="arrival_only":
        return list(events)
    if policy=="timestamp_only":
        return sorted(events,key=lambda e:tskey(e["ts"]))
    if policy=="timestamp_event_seq":
        return sorted(events,key=lambda e:(tskey(e["ts"]),sk(e["event_seq"])))
    if policy=="event_seq_only":
        return sorted(events,key=lambda e:sk(e["event_seq"]))
    if policy=="scan_id_only":
        return sorted(events,key=lambda e:sk(e["scan_id"]))
    if policy=="scan_id_event_order":
        return sorted(events,key=lambda e:(sk(e["scan_id"]),sk(e["event_order"]),sk(e["event_seq"])))
    raise ValueError(policy)

with zipfile.ZipFile(ZIP) as z:
    csvs=sorted([x.filename for x in z.infolist() if x.filename.lower().endswith(".csv") and bn(x.filename)],
                key=lambda x:bn(x))
    pair_rows=[]
    seq_audit=[]
    part_records={}
    total_rows=0

    for member in csvs:
        b=bn(member); cols,rows=rcsv(z,member); total_rows += len(rows)
        part=choose(cols,["part_id"]); scan=choose(cols,["scan_id"]); order=choose(cols,["event_order"])
        evseq=choose(cols,["event_seq"]); evid=choose(cols,["event_id"]); ts=choose(cols,["ts_plc"])
        lut={c:c for c in cols}
        state_cols=[]
        bynorm=defaultdict(list)
        for c in cols: bynorm[norm(c)].append(c)
        for w in STATE_WANTED:
            exact=next((c for c in cols if c==w),None)
            if exact: state_cols.append(exact)
            else:
                cs=bynorm.get(norm(w),[])
                if len(cs)==1: state_cols.append(cs[0])
        assert part and scan and order and evseq and ts and len(state_cols)>=15, (b,part,scan,order,evseq,ts,state_cols)
        idx={c:i for i,c in enumerate(state_cols)}
        by=defaultdict(list)
        for r in rows: by[str(r.get(part))].append(r)

        for p,rr in by.items():
            rr.sort(key=lambda r:(sk(r.get(scan)),sk(r.get(order)),sk(r.get(evseq))))
            canon=[state(r,state_cols) for r in rr]
            cset=set(canon)
            events=[]
            for i in range(1,len(rr)):
                events.append({
                    "canon_index":i,
                    "delta":delta(rr[i-1],rr[i],state_cols),
                    "ts":rr[i].get(ts),
                    "event_seq":rr[i].get(evseq),
                    "event_id":rr[i].get(evid) if evid else None,
                    "scan_id":rr[i].get(scan),
                    "event_order":rr[i].get(order),
                })

            # sequence integrity audit
            seqvals=[val(r.get(evseq)) for r in rr]
            numeric=[x for x in seqvals if isinstance(x,(int,float))]
            mono=all(sk(seqvals[i]) < sk(seqvals[i+1]) for i in range(len(seqvals)-1))
            unique=len(set(map(str,seqvals)))==len(seqvals)
            seq_audit.append({"batch":b,"part_id":p,"rows":len(rr),"event_seq_strictly_increasing":int(mono),
                              "event_seq_unique_within_part":int(unique),
                              "min_event_seq":min(numeric) if numeric else None,
                              "max_event_seq":max(numeric) if numeric else None})

            meaningful=[]
            for i in range(1,len(rr)-1):
                if str(rr[i].get(scan)) != str(rr[i+1].get(scan)): continue
                A=events[i-1]["delta"]; B=events[i]["delta"]
                if not A or not B: continue
                pre=canon[i-1]
                s1=apply(pre,B,idx); s2=apply(s1,A,idx)
                transient=(s1 not in cset) or (s2 not in cset)
                local_persistent=(s2 != canon[i+1])
                meaningful.append((i,transient,local_persistent,s1,s2,A,B))

            part_records[(b,p)]={"rr":rr,"canon":canon,"cset":cset,"events":events,"idx":idx,
                                 "state_cols":state_cols,"meaningful":meaningful,
                                 "cols":{"part":part,"scan":scan,"order":order,"evseq":evseq,"evid":evid,"ts":ts}}

            for i,transient,persistent,s1,s2,A,B in meaningful:
                rA,rB=rr[i],rr[i+1]
                pair_id=f"b{b:02d}-p{p}-s{rA.get(scan)}-o{rA.get(order)}_{rB.get(order)}"
                pair_rows.append({
                    "pair_id":pair_id,"batch":b,"part_id":p,"scan_id":rA.get(scan),
                    "A_event_seq":rA.get(evseq),"B_event_seq":rB.get(evseq),
                    "A_event_id":rA.get(evid) if evid else None,"B_event_id":rB.get(evid) if evid else None,
                    "A_event_order":rA.get(order),"B_event_order":rB.get(order),
                    "A_ts":rA.get(ts),"B_ts":rB.get(ts),
                    "timestamp_tied":int(tskey(rA.get(ts))==tskey(rB.get(ts))),
                    "delta_A":jdump(A),"delta_B":jdump(B),
                    "original_transient":int(transient),"original_local_persistent":int(persistent),
                    "canon_i":i
                })

    assert total_rows==8810, total_rows

    # Evaluate each meaningful pair independently over its entire part trace.
    matrix=[]
    for base in pair_rows:
        key=(base["batch"],str(base["part_id"]))
        pr=part_records[key]; events=pr["events"]; canon=pr["canon"]; cset=pr["cset"]; idx=pr["idx"]
        i=int(base["canon_i"])
        # events list index i-1 corresponds row i (A), i corresponds row i+1 (B)
        corrupted=list(events)
        corrupted[i-1],corrupted[i]=corrupted[i],corrupted[i-1]
        aid=i; bid=i+1  # canon_index identifiers
        for pol in POLICIES:
            ordered=order_events(corrupted,pol)
            pos={e["canon_index"]:k for k,e in enumerate(ordered)}
            s=canon[0]
            offcanon=0
            states_after={}
            first_second_interval_off=0
            firstpos=min(pos[aid],pos[bid]); secondpos=max(pos[aid],pos[bid])
            for k,e in enumerate(ordered):
                s=apply(s,e["delta"],idx)
                states_after[e["canon_index"]]=s
                if s not in cset: offcanon += 1
                if firstpos <= k < secondpos and s not in cset: first_second_interval_off += 1
            # state after both pair events means materialized state at later of their two positions
            s2=canon[0]
            state_after_both=None
            for k,e in enumerate(ordered):
                s2=apply(s2,e["delta"],idx)
                if k==secondpos:
                    state_after_both=s2
                    break
            order_correct=int(pos[aid] < pos[bid])
            transient_survives=int(bool(base["original_transient"]) and first_second_interval_off>0)
            persistent_survives=int(bool(base["original_local_persistent"]) and state_after_both!=canon[i+1])
            matrix.append({**{k:v for k,v in base.items() if k!="canon_i"},
                           "policy":pol,"A_position":pos[aid],"B_position":pos[bid],
                           "pair_order_correct":order_correct,
                           "offcanonical_states_entire_part":offcanon,
                           "offcanonical_states_between_pair_events":first_second_interval_off,
                           "transient_survives":transient_survives,
                           "persistent_survives":persistent_survives,
                           "known_corruption_survives":int(transient_survives or persistent_survives)})

    # Main summary over the known 32 transient + 2 additional persistent mechanisms.
    summary=[]
    for pol in POLICIES:
        mm=[r for r in matrix if r["policy"]==pol]
        known=[r for r in mm if r["original_transient"] or r["original_local_persistent"]]
        trans=[r for r in mm if r["original_transient"]]
        persist_only=[r for r in mm if r["original_local_persistent"] and not r["original_transient"]]
        summary.append({
            "policy":pol,
            "meaningful_pairs":len(mm),
            "known_corrupting_pairs":len(known),
            "original_transient_pairs":len(trans),
            "original_persistent_only_pairs":len(persist_only),
            "transient_surviving":sum(r["transient_survives"] for r in trans),
            "transient_repaired":len(trans)-sum(r["transient_survives"] for r in trans),
            "persistent_only_surviving":sum(r["persistent_survives"] for r in persist_only),
            "persistent_only_repaired":len(persist_only)-sum(r["persistent_survives"] for r in persist_only),
            "known_corruptions_surviving":sum(r["known_corruption_survives"] for r in known),
            "known_corruptions_repaired":len(known)-sum(r["known_corruption_survives"] for r in known),
            "pair_order_correct_all_meaningful":sum(r["pair_order_correct"] for r in mm),
        })

    # Global stress stream: swap all non-overlapping meaningful adjacent pairs simultaneously per part.
    global_rows=[]
    overlap_conflicts=0
    swaps_used=0
    for (b,p),pr in part_records.items():
        events=pr["events"]; canon=pr["canon"]; cset=pr["cset"]; idx=pr["idx"]
        pair_indices=[x[0] for x in pr["meaningful"]]
        used=set(); selected=[]
        for i in pair_indices:
            ei={i-1,i} # indices into events
            if used & ei:
                overlap_conflicts += 1
                continue
            selected.append(i); used |= ei
        swaps_used += len(selected)
        corrupted=list(events)
        for i in selected:
            corrupted[i-1],corrupted[i]=corrupted[i],corrupted[i-1]
        for pol in POLICIES:
            ordered=order_events(corrupted,pol)
            s=canon[0]; off=0; first_off=None; last_off=None
            for k,e in enumerate(ordered):
                s=apply(s,e["delta"],idx)
                if s not in cset:
                    off += 1
                    if first_off is None: first_off=k
                    last_off=k
            global_rows.append({"batch":b,"part_id":p,"policy":pol,
                                "canonical_rows":len(canon),"injected_swaps":len(selected),
                                "offcanonical_materialized_states":off,
                                "final_state_differs":int(s!=canon[-1]),
                                "first_offcanonical_position":first_off,
                                "last_offcanonical_position":last_off})

    # Save.
    def writecsv(path,rows):
        with open(path,"w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    writecsv(OUT/"metadata_ablation_pair_matrix.csv",matrix)
    writecsv(OUT/"metadata_ablation_policy_summary.csv",summary)
    writecsv(OUT/"event_seq_audit.csv",seq_audit)
    writecsv(OUT/"global_materialization_by_part.csv",global_rows)

    seq_bad=sum(1 for r in seq_audit if not r["event_seq_strictly_increasing"] or not r["event_seq_unique_within_part"])
    known_count=sum(1 for r in pair_rows if r["original_transient"] or r["original_local_persistent"])
    transient_count=sum(r["original_transient"] for r in pair_rows)
    persist_only_count=sum(1 for r in pair_rows if r["original_local_persistent"] and not r["original_transient"])
    persistent_any=sum(r["original_local_persistent"] for r in pair_rows)
    tied_known=sum(1 for r in pair_rows if (r["original_transient"] or r["original_local_persistent"]) and r["timestamp_tied"])

    glob=[]
    for pol in POLICIES:
        gg=[r for r in global_rows if r["policy"]==pol]
        glob.append({"policy":pol,
                     "offcanonical_materialized_states":sum(r["offcanonical_materialized_states"] for r in gg),
                     "parts_with_any_offcanonical":sum(r["offcanonical_materialized_states"]>0 for r in gg),
                     "parts_with_final_mismatch":sum(r["final_state_differs"] for r in gg)})
    writecsv(OUT/"global_materialization_policy_summary.csv",glob)

    result={
        "total_dataset_rows":total_rows,
        "parts":len(part_records),
        "meaningful_pairs":len(pair_rows),
        "known_corrupting_pairs":known_count,
        "original_transient_pairs":transient_count,
        "original_persistent_pairs_any_overlap_with_transient":persistent_any,
        "original_persistent_only_pairs":persist_only_count,
        "known_corrupting_pairs_with_tied_plc_timestamp":tied_known,
        "event_seq_part_audits":len(seq_audit),
        "event_seq_bad_parts":seq_bad,
        "global_simultaneous_swaps_used":swaps_used,
        "global_overlap_conflicts_skipped":overlap_conflicts,
        "policy_summary":summary,
        "global_summary":glob,
        "definitions":{
            "arrival_only":"consume controlled swapped arrival order as delivered",
            "timestamp_only":"stable sort by ts_plc; ties retain arrival order",
            "timestamp_event_seq":"sort by ts_plc then monotonic event_seq",
            "event_seq_only":"sort by monotonic event_seq (diagnostic extra policy)",
            "scan_id_only":"stable sort by scan_id; events within the same scan retain arrival order",
            "scan_id_event_order":"sort by scan_id, event_order, then event_seq",
        }
    }
    (OUT/"metadata_ablation_summary.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    lines=["# Metadata ablation\n",f"- dataset rows: {total_rows}\n",f"- parts: {len(part_records)}\n",
           f"- meaningful same-scan state-changing pairs: {len(pair_rows)}\n",
           f"- known corrupting pairs: {known_count} ({transient_count} transient + {persist_only_count} persistent-only)\n",
           f"- event_seq bad part traces: {seq_bad}/{len(seq_audit)}\n",
           f"- simultaneous stress swaps: {swaps_used}; overlap conflicts skipped: {overlap_conflicts}\n\n",
           "| policy | transient survives | persistent-only survives | total known survives | repaired |\n",
           "|---|---:|---:|---:|---:|\n"]
    for s in summary:
        lines.append(f"| {s['policy']} | {s['transient_surviving']}/{s['original_transient_pairs']} | "
                     f"{s['persistent_only_surviving']}/{s['original_persistent_only_pairs']} | "
                     f"{s['known_corruptions_surviving']}/{s['known_corrupting_pairs']} | {s['known_corruptions_repaired']} |\n")
    lines += ["\n## Global simultaneous-swap materialization\n",
              "| policy | off-canonical materialized states | parts affected | final-mismatch parts |\n",
              "|---|---:|---:|---:|\n"]
    for g in glob:
        lines.append(f"| {g['policy']} | {g['offcanonical_materialized_states']} | {g['parts_with_any_offcanonical']} | {g['parts_with_final_mismatch']} |\n")
    (OUT/"metadata_ablation_report.md").write_text("".join(lines),encoding="utf-8")
    print(json.dumps(result,indent=2))
