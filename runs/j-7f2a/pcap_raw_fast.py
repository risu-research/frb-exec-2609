import csv,json,math,re,struct,zipfile
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

OUT=Path("runs/j-7f2a/out"); OUT.mkdir(parents=True,exist_ok=True)
ZIP=Path("/tmp/source.zip")
def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())
def choose(cols,names):
 d={norm(c):c for c in cols}; return next((d[norm(n)] for n in names if norm(n) in d),None)
def n(v):
 try:
  x=float(str(v).strip()); return int(x) if x.is_integer() else x
 except: return None if v is None or str(v).strip()=="" else str(v)
def sk(v):
 x=n(v); return (0,float(x)) if isinstance(x,(int,float)) else (1,str(x))
def bn(s):
 m=re.search(r"batch\s*0*([0-9]+)",s,re.I); return int(m.group(1)) if m else None
def rcsv(z,m):
 raw=z.read(m); txt=raw.decode("utf-8-sig","replace"); sm=txt[:8192]
 try: d=csv.Sniffer().sniff(sm,delimiters=",;\t|").delimiter
 except: d=";" if sm.count(";")>sm.count(",") else ","
 r=csv.DictReader(txt.splitlines(),delimiter=d); return r.fieldnames or [],list(r)
def ts(v):
 if not v or not str(v).strip(): return None
 s=str(v).strip().replace("Z","+00:00")
 try: d=datetime.fromisoformat(s)
 except: return None
 if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
 return d.timestamp()
def state(r,cs): return tuple(n(r.get(c)) for c in cs)
def delta(a,b,cs): return {c:n(b.get(c)) for c in cs if n(a.get(c))!=n(b.get(c))}
def apply(s,d,ix):
 x=list(s)
 for c,v in d.items(): x[ix[c]]=v
 return tuple(x)

def options(body,endian,start):
 pos=start; out={}
 while pos+4<=len(body):
  code,l=struct.unpack(endian+"HH",body[pos:pos+4]); pos+=4
  if code==0: break
  val=body[pos:pos+l]; pos += ((l+3)//4)*4
  out.setdefault(code,[]).append(val)
 return out

def iter_pcapng(path):
 f=open(path,"rb"); endian="<"; resol=[]; section=False
 try:
  while True:
   h=f.read(12)
   if len(h)<12: break
   typraw=h[:4]
   if typraw==b"\x0a\x0d\x0d\x0a":
    magic=h[8:12]
    if magic==b"\x4d\x3c\x2b\x1a": endian="<"
    elif magic==b"\x1a\x2b\x3c\x4d": endian=">"
    else: raise RuntimeError("bad pcapng BOM")
    blen=struct.unpack(endian+"I",h[4:8])[0]
    rest=f.read(blen-12)
    resol=[]; section=True
    continue
   if not section: raise RuntimeError("pcapng missing SHB")
   typ=struct.unpack(endian+"I",typraw)[0]; blen=struct.unpack(endian+"I",h[4:8])[0]
   body0=h[8:12]; rest=f.read(blen-12); body=body0+rest[:-4]
   if typ==1 and len(body)>=8:
    opts=options(body,endian,8); r=1e-6
    if 9 in opts and opts[9] and opts[9][0]:
     b=opts[9][0][0]; r=(2.0**-(b&0x7f)) if (b&0x80) else (10.0**-b)
    resol.append(r)
   elif typ==6 and len(body)>=20:
    iid,hi,lo,caplen,pktlen=struct.unpack(endian+"IIIII",body[:20])
    data=body[20:20+caplen]
    rr=resol[iid] if iid<len(resol) else 1e-6
    t=((hi<<32)|lo)*rr
    yield t,data
 finally: f.close()

def parse_pn(frame):
 if len(frame)<18: return None
 src=":".join(f"{x:02x}" for x in frame[6:12]); dst=":".join(f"{x:02x}" for x in frame[:6])
 et=int.from_bytes(frame[12:14],"big"); off=14
 while et in (0x8100,0x88a8,0x9100) and len(frame)>=off+4:
  et=int.from_bytes(frame[off+2:off+4],"big"); off+=4
 if et!=0x8892 or len(frame)<off+8: return None
 p=frame[off:]; fid=int.from_bytes(p[:2],"big")
 if not (0x8000<=fid<=0xfbff) or len(p)<6: return None
 cyc=int.from_bytes(p[-4:-2],"big"); ds=p[-2]; tr=p[-1]; userdata=p[2:-4]
 return src,dst,fid,cyc,ds,tr,userdata

with zipfile.ZipFile(ZIP) as z:
 names=[x.filename for x in z.infolist()]
 csvs=sorted([x for x in names if x.endswith(".csv") and bn(x)],key=bn)
 pcaps={bn(x):x for x in names if x.endswith(".pcapng") and bn(x)}
 desired=["gemma","a0","a1","b0","b1","c0","c1","B_1","B_2","YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]
 outs={"YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"}
 pairs=[]; invsum={}; invrows=[]; crange={}
 for m in csvs:
  b=bn(m); cols,rows=rcsv(z,m); part=choose(cols,["part_id"]); scan=choose(cols,["scan_id"]); order=choose(cols,["event_order"]); evseq=choose(cols,["event_seq"]); tsc=choose(cols,["ts_plc"]); evid=choose(cols,["event_id"]); dtc=choose(cols,["delta_time_ms"])
  cs=[d for d in desired if d in cols]; ix={c:i for i,c in enumerate(cs)}; by=defaultdict(list)
  for r in rows: by[str(r.get(part))].append(r)
  tv=[ts(r.get(tsc)) for r in rows]; tv=[x for x in tv if x is not None]; crange[b]=(min(tv) if tv else None,max(tv) if tv else None)
  stt=Counter()
  for p,rr in by.items():
   rr.sort(key=lambda r:(sk(r.get(scan)),sk(r.get(order)),sk(r.get(evseq)) if evseq else (0,0)))
   ss=[state(r,cs) for r in rr]; seen=set(ss); ds=[None]+[delta(rr[i-1],rr[i],cs) for i in range(1,len(rr))]
   for i,r in enumerate(rr):
    if ss[i][ix["gemma"]]==7:
     stt["d2_rows"]+=1
     if any(ss[i][ix[o]]==1 for o in outs): stt["d2_rows_on"]+=1
     if i==0 or ss[i-1][ix["gemma"]]!=7:
      stt["d2_entries"]+=1
      if any(ss[i][ix[o]]==1 for o in outs): stt["d2_entries_on"]+=1
      sc=str(r.get(scan)); j=i
      while j>0 and str(rr[j-1].get(scan))==sc: j-=1
      pre=ss[j-1] if j>0 else ss[j]; on=[o for o in outs if pre[ix[o]]==1]; cleared=[]
      for k in range(j,i):
       for o in on:
        if (ds[k] or {}).get(o)==0 and o not in cleared: cleared.append(o)
      if on:
       stt["entries_started_on"]+=1
       if set(on)==set(cleared): stt["entries_cleared_before"]+=1
       else: stt["entries_clear_violation"]+=1
      else: stt["entries_started_zero"]+=1
      invrows.append({"batch":b,"part_id":p,"scan_id":r.get(scan),"event_order_d2":r.get(order),"on_at_scan_start":";".join(on),"cleared_before_d2":";".join(cleared),"on_at_d2":";".join(o for o in outs if ss[i][ix[o]]==1),"ts_d2":r.get(tsc)})
   for i in range(1,len(rr)-1):
    if str(rr[i].get(scan))!=str(rr[i+1].get(scan)): continue
    A,B=ds[i],ds[i+1]
    if not A or not B: continue
    s1=apply(ss[i-1],B,ix); s2=apply(s1,A,ix); bad=s1 not in seen or s2 not in seen; final=s2!=ss[i+1]
    if not (bad or final): continue
    ta,tb=ts(rr[i].get(tsc)),ts(rr[i+1].get(tsc))
    pairs.append({"batch":b,"part_id":p,"scan_id":rr[i].get(scan),"order_A":rr[i].get(order),"order_B":rr[i+1].get(order),"event_id_A":rr[i].get(evid),"event_id_B":rr[i+1].get(evid),"ts_A":rr[i].get(tsc),"ts_B":rr[i+1].get(tsc),"ta":ta,"tb":tb,"separation_us":None if ta is None or tb is None else (tb-ta)*1e6,"delta_A":json.dumps(A,sort_keys=True),"delta_B":json.dumps(B,sort_keys=True),"trace_inconsistent":int(bad),"final_divergent":int(final),"gemma7_after_B":int(B.get("gemma")==7),"actuator_clear_A":int(any(c in outs and v==0 for c,v in A.items())),"frames_between":0,"payload_changes_between":0,"nearest_frame_us":None,"nearest_payload_change_us":None})
  invsum[b]=dict(stt)

 pb=defaultdict(list)
 for q in pairs: pb[q["batch"]].append(q)
 streams=[]; batches={}
 for b,mem in sorted(pcaps.items()):
  tmp=Path(f"/tmp/raw_b{b:02}.pcapng")
  with z.open(mem) as s,open(tmp,"wb") as d:
   while True:
    x=s.read(16*1024*1024)
    if not x: break
    d.write(x)
  S={}; first=last=None; total=0
  for t,frame in iter_pcapng(tmp):
   x=parse_pn(frame)
   if not x: continue
   src,dst,fid,cyc,ds,tr,data=x; total+=1; first=t if first is None else min(first,t); last=t if last is None else max(last,t)
   k=(src,dst,fid); s=S.get(k)
   if s is None: s={"n":0,"lastt":None,"lastc":None,"lastdata":None,"min":None,"max":None,"dt":Counter(),"cd":Counter(),"changes":0}; S[k]=s
   changed=s["lastdata"] is not None and data!=s["lastdata"]
   if changed: s["changes"]+=1
   if s["lastt"] is not None:
    dt=(t-s["lastt"])*1000; s["min"]=dt if s["min"] is None else min(s["min"],dt); s["max"]=dt if s["max"] is None else max(s["max"],dt); s["dt"][round(dt*1000)]+=1; s["cd"][(cyc-s["lastc"])&0xffff]+=1
   s["n"]+=1; s["lastt"]=t; s["lastc"]=cyc; s["lastdata"]=data
   for q in pb.get(b,[]):
    ref=q["tb"] if q["tb"] is not None else q["ta"]
    if ref is not None:
     off=abs(t-ref)*1e6
     if q["nearest_frame_us"] is None or off<q["nearest_frame_us"]: q["nearest_frame_us"]=off
     if changed and (q["nearest_payload_change_us"] is None or off<q["nearest_payload_change_us"]): q["nearest_payload_change_us"]=off
    if q["ta"] is not None and q["tb"] is not None and q["ta"]<t<q["tb"]:
     q["frames_between"]+=1
     if changed: q["payload_changes_between"]+=1
  for (src,dst,fid),s in S.items():
   modeus=s["dt"].most_common(1)[0][0] if s["dt"] else None; fw=[(d,c) for d,c in s["cd"].items() if 0<d<32768]; step=max(fw,key=lambda x:x[1])[0] if fw else None
   streams.append({"batch":b,"src":src,"dst":dst,"frame_id":fid,"frames":s["n"],"payload_changes":s["changes"],"modal_interarrival_ms":None if modeus is None else modeus/1000,"min_interarrival_ms":s["min"],"max_interarrival_ms":s["max"],"modal_cycle_step":step,"counter_backward":sum(c for d,c in s["cd"].items() if d>32768),"counter_duplicate":s["cd"].get(0,0)})
  cs,ce=crange.get(b,(None,None)); batches[b]={"frames":total,"pcap_start":first,"pcap_end":last,"csv_start":cs,"csv_end":ce,"start_offset_s":None if first is None or cs is None else first-cs,"end_offset_s":None if last is None or ce is None else last-ce}
  tmp.unlink(missing_ok=True)

with open(OUT/"raw_pcap_streams.csv","w",newline="",encoding="utf8") as f:
 w=csv.DictWriter(f,fieldnames=list(streams[0])); w.writeheader(); w.writerows(streams)
with open(OUT/"raw_pair_timing.csv","w",newline="",encoding="utf8") as f:
 w=csv.DictWriter(f,fieldnames=list(pairs[0])); w.writeheader(); w.writerows(pairs)
with open(OUT/"raw_invariant_transitions.csv","w",newline="",encoding="utf8") as f:
 w=csv.DictWriter(f,fieldnames=list(invrows[0])); w.writeheader(); w.writerows(invrows)
tot=lambda k:sum(x.get(k,0) for x in invsum.values())
R={"d2_rows":tot("d2_rows"),"d2_rows_on":tot("d2_rows_on"),"d2_entries":tot("d2_entries"),"d2_entries_on":tot("d2_entries_on"),"entries_started_on":tot("entries_started_on"),"entries_cleared_before":tot("entries_cleared_before"),"entries_clear_violation":tot("entries_clear_violation"),"positive_pairs":len(pairs),"pairs_zero_timestamp_separation":sum(q["separation_us"]==0 for q in pairs),"pairs_with_frame_between":sum(q["frames_between"]>0 for q in pairs),"pairs_with_payload_change_between":sum(q["payload_changes_between"]>0 for q in pairs),"gemma7_actuator_clear_pairs":sum(q["gemma7_after_B"] and q["actuator_clear_A"] for q in pairs),"counter_backward_total":sum(s["counter_backward"] for s in streams),"batches":batches,"invariant_by_batch":invsum}
(OUT/"raw_pcap_analysis.json").write_text(json.dumps(R,indent=2),encoding="utf8")
lines=["# Raw PCAPNG audit\n\n"]+[f"- {k}: {v}\n" for k,v in R.items() if k not in ("batches","invariant_by_batch")]
lines+=["\n## Streams\n"]+[f"- b{s['batch']:02} {s['src']}->{s['dst']} fid={s['frame_id']} n={s['frames']} changes={s['payload_changes']} modal={s['modal_interarrival_ms']}ms min={s['min_interarrival_ms']} max={s['max_interarrival_ms']} back={s['counter_backward']}\n" for s in streams]
(OUT/"raw_pcap_report.md").write_text("".join(lines),encoding="utf8")
print(json.dumps(R,indent=2))
