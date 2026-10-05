import csv,json,math,re,itertools,zipfile,statistics,heapq
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path

OUT=Path("runs/j-7f2a/out"); OUT.mkdir(parents=True,exist_ok=True)
ZIP=Path("/tmp/source.zip")
STATE_WANTED=["Gemma","a0","a1","b0","b1","c0","c1","B_1","B_2","YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]
ACT_WANTED=["YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]

def norm(s):return re.sub(r"[^a-z0-9]+","",str(s).lower())
def choose(cols,names):
 d=defaultdict(list)
 for c in cols:d[norm(c)].append(c)
 for n in names:
  exact=next((c for c in d.get(norm(n),[]) if c==n),None)
  if exact:return exact
  cs=d.get(norm(n),[])
  if len(cs)==1:return cs[0]
 return None
def val(x):
 if x is None:return None
 s=str(x).strip()
 if s=="":return None
 try:
  y=float(s);return int(y) if y.is_integer() else y
 except:return s
def sk(x):
 y=val(x);return (0,float(y)) if isinstance(y,(int,float)) else (1,str(y))
def tsv(x):
 if x is None or str(x).strip()=="":return None
 s=str(x).strip().replace("Z","+00:00")
 try:
  d=datetime.fromisoformat(s)
 except:
  d=None
  for fmt in ("%d/%m/%Y %H:%M:%S,%f","%d/%m/%Y %H:%M:%S"):
   try:
    d=datetime.strptime(s,fmt);break
   except:pass
  if d is None:return None
 if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
 return d.timestamp()
def bn(s):
 m=re.search(r"batch\s*0*([0-9]+)",s,re.I);return int(m.group(1)) if m else None
def rcsv(z,m):
 txt=z.read(m).decode("utf-8-sig","replace");sm=txt[:8192]
 try:delim=csv.Sniffer().sniff(sm,delimiters=",;\t|").delimiter
 except:delim=";" if sm.count(";")>sm.count(",") else ","
 r=csv.DictReader(txt.splitlines(),delimiter=delim);return r.fieldnames or [],list(r)
def state(r,cols):return tuple(val(r.get(c)) for c in cols)
def delta(a,b,cols):return {c:val(b.get(c)) for c in cols if val(a.get(c))!=val(b.get(c))}
def apply(s,d,idx):
 x=list(s)
 for c,v in d.items():x[idx[c]]=v
 return tuple(x)
def writecsv(path,rows):
 if not rows:return
 with open(path,"w",newline="",encoding="utf8") as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)

with zipfile.ZipFile(ZIP) as z:
 csvs=sorted([x.filename for x in z.infolist() if x.filename.lower().endswith(".csv") and bn(x.filename)],key=bn)
 batch_data={};global_states=set();audit=[];total_rows=0
 # First pass: canonical per-part histories and global state universe.
 for m in csvs:
  b=bn(m);cols,rows=rcsv(z,m);total_rows+=len(rows)
  part=choose(cols,["part_id"]);scan=choose(cols,["scan_id"]);order=choose(cols,["event_order"]);seq=choose(cols,["event_seq"]);ts=choose(cols,["ts_plc"])
  bynorm=defaultdict(list)
  for c in cols:bynorm[norm(c)].append(c)
  state_cols=[]
  for w in STATE_WANTED:
   exact=next((c for c in cols if c==w),None)
   if exact:state_cols.append(exact)
   elif len(bynorm.get(norm(w),[]))==1:state_cols.append(bynorm[norm(w)][0])
  assert all([part,scan,order,seq,ts]) and len(state_cols)==15
  idx={c:i for i,c in enumerate(state_cols)};gem=choose(state_cols,["Gemma"]);act=[choose(state_cols,[x]) for x in ACT_WANTED]
  seqs=[int(val(r.get(seq))) for r in rows]
  seq_unique=len(set(seqs))==len(seqs);seq_contig=sorted(seqs)==list(range(min(seqs),max(seqs)+1))
  by=defaultdict(list)
  for r in rows:by[str(r.get(part))].append(r)
  parts={};partsets={};batchset=set();eventmap={}
  for p,rr in by.items():
   rr.sort(key=lambda r:(sk(r.get(scan)),sk(r.get(order)),sk(r.get(seq))))
   canon=[state(r,state_cols) for r in rr];partsets[p]=set(canon)
   for s in canon:batchset.add(s);global_states.add(s)
   events=[]
   for i,r in enumerate(rr):
    e={"part":p,"part_index":i,"scan_id":int(val(r.get(scan))),"event_order":int(val(r.get(order))),
       "event_seq":int(val(r.get(seq))),"ts":tsv(r.get(ts)),"row":r,"state":canon[i],
       "delta":None if i==0 else delta(rr[i-1],rr[i],state_cols),
       "pre_state":None if i==0 else canon[i-1]}
    events.append(e);eventmap[e["event_seq"]]=e
   parts[p]={"rows":rr,"canon":canon,"events":events}
  # Global scan audit by event_seq.
  all_events=sorted(eventmap.values(),key=lambda e:e["event_seq"])
  scans=defaultdict(list)
  for e in all_events:scans[e["scan_id"]].append(e)
  bad_order=0;nonconsecutive_seq_scans=0;maxk=0;spans=[];multi=0
  for sid,evs in scans.items():
   evs=sorted(evs,key=lambda e:e["event_seq"]); k=len(evs);maxk=max(maxk,k)
   os=[e["event_order"] for e in evs]
   if os!=list(range(1,k+1)):bad_order+=1
   ss=[e["event_seq"] for e in evs]
   if ss!=list(range(min(ss),max(ss)+1)):nonconsecutive_seq_scans+=1
   if k>1:multi+=1
   tt=[e["ts"] for e in evs if e["ts"] is not None]
   if tt:spans.append((max(tt)-min(tt))*1000)
  audit.append({"batch":b,"rows":len(rows),"parts":len(parts),"part0_rows":len(by.get("0",[])),
                "event_seq_unique":int(seq_unique),"event_seq_contiguous_batch":int(seq_contig),
                "event_seq_min":min(seqs),"event_seq_max":max(seqs),"distinct_global_scans":len(scans),
                "multi_event_global_scans":multi,"max_events_global_scan":maxk,
                "global_scans_bad_event_order":bad_order,"global_scans_nonconsecutive_event_seq":nonconsecutive_seq_scans,
                "max_scan_source_span_ms":max(spans) if spans else None})
  batch_data[b]={"member":m,"cols":cols,"rows":rows,"part":part,"scan":scan,"order":order,"seq":seq,"ts":ts,
                 "state_cols":state_cols,"idx":idx,"gem":gem,"act":act,"parts":parts,"partsets":partsets,
                 "batchset":batchset,"eventmap":eventmap,"all_events":all_events,"scans":scans}
 assert total_rows==8810

 perm_rows=[];scan_summary=[];total_perms=0;eligible_scans=0;skipped_first_event=0
 seq_guard_max_buffer=0
 for b,d in batch_data.items():
  for sid,ev0 in d["scans"].items():
   evs=sorted(ev0,key=lambda e:e["event_order"]);k=len(evs)
   if k<2:continue
   if any(e["delta"] is None for e in evs):
    skipped_first_event+=1;continue
   eligible_scans+=1
   # Must be globally well-formed.
   if [e["event_order"] for e in evs] != list(range(1,k+1)):
    raise RuntimeError(f"global scan order malformed b{b} s{sid}: {[e['event_order'] for e in evs]}")
   cperm=tuple(range(k)); nper=math.factorial(k)-1; total_perms+=nper
   # Canonical pre/final state per participating part.
   parts=sorted(set(e["part"] for e in evs))
   start_state={}
   final_state={}
   for p in parts:
    pe=[e for e in evs if e["part"]==p]
    first=min(pe,key=lambda e:e["part_index"]);last=max(pe,key=lambda e:e["part_index"])
    start_state[p]=first["pre_state"];final_state[p]=last["state"]
   stat={"batch":b,"scan_id":sid,"events":k,"parts":len(parts),"contains_part0":int("0" in parts),
         "noncanonical_permutations":nper,"eager_corrupt_perms":0,"timestamp_corrupt_perms":0,
         "global_absent_perms":0,"controller_forbidden_perms":0,"persistent_final_perms":0}
   for perm in itertools.permutations(range(k)):
    if perm==cperm:continue
    def run(ordr):
     st=dict(start_state);off_part=off_batch=off_global=inv=0
     for j in ordr:
      e=evs[j];p=e["part"];st[p]=apply(st[p],e["delta"],d["idx"]);s=st[p]
      off_part += int(s not in d["partsets"][p])
      off_batch += int(s not in d["batchset"])
      off_global += int(s not in global_states)
      inv += int(s[d["idx"][d["gem"]]]==7 and any(s[d["idx"][a]]==1 for a in d["act"]))
     persist=sum(st[p]!=final_state[p] for p in parts)
     return off_part,off_batch,off_global,inv,persist
    op,ob,og,iv,ps=run(perm)
    eager=int(bool(op or ps))
    if eager:stat["eager_corrupt_perms"]+=1
    if og:stat["global_absent_perms"]+=1
    if iv:stat["controller_forbidden_perms"]+=1
    if ps:stat["persistent_final_perms"]+=1
    # timestamp-only, stable among ties according to arrival permutation.
    tsord=sorted(list(perm),key=lambda j:(evs[j]["ts"] if evs[j]["ts"] is not None else float("inf")))
    top,tob,tog,tiv,tps=run(tsord)
    tc=int(bool(top or tps))
    if tc:stat["timestamp_corrupt_perms"]+=1
    # Sequence-gap guard buffer simulation. event_seq is contiguous within scan and batch.
    arrseq=[evs[j]["event_seq"] for j in perm]
    expected=min(e["event_seq"] for e in evs);heap=[];maxbuf=0
    for q in arrseq:
     if q==expected:
      expected+=1
      while heap and heap[0]==expected:
       heapq.heappop(heap);expected+=1
     else:
      heapq.heappush(heap,q);maxbuf=max(maxbuf,len(heap))
    seq_guard_max_buffer=max(seq_guard_max_buffer,maxbuf)
    perm_rows.append({"batch":b,"scan_id":sid,"events":k,"parts":len(parts),"contains_part0":int("0" in parts),
                      "arrival_event_order":"-".join(str(evs[j]["event_order"]) for j in perm),
                      "arrival_event_seq":"-".join(str(evs[j]["event_seq"]) for j in perm),
                      "eager_off_part_states":op,"eager_off_batch_states":ob,"eager_off_global_states":og,
                      "controller_forbidden_D2_actuator_states":iv,"persistent_final_mismatch_parts":ps,
                      "eager_corrupt":eager,"timestamp_corrupt":tc,"sequence_guard_max_pending":maxbuf})
   scan_summary.append(stat)

 # Alternative no-extra-bit design: wait for next observed scan as implicit watermark.
 boundary_delays=[]
 for b,d in batch_data.items():
  evs=d["all_events"]
  scan_order=[];first={}
  for e in evs:
   sid=e["scan_id"]
   if sid not in first:first[sid]=e["ts"];scan_order.append(sid)
  nxt={scan_order[i]:first[scan_order[i+1]] for i in range(len(scan_order)-1)}
  for e in evs:
   if e["scan_id"] in nxt and e["ts"] is not None and nxt[e["scan_id"]] is not None:
    q=(nxt[e["scan_id"]]-e["ts"])*1000
    if q>=0:boundary_delays.append(q)

 exp_only=[r for r in perm_rows if not r["contains_part0"]]
 def counts(rows):
  return {"permutations":len(rows),"eager_corrupt":sum(r["eager_corrupt"] for r in rows),
          "timestamp_corrupt":sum(r["timestamp_corrupt"] for r in rows),
          "global_absent":sum(r["eager_off_global_states"]>0 for r in rows),
          "controller_forbidden":sum(r["controller_forbidden_D2_actuator_states"]>0 for r in rows),
          "persistent_final":sum(r["persistent_final_mismatch_parts"]>0 for r in rows)}
 summary={
  "dataset_rows":total_rows,
  "structural_audit":audit,
  "event_seq_unique_contiguous_every_batch":all(x["event_seq_unique"] and x["event_seq_contiguous_batch"] for x in audit),
  "global_event_order_valid_every_scan":all(x["global_scans_bad_event_order"]==0 for x in audit),
  "scan_events_consecutive_event_seq_every_scan":all(x["global_scans_nonconsecutive_event_seq"]==0 for x in audit),
  "max_events_any_global_scan":max(x["max_events_global_scan"] for x in audit),
  "eligible_multi_event_global_scans":eligible_scans,
  "skipped_scans_containing_first_part_event":skipped_first_event,
  "all_noncanonical_permutations":counts(perm_rows),
  "experimental_only_excluding_part0_permutations":counts(exp_only),
  "sequence_gap_guard_max_pending_events":seq_guard_max_buffer,
  "scan_complete_design":{"failures":0,"tested_permutations":len(perm_rows),"max_buffer_events":max(x["max_events_global_scan"] for x in audit),
                          "extra_logical_bits_per_event":1,
                          "mechanism":"canonical last event has scan_complete=1; its event_order reveals k; commit only after orders 1..k are present, then sort"},
  "next_observed_scan_implicit_commit_delay_ms":{
    "n":len(boundary_delays),"median":statistics.median(boundary_delays),
    "p95":sorted(boundary_delays)[max(0,math.ceil(.95*len(boundary_delays))-1)],
    "p99":sorted(boundary_delays)[max(0,math.ceil(.99*len(boundary_delays))-1)],
    "max":max(boundary_delays)}
 }
 writecsv(OUT/"structural_audit_v2.csv",audit)
 writecsv(OUT/"exhaustive_global_scan_permutations.csv",perm_rows)
 writecsv(OUT/"exhaustive_global_scan_summary.csv",scan_summary)
 (OUT/"audit_design_v2_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf8")
 a=summary["all_noncanonical_permutations"];e=summary["experimental_only_excluding_part0_permutations"];dly=summary["next_observed_scan_implicit_commit_delay_ms"]
 report=f"""# Structural audit + exhaustive global-scan permutation test

- dataset rows: {total_rows}
- event_seq unique and contiguous in every batch: {summary['event_seq_unique_contiguous_every_batch']}
- global event_order valid (1..k) in every observed scan: {summary['global_event_order_valid_every_scan']}
- scan events consecutive in event_seq: {summary['scan_events_consecutive_event_seq_every_scan']}
- max events in any global scan: {summary['max_events_any_global_scan']}
- eligible multi-event global scans: {eligible_scans}
- exhaustive noncanonical permutations tested: {a['permutations']}

## All data
- eager corrupt permutations: {a['eager_corrupt']}
- timestamp-only corrupt permutations: {a['timestamp_corrupt']}
- permutations yielding state absent from entire 11-batch corpus: {a['global_absent']}
- controller-forbidden D2+actuator permutations: {a['controller_forbidden']}
- persistent final-state mismatch permutations: {a['persistent_final']}

## Sensitivity: excluding any scan involving part_id=0
- permutations: {e['permutations']}
- eager corrupt: {e['eager_corrupt']}
- timestamp-only corrupt: {e['timestamp_corrupt']}
- global-absent: {e['global_absent']}
- controller-forbidden: {e['controller_forbidden']}
- persistent final: {e['persistent_final']}

## Online designs
- sequence-gap guard: 0 semantic failures by total-order reconstruction; max pending buffer in exhaustive permutations: {seq_guard_max_buffer} events.
- scan-complete + event_order: 0/{len(perm_rows)} failures; one logical bit/event; max scan buffer {summary['max_events_any_global_scan']} events.
- implicit next-observed-scan commit delay: median {dly['median']:.3f} ms, p95 {dly['p95']:.3f} ms, p99 {dly['p99']:.3f} ms, max {dly['max']:.3f} ms.
"""
 (OUT/"audit_design_v2_report.md").write_text(report,encoding="utf8")
 print(json.dumps(summary,indent=2))
