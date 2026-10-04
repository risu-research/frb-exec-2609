import csv, json, math, re, subprocess, zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

OUT=Path("runs/j-7f2a/out"); OUT.mkdir(parents=True,exist_ok=True)
ZIP=Path("/tmp/source.zip")
def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())
def choose(cols,names):
    d={norm(c):c for c in cols}
    return next((d[norm(n)] for n in names if norm(n) in d),None)
def num(v):
    try:
        x=float(str(v).strip()); return int(x) if x.is_integer() else x
    except: return None if v is None or str(v).strip()=="" else str(v)
def key(v):
    x=num(v); return (0,float(x)) if isinstance(x,(int,float)) else (1,str(x))
def batchno(s):
    m=re.search(r"batch\s*0*([0-9]+)",s,re.I); return int(m.group(1)) if m else None
def readcsv(z,m):
    raw=z.read(m); txt=raw.decode("utf-8-sig","replace")
    sm=txt[:8192]
    try: delim=csv.Sniffer().sniff(sm,delimiters=",;\t|").delimiter
    except: delim=";" if sm.count(";")>sm.count(",") else ","
    r=csv.DictReader(txt.splitlines(),delimiter=delim); return r.fieldnames or [],list(r)
def pts(v):
    if not v or not str(v).strip(): return None
    s=str(v).strip().replace("Z","+00:00")
    try: d=datetime.fromisoformat(s)
    except: return None
    if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
    return d.timestamp()
def st(r,cols): return tuple(num(r.get(c)) for c in cols)
def diff(a,b,cols):
    return {c:num(b.get(c)) for c in cols if num(a.get(c))!=num(b.get(c))}
def apply(s,d,idx):
    x=list(s)
    for c,v in d.items(): x[idx[c]]=v
    return tuple(x)

with zipfile.ZipFile(ZIP) as z:
    names=[i.filename for i in z.infolist()]
    csvs=sorted([n for n in names if n.endswith(".csv") and batchno(n)],key=batchno)
    pcaps={batchno(n):n for n in names if n.endswith(".pcapng") and batchno(n)}
    desired=["gemma","a0","a1","b0","b1","c0","c1","B_1","B_2","YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]
    outnames={"YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"}
    inv=[]; invsum={}; pairs=[]; ranges={}
    for m in csvs:
        b=batchno(m); cols,rows=readcsv(z,m)
        part=choose(cols,["part_id"]); scan=choose(cols,["scan_id"]); order=choose(cols,["event_order"]); evseq=choose(cols,["event_seq"])
        tscol=choose(cols,["ts_plc"]); evid=choose(cols,["event_id"]); dtcol=choose(cols,["delta_time_ms"])
        scols=[]
        for d in desired:
            ex=next((c for c in cols if c==d),None)
            if ex: scols.append(ex)
        gem="gemma"; outs=[c for c in scols if c in outnames]; idx={c:i for i,c in enumerate(scols)}
        ts=[pts(r.get(tscol)) for r in rows if tscol]; ts=[x for x in ts if x is not None]
        ranges[b]={"csv_start":min(ts) if ts else None,"csv_end":max(ts) if ts else None}
        by=defaultdict(list)
        for r in rows: by[str(r.get(part))].append(r)
        stat=Counter()
        for p,rr in by.items():
            rr.sort(key=lambda r:(key(r.get(scan)),key(r.get(order)),key(r.get(evseq)) if evseq else (0,0)))
            states=[st(r,scols) for r in rr]; seen=set(states)
            ds=[None]+[diff(rr[i-1],rr[i],scols) for i in range(1,len(rr))]
            for i,r in enumerate(rr):
                if states[i][idx[gem]]==7:
                    stat["d2_rows"]+=1
                    if any(states[i][idx[o]]==1 for o in outs): stat["d2_rows_on"]+=1
                    prev=states[i-1][idx[gem]] if i else None
                    if prev!=7:
                        stat["d2_entries"]+=1
                        if any(states[i][idx[o]]==1 for o in outs): stat["d2_entries_on"]+=1
                        ss=str(r.get(scan)); j=i
                        while j>0 and str(rr[j-1].get(scan))==ss: j-=1
                        pre=states[j-1] if j>0 else states[j]
                        on=[o for o in outs if pre[idx[o]]==1]
                        cleared=[]
                        for k in range(j,i):
                            for o in on:
                                if (ds[k] or {}).get(o)==0 and o not in cleared: cleared.append(o)
                        if on:
                            stat["entries_started_on"]+=1
                            if set(on)==set(cleared): stat["entries_all_cleared_before"]+=1
                            else: stat["entries_clear_violation"]+=1
                        else: stat["entries_started_zero"]+=1
                        inv.append({"batch":b,"part_id":p,"scan_id":r.get(scan),"event_order_d2":r.get(order),
                                    "on_at_scan_start":";".join(on),"cleared_before_d2":";".join(cleared),
                                    "on_at_d2":";".join(o for o in outs if states[i][idx[o]]==1),"ts_d2":r.get(tscol)})
            for i in range(1,len(rr)-1):
                if str(rr[i].get(scan))!=str(rr[i+1].get(scan)): continue
                A,B=ds[i],ds[i+1]
                if not A or not B: continue
                s1=apply(states[i-1],B,idx); s2=apply(s1,A,idx)
                bad=(s1 not in seen) or (s2 not in seen); final=(s2!=states[i+1])
                if not (bad or final): continue
                ta=pts(rr[i].get(tscol)); tb=pts(rr[i+1].get(tscol))
                pairs.append({"batch":b,"part_id":p,"scan_id":rr[i].get(scan),"order_A":rr[i].get(order),"order_B":rr[i+1].get(order),
                              "event_id_A":rr[i].get(evid),"event_id_B":rr[i+1].get(evid),"ts_A":rr[i].get(tscol),"ts_B":rr[i+1].get(tscol),
                              "ta":ta,"tb":tb,"separation_us":None if ta is None or tb is None else (tb-ta)*1e6,
                              "delta_time_A_ms":rr[i].get(dtcol),"delta_time_B_ms":rr[i+1].get(dtcol),
                              "delta_A":json.dumps(A,sort_keys=True),"delta_B":json.dumps(B,sort_keys=True),
                              "trace_inconsistent":int(bad),"final_divergent":int(final),
                              "gemma7_after_B":int(B.get("gemma")==7),"actuator_clear_A":int(any(c in outs and v==0 for c,v in A.items())),
                              "frames_between_A_B":0,"nearest_frame_offset_us":None})
        invsum[b]=dict(stat)

    bypair=defaultdict(list)
    for r in pairs: bypair[r["batch"]].append(r)
    streams_out=[]; batch_out={}
    for b,pm in sorted(pcaps.items()):
        tmp=Path(f"/tmp/b{b:02}.pcapng")
        with z.open(pm) as s, open(tmp,"wb") as d:
            while True:
                x=s.read(8*1024*1024)
                if not x: break
                d.write(x)
        cmd=["tshark","-n","-r",str(tmp),"-Y","pn_rt.cycle_counter","-T","fields","-E","separator=\t","-E","occurrence=f",
             "-e","frame.time_epoch","-e","eth.src","-e","eth.dst","-e","pn_rt.frame_id","-e","pn_rt.cycle_counter"]
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1024*1024)
        S={}
        pcap_start=pcap_end=None; total=0
        targets=bypair.get(b,[])
        for line in proc.stdout:
            v=line.rstrip().split("\t"); v+=[""]*(5-len(v))
            try: t=float(v[0]); src=v[1]; dst=v[2]; fid=int(v[3],0); cyc=int(v[4],0)
            except: continue
            total+=1; pcap_start=t if pcap_start is None else min(pcap_start,t); pcap_end=t if pcap_end is None else max(pcap_end,t)
            k=(src,dst,fid)
            s=S.get(k)
            if s is None:
                s={"n":0,"first":t,"last":t,"last_t":None,"last_c":None,"min_dt":None,"max_dt":None,"dt_us":Counter(),"cycdiff":Counter()}
                S[k]=s
            s["n"]+=1; s["last"]=t
            if s["last_t"] is not None:
                dt=(t-s["last_t"])*1000
                s["min_dt"]=dt if s["min_dt"] is None else min(s["min_dt"],dt); s["max_dt"]=dt if s["max_dt"] is None else max(s["max_dt"],dt)
                s["dt_us"][round(dt*1000)]+=1
                s["cycdiff"][(cyc-s["last_c"]) & 0xffff]+=1
            s["last_t"]=t; s["last_c"]=cyc
            for q in targets:
                ref=q["tb"] if q["tb"] is not None else q["ta"]
                if ref is not None:
                    off=abs(t-ref)*1e6
                    if q["nearest_frame_offset_us"] is None or off<q["nearest_frame_offset_us"]: q["nearest_frame_offset_us"]=off
                if q["ta"] is not None and q["tb"] is not None and q["ta"]<t<q["tb"]: q["frames_between_A_B"]+=1
        proc.wait()
        for (src,dst,fid),s in S.items():
            modal_us=s["dt_us"].most_common(1)[0][0] if s["dt_us"] else None
            forward=[(d,c) for d,c in s["cycdiff"].items() if 0<d<32768]
            modal_step=max(forward,key=lambda x:x[1])[0] if forward else None
            back=sum(c for d,c in s["cycdiff"].items() if d>32768)
            dup=s["cycdiff"].get(0,0)
            streams_out.append({"batch":b,"src":src,"dst":dst,"frame_id":fid,"frames":s["n"],
                                "first_epoch":s["first"],"last_epoch":s["last"],"modal_interarrival_ms":None if modal_us is None else modal_us/1000,
                                "min_interarrival_ms":s["min_dt"],"max_interarrival_ms":s["max_dt"],"modal_cycle_step":modal_step,
                                "cycle_counter_backward":back,"cycle_counter_duplicate":dup})
        rb=ranges.get(b,{})
        batch_out[b]={"pcap_frames":total,"pcap_start":pcap_start,"pcap_end":pcap_end,"csv_start":rb.get("csv_start"),"csv_end":rb.get("csv_end"),
                      "start_offset_s":None if pcap_start is None or rb.get("csv_start") is None else pcap_start-rb["csv_start"],
                      "end_offset_s":None if pcap_end is None or rb.get("csv_end") is None else pcap_end-rb["csv_end"]}
        tmp.unlink(missing_ok=True)

with open(OUT/"invariant_transitions.csv","w",newline="",encoding="utf8") as f:
    w=csv.DictWriter(f,fieldnames=list(inv[0])); w.writeheader(); w.writerows(inv)
with open(OUT/"pair_timing_pcap.csv","w",newline="",encoding="utf8") as f:
    w=csv.DictWriter(f,fieldnames=list(pairs[0])); w.writeheader(); w.writerows(pairs)
with open(OUT/"pcap_streams.csv","w",newline="",encoding="utf8") as f:
    w=csv.DictWriter(f,fieldnames=list(streams_out[0])); w.writeheader(); w.writerows(streams_out)

tot=lambda k:sum(x.get(k,0) for x in invsum.values())
result={"invariant_summary":invsum,"pcap_batches":batch_out,"positive_pairs":len(pairs),
        "d2_rows":tot("d2_rows"),"d2_rows_on":tot("d2_rows_on"),"d2_entries":tot("d2_entries"),"d2_entries_on":tot("d2_entries_on"),
        "entries_started_on":tot("entries_started_on"),"entries_all_cleared_before":tot("entries_all_cleared_before"),"entries_clear_violation":tot("entries_clear_violation"),
        "pairs_zero_timestamp_separation":sum(r["separation_us"]==0 for r in pairs),
        "pairs_with_frame_between":sum(r["frames_between_A_B"]>0 for r in pairs),
        "gemma7_actuator_clear_pairs":sum(r["gemma7_after_B"] and r["actuator_clear_A"] for r in pairs),
        "cycle_counter_backward_total":sum(r["cycle_counter_backward"] for r in streams_out)}
(OUT/"pcap_analysis.json").write_text(json.dumps(result,indent=2),encoding="utf8")
lines=["# Control invariant + PCAP audit\n\n"]
for k,v in result.items():
    if k not in ("invariant_summary","pcap_batches"): lines.append(f"- {k}: {v}\n")
lines.append("\n## Streams\n")
for r in streams_out: lines.append(f"- b{r['batch']:02} fid={r['frame_id']} {r['src']}->{r['dst']} n={r['frames']} modal={r['modal_interarrival_ms']}ms min={r['min_interarrival_ms']} max={r['max_interarrival_ms']} counter_back={r['cycle_counter_backward']}\n")
(OUT/"pcap_report.md").write_text("".join(lines),encoding="utf8")
print(json.dumps({"status":"ok","result":result},indent=2))
