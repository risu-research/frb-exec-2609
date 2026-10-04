import csv, json, math, os, re, statistics, subprocess, tempfile, zipfile
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

JOB="j-7f2a"
OUT=Path("runs")/JOB/"out"
OUT.mkdir(parents=True, exist_ok=True)
ZIP=Path("/tmp/source.zip")

def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())
def choose(cols,names):
    lut={norm(c):c for c in cols}
    for n in names:
        if norm(n) in lut: return lut[norm(n)]
    return None
def num(v):
    if v is None: return None
    s=str(v).strip()
    if not s: return None
    try:
        x=float(s); return int(x) if x.is_integer() else x
    except: return s
def sortkey(v):
    x=num(v)
    return (0,float(x)) if isinstance(x,(int,float)) else (1,str(x))
def batchno(name):
    m=re.search(r"batch\s*0*([0-9]+)",name,re.I)
    return int(m.group(1)) if m else None
def read_csv(zf,member):
    raw=zf.read(member)
    txt=None
    for enc in ("utf-8-sig","utf-8","latin-1"):
        try: txt=raw.decode(enc); break
        except UnicodeDecodeError: pass
    sample=txt[:8192]
    try: delim=csv.Sniffer().sniff(sample,delimiters=",;\t|").delimiter
    except: delim=";" if sample.count(";")>sample.count(",") else ","
    r=csv.DictReader(txt.splitlines(),delimiter=delim)
    return r.fieldnames or [], list(r)
def parse_ts(v):
    if v is None: return None
    s=str(v).strip()
    if not s: return None
    # common SQL/ISO variants
    s=s.replace("Z","+00:00")
    try:
        dt=datetime.fromisoformat(s)
    except:
        fmts=["%Y-%m-%d %H:%M:%S.%f","%Y-%m-%d %H:%M:%S","%d/%m/%Y %H:%M:%S.%f","%d/%m/%Y %H:%M:%S"]
        dt=None
        for f in fmts:
            try: dt=datetime.strptime(s,f); break
            except: pass
        if dt is None: return None
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()
def state(row,cols): return tuple(num(row.get(c)) for c in cols)
def delta(a,b,cols):
    d={}
    for c in cols:
        av,bv=num(a.get(c)),num(b.get(c))
        if av!=bv: d[c]=bv
    return d
def apply(st,d,idx):
    x=list(st)
    for k,v in d.items(): x[idx[k]]=v
    return tuple(x)
def pct(vals,q):
    if not vals: return None
    s=sorted(vals)
    if len(s)==1: return s[0]
    pos=(len(s)-1)*q
    lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    if lo==hi: return s[lo]
    return s[lo]*(hi-pos)+s[hi]*(pos-lo)
def nearest(times,t):
    if not times or t is None: return None
    i=bisect_left(times,t)
    cand=[]
    if i<len(times): cand.append(times[i])
    if i: cand.append(times[i-1])
    return min(cand,key=lambda x:abs(x-t)) if cand else None

with zipfile.ZipFile(ZIP) as zf:
    members=[i.filename for i in zf.infolist()]
    csvs=sorted([m for m in members if m.lower().endswith(".csv") and batchno(m)], key=lambda m:batchno(m))
    pcaps={batchno(m):m for m in members if m.lower().endswith(".pcapng") and batchno(m)}

    all_pairs=[]
    invariant_rows=[]
    invariant_summary={}
    csv_ranges={}
    pair_by_batch=defaultdict(list)

    desired=["gemma","a0","a1","b0","b1","c0","c1","B_1","B_2","YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]
    out_names=["YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]

    for member in csvs:
        b=batchno(member)
        cols,rows=read_csv(zf,member)
        part=choose(cols,["part_id"]); scan=choose(cols,["scan_id"]); order=choose(cols,["event_order"])
        evseq=choose(cols,["event_seq"]); evid=choose(cols,["event_id"]); tscol=choose(cols,["ts_plc"]); dtcol=choose(cols,["delta_time_ms"])
        # exact preferred
        scols=[]
        for d in desired:
            ex=next((c for c in cols if c==d),None)
            if ex: scols.append(ex)
            else:
                ms=[c for c in cols if norm(c)==norm(d)]
                if len(ms)==1: scols.append(ms[0])
        gem=next((c for c in scols if c=="gemma"),None)
        outs=[c for c in scols if c in out_names]
        idx={c:i for i,c in enumerate(scols)}
        byp=defaultdict(list)
        for r in rows: byp[str(r.get(part))].append(r)

        tsvals=[parse_ts(r.get(tscol)) for r in rows if tscol]
        tsvals=[x for x in tsvals if x is not None]
        csv_ranges[b]={"start":min(tsvals) if tsvals else None,"end":max(tsvals) if tsvals else None,
                       "start_raw":rows[0].get(tscol) if rows and tscol else None,
                       "end_raw":rows[-1].get(tscol) if rows and tscol else None}

        d2_rows=0; d2_rows_on=0; d2_entries=0; d2_entry_on=0
        entries_from_on=0; entries_cleared_before=0; entries_violate_clear_order=0; entries_already_zero=0

        for p,rr in byp.items():
            rr.sort(key=lambda r:(sortkey(r.get(scan)),sortkey(r.get(order)),sortkey(r.get(evseq)) if evseq else (0,0)))
            canon=[state(r,scols) for r in rr]
            partset=set(canon)
            ds=[None]+[delta(rr[i-1],rr[i],scols) for i in range(1,len(rr))]

            # canonical D2 rows and entries
            for i,r in enumerate(rr):
                st=canon[i]
                if gem and st[idx[gem]]==7:
                    d2_rows+=1
                    if any(st[idx[o]]==1 for o in outs): d2_rows_on+=1
                    prevg=canon[i-1][idx[gem]] if i>0 else None
                    if prevg!=7:
                        d2_entries+=1
                        if any(st[idx[o]]==1 for o in outs): d2_entry_on+=1
                        # state at start of this scan = previous row before first event of scan
                        sscan=str(r.get(scan))
                        j=i
                        while j>0 and str(rr[j-1].get(scan))==sscan:
                            j-=1
                        pre_scan = canon[j-1] if j>0 else canon[j]
                        on_before=[o for o in outs if pre_scan[idx[o]]==1]
                        cleared=[]
                        for k in range(j,i):
                            dd=ds[k] or {}
                            for o in on_before:
                                if dd.get(o)==0 and o not in cleared: cleared.append(o)
                        if on_before:
                            entries_from_on+=1
                            if set(cleared)==set(on_before): entries_cleared_before+=1
                            else: entries_violate_clear_order+=1
                        else:
                            entries_already_zero+=1
                        invariant_rows.append({
                            "batch":b,"part_id":p,"scan_id":r.get(scan),"event_order_d2":r.get(order),
                            "outputs_on_at_scan_start":";".join(on_before),
                            "outputs_cleared_before_d2":";".join(cleared),
                            "d2_entry_outputs_on":";".join(o for o in outs if st[idx[o]]==1),
                            "ts_d2":r.get(tscol) if tscol else "",
                        })

            # same-scan meaningful adjacent pairs
            for i in range(1,len(rr)-1):
                if str(rr[i].get(scan))!=str(rr[i+1].get(scan)): continue
                A,B=ds[i],ds[i+1]
                if not A or not B: continue
                pre=canon[i-1]
                s1=apply(pre,B,idx); s2=apply(s1,A,idx)
                pbad=(s1 not in partset) or (s2 not in partset)
                final=(s2!=canon[i+1])
                if not (pbad or final): continue
                ta=parse_ts(rr[i].get(tscol)) if tscol else None
                tb=parse_ts(rr[i+1].get(tscol)) if tscol else None
                rec={
                    "batch":b,"part_id":p,"scan_id":rr[i].get(scan),
                    "order_A":rr[i].get(order),"order_B":rr[i+1].get(order),
                    "event_id_A":rr[i].get(evid) if evid else "","event_id_B":rr[i+1].get(evid) if evid else "",
                    "ts_A":rr[i].get(tscol) if tscol else "","ts_B":rr[i+1].get(tscol) if tscol else "",
                    "ts_A_epoch":ta,"ts_B_epoch":tb,
                    "timestamp_separation_us":None if ta is None or tb is None else (tb-ta)*1e6,
                    "delta_time_A_ms":rr[i].get(dtcol) if dtcol else "","delta_time_B_ms":rr[i+1].get(dtcol) if dtcol else "",
                    "delta_A":json.dumps(A,sort_keys=True),"delta_B":json.dumps(B,sort_keys=True),
                    "trace_inconsistent":int(pbad),"final_divergent":int(final),
                    "gemma7_after_B":int(B.get(gem)==7 if gem else False),
                    "actuator_clear_A":int(any(k in outs and v==0 for k,v in A.items())),
                }
                all_pairs.append(rec); pair_by_batch[b].append(rec)

        invariant_summary[b]={
            "d2_rows":d2_rows,"d2_rows_with_output_command_on":d2_rows_on,
            "d2_entries":d2_entries,"d2_entries_with_output_command_on":d2_entry_on,
            "d2_entries_scan_started_with_output_on":entries_from_on,
            "d2_entries_all_prior_on_outputs_cleared_before_d2":entries_cleared_before,
            "d2_entries_clear_order_violations":entries_violate_clear_order,
            "d2_entries_scan_started_outputs_already_zero":entries_already_zero,
        }

    # write pair and invariant tables before PCAP enrichment
    if invariant_rows:
        with open(OUT/"invariant_transitions.csv","w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(invariant_rows[0].keys())); w.writeheader(); w.writerows(invariant_rows)

    stream_rows=[]
    pcap_batch_summary={}
    batch_stream_times={}

    for b,member in sorted(pcaps.items()):
        tmp=Path("/tmp")/f"b{b:02d}.pcapng"
        with zf.open(member) as src, open(tmp,"wb") as dst:
            while True:
                buf=src.read(8*1024*1024)
                if not buf: break
                dst.write(buf)

        cmd=["tshark","-n","-r",str(tmp),"-Y","pn_rt.cycle_counter",
             "-T","fields","-E","separator=\t","-E","occurrence=f",
             "-e","frame.number","-e","frame.time_epoch","-e","eth.src","-e","eth.dst",
             "-e","pn_rt.frame_id","-e","pn_rt.cycle_counter","-e","pn_rt.ds","-e","pn_rt.transfer_status"]
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        streams=defaultdict(lambda:{"times":[],"cycles":[],"frames":[],"ds":[],"ts":[]})
        total=0
        for line in p.stdout:
            vals=line.rstrip("\n").split("\t")
            vals += [""]*(9-len(vals))
            fr,t,src,dst,fid,cyc,ds,tr=vals[:8]
            if not (t and src and dst and fid and cyc): continue
            try:
                tt=float(t); cc=int(cyc,0); fi=int(fid,0)
            except: continue
            key=(src,dst,fi)
            streams[key]["times"].append(tt); streams[key]["cycles"].append(cc); streams[key]["frames"].append(int(fr))
            streams[key]["ds"].append(ds); streams[key]["ts"].append(tr)
            total+=1
        stderr=p.stderr.read(); rc=p.wait()

        all_times=sorted(t for s in streams.values() for t in s["times"])
        batch_stream_times[b]={k:sorted(v["times"]) for k,v in streams.items()}
        srange=csv_ranges.get(b,{})
        prange=(min(all_times),max(all_times)) if all_times else (None,None)
        overlap=False; start_offset=None; end_offset=None
        if prange[0] is not None and srange.get("start") is not None:
            start_offset=prange[0]-srange["start"]; end_offset=prange[1]-srange["end"]
            overlap=(max(prange[0],srange["start"]) <= min(prange[1],srange["end"]))
        pcap_batch_summary[b]={
            "pcap_member":member,"tshark_rc":rc,"tshark_stderr_tail":stderr[-1000:],
            "pnrt_cyclic_frames":total,"streams":len(streams),
            "pcap_start_epoch":prange[0],"pcap_end_epoch":prange[1],
            "csv_start_epoch":srange.get("start"),"csv_end_epoch":srange.get("end"),
            "pcap_minus_csv_start_s":start_offset,"pcap_minus_csv_end_s":end_offset,
            "ranges_overlap":overlap,
        }

        for (src,dst,fid),s in streams.items():
            times=s["times"]; cycles=s["cycles"]
            intervals=[(times[i]-times[i-1])*1000 for i in range(1,len(times))]
            diffs=[(cycles[i]-cycles[i-1]) & 0xFFFF for i in range(1,len(cycles))]
            nonzero=[d for d in diffs if d!=0 and d<32768]
            mode_step=Counter(nonzero).most_common(1)[0][0] if nonzero else None
            backwards=sum(1 for d in diffs if d>32768)
            duplicates=sum(1 for d in diffs if d==0)
            irregular=sum(1 for d in diffs if mode_step is not None and d not in (mode_step,0) and d<32768)
            stream_rows.append({
                "batch":b,"src":src,"dst":dst,"frame_id":fid,"frames":len(times),
                "first_epoch":times[0] if times else None,"last_epoch":times[-1] if times else None,
                "median_interarrival_ms":statistics.median(intervals) if intervals else None,
                "p01_interarrival_ms":pct(intervals,.01),"p99_interarrival_ms":pct(intervals,.99),
                "p999_interarrival_ms":pct(intervals,.999),"min_interarrival_ms":min(intervals) if intervals else None,
                "max_interarrival_ms":max(intervals) if intervals else None,
                "modal_cycle_counter_step":mode_step,
                "cycle_counter_backward_transitions":backwards,
                "cycle_counter_duplicate_transitions":duplicates,
                "cycle_counter_irregular_forward_transitions":irregular,
            })
        try: tmp.unlink()
        except: pass

    # enrich positive pairs with actual capture geometry
    for rec in all_pairs:
        b=rec["batch"]; ta=rec["ts_A_epoch"]; tb=rec["ts_B_epoch"]
        streams=batch_stream_times.get(b,{})
        rec["pcap_streams_in_batch"]=len(streams)
        rec["separate_cyclic_frames_strictly_between_A_B"]=0
        nearest_us=[]
        for key,times in streams.items():
            if ta is not None and tb is not None and tb>=ta:
                rec["separate_cyclic_frames_strictly_between_A_B"] += sum(1 for x in times if ta < x < tb)
            n=nearest(times,tb if tb is not None else ta)
            if n is not None and (tb is not None or ta is not None):
                ref=tb if tb is not None else ta
                nearest_us.append(abs(n-ref)*1e6)
        rec["nearest_cyclic_frame_abs_offset_us"]=min(nearest_us) if nearest_us else None

    if stream_rows:
        with open(OUT/"pcap_streams.csv","w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(stream_rows[0].keys())); w.writeheader(); w.writerows(stream_rows)
    if all_pairs:
        fields=list(all_pairs[0].keys())
        with open(OUT/"pair_timing_pcap.csv","w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(all_pairs)

    result={
        "invariant_summary":invariant_summary,
        "pcap_batch_summary":pcap_batch_summary,
        "positive_pairs":len(all_pairs),
        "positive_pairs_zero_timestamp_separation":sum(1 for r in all_pairs if r["timestamp_separation_us"]==0),
        "positive_pairs_with_nonzero_timestamp_separation":sum(1 for r in all_pairs if r["timestamp_separation_us"] not in (None,0)),
        "positive_pairs_with_network_frame_strictly_between":sum(1 for r in all_pairs if r["separate_cyclic_frames_strictly_between_A_B"]>0),
        "gemma7_actuator_clear_pairs":sum(1 for r in all_pairs if r["gemma7_after_B"] and r["actuator_clear_A"]),
        "stream_rows":len(stream_rows),
        "cycle_counter_backward_total":sum(r["cycle_counter_backward_transitions"] for r in stream_rows),
    }
    (OUT/"pcap_analysis.json").write_text(json.dumps(result,indent=2),encoding="utf-8")

    tot_d2=sum(x["d2_rows"] for x in invariant_summary.values())
    tot_d2_on=sum(x["d2_rows_with_output_command_on"] for x in invariant_summary.values())
    ent=sum(x["d2_entries"] for x in invariant_summary.values())
    ent_on=sum(x["d2_entries_with_output_command_on"] for x in invariant_summary.values())
    from_on=sum(x["d2_entries_scan_started_with_output_on"] for x in invariant_summary.values())
    clear=sum(x["d2_entries_all_prior_on_outputs_cleared_before_d2"] for x in invariant_summary.values())
    viol=sum(x["d2_entries_clear_order_violations"] for x in invariant_summary.values())

    report=[]
    report.append("# j-7f2a control invariant + PCAP audit\n\n")
    report.append(f"- Canonical GEMMA=7 rows: {tot_d2}\n")
    report.append(f"- GEMMA=7 rows with any output command ON: {tot_d2_on}\n")
    report.append(f"- D2 entry transitions: {ent}\n")
    report.append(f"- D2 entries with any output command ON: {ent_on}\n")
    report.append(f"- D2 entries whose scan began with output ON: {from_on}\n")
    report.append(f"- Of those, all prior ON outputs cleared before D2: {clear}\n")
    report.append(f"- Clear-before-D2 violations: {viol}\n")
    report.append(f"- Positive order-sensitive pairs: {len(all_pairs)}\n")
    report.append(f"- Positive pairs with exactly zero PLC timestamp separation: {result['positive_pairs_zero_timestamp_separation']}\n")
    report.append(f"- Positive pairs with a cyclic PN-RT frame strictly between A and B: {result['positive_pairs_with_network_frame_strictly_between']}\n")
    report.append(f"- PN-RT cycle-counter backward transitions across streams: {result['cycle_counter_backward_total']}\n\n")
    report.append("## PCAP streams\n")
    for r in stream_rows:
        report.append(f"- b{r['batch']:02d} {r['src']} -> {r['dst']} fid={r['frame_id']}: n={r['frames']}, median={r['median_interarrival_ms']} ms, p99={r['p99_interarrival_ms']} ms, max={r['max_interarrival_ms']} ms, counter_back={r['cycle_counter_backward_transitions']}\n")
    (OUT/"pcap_report.md").write_text("".join(report),encoding="utf-8")

print(json.dumps({"status":"ok","pairs":len(all_pairs),"pcap_batches":len(pcaps),"stream_rows":len(stream_rows)},indent=2))
