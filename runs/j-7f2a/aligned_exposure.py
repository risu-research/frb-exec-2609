import csv,json,re,struct,zipfile,statistics,bisect
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path
OUT=Path("runs/j-7f2a/out"); OUT.mkdir(parents=True,exist_ok=True)
ZIP=Path("/tmp/source.zip"); BATCHES={2,5,8,9,11}
SIGS=["YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]; BIT={s:i for i,s in enumerate(SIGS)}
def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())
def choose(cols,names):
 d={norm(c):c for c in cols}; return next((d[norm(n)] for n in names if norm(n) in d),None)
def v(x):
 try:
  y=float(str(x).strip()); return int(y) if y.is_integer() else y
 except: return str(x).strip() if x is not None else None
def sk(x):
 y=v(x); return (0,float(y)) if isinstance(y,(int,float)) else (1,str(y))
def bn(s):
 m=re.search(r"batch\\s*0*([0-9]+)",s,re.I); return int(m.group(1)) if m else None
def pts(x):
 if not x or not str(x).strip(): return None
 s=str(x).strip().replace("Z","+00:00")
 try: d=datetime.fromisoformat(s)
 except:
  d=None
  for f in ("%d/%m/%Y %H:%M:%S,%f","%d/%m/%Y %H:%M:%S"):
   try: d=datetime.strptime(s,f); break
   except: pass
  if d is None: return None
 if d.tzinfo is None: d=d.replace(tzinfo=timezone.utc)
 return d.timestamp()
def rcsv(z,m):
 txt=z.read(m).decode("utf-8-sig","replace"); sm=txt[:8192]
 try: delim=csv.Sniffer().sniff(sm,delimiters=",;\\t|").delimiter
 except: delim=";" if sm.count(";")>sm.count(",") else ","
 r=csv.DictReader(txt.splitlines(),delimiter=delim); return r.fieldnames or [],list(r)
def opts(body,e,start):
 p=start; oo={}
 while p+4<=len(body):
  c,l=struct.unpack(e+"HH",body[p:p+4]); p+=4
  if c==0: break
  x=body[p:p+l]; p+=((l+3)//4)*4; oo.setdefault(c,[]).append(x)
 return oo
def packets(path):
 f=open(path,"rb"); e="<"; res=[]; sec=False
 try:
  while True:
   h=f.read(12)
   if len(h)<12: break
   if h[:4]==b"\\x0a\\x0d\\x0d\\x0a":
    e="<" if h[8:12]==b"\\x4d\\x3c\\x2b\\x1a" else ">"
    L=struct.unpack(e+"I",h[4:8])[0]; f.read(L-12); res=[]; sec=True; continue
   if not sec: raise RuntimeError("bad pcapng")
   typ=struct.unpack(e+"I",h[:4])[0]; L=struct.unpack(e+"I",h[4:8])[0]; b0=h[8:12]; rest=f.read(L-12); body=b0+rest[:-4]
   if typ==1 and len(body)>=8:
    o=opts(body,e,8); r=1e-6
    if 9 in o and o[9] and o[9][0]:
     q=o[9][0][0]; r=2.0**-(q&127) if q&128 else 10.0**-q
    res.append(r)
   elif typ==6 and len(body)>=20:
    iid,hi,lo,cap,plen=struct.unpack(e+"IIIII",body[:20]); data=body[20:20+cap]; r=res[iid] if iid<len(res) else 1e-6
    yield ((hi<<32)|lo)*r,data
 finally: f.close()
def pn(fr):
 if len(fr)<18:return None
 dst,src=fr[:6],fr[6:12]; et=int.from_bytes(fr[12:14],"big"); o=14
 while et in (0x8100,0x88a8,0x9100) and len(fr)>=o+4:
  et=int.from_bytes(fr[o+2:o+4],"big"); o+=4
 if et!=0x8892:return None
 p=fr[o:]
 if len(p)<8:return None
 fid=int.from_bytes(p[:2],"big")
 if not 0x8000<=fid<=0xfbff:return None
 cyc=int.from_bytes(p[-4:-2],"big"); data=p[2:-4]
 mac=lambda x:":".join(f"{a:02x}" for a in x)
 return mac(src),mac(dst),fid,cyc,data
def nearest(arr,x):
 if not arr:return None
 i=bisect.bisect_left(arr,x); c=[]
 if i<len(arr):c.append(arr[i])
 if i:c.append(arr[i-1])
 return min(c,key=lambda q:abs(q-x)) if c else None
def fit_lag(events,trans,maxlag=2.0):
 hist=Counter()
 for ev in events[:100]:
  arr=trans.get((ev["bit"],ev["new"]),[])
  lo=bisect.bisect_left(arr,ev["t"]-maxlag); hi=bisect.bisect_right(arr,ev["t"]+maxlag)
  for tt in arr[lo:hi]: hist[round((tt-ev["t"])*1000)]+=1
 if not hist:return None
 lag0=hist.most_common(1)[0][0]/1000; diffs=[]
 for ev in events:
  arr=trans.get((ev["bit"],ev["new"]),[]); q=nearest(arr,ev["t"]+lag0)
  if q is not None and abs(q-(ev["t"]+lag0))<=.006: diffs.append(q-ev["t"])
 if not diffs:return None
 lag=statistics.median(diffs); res=[]
 for ev in events:
  arr=trans.get((ev["bit"],ev["new"]),[]); q=nearest(arr,ev["t"]+lag)
  if q is not None and abs(q-(ev["t"]+lag))<=.003: res.append((q-(ev["t"]+lag))*1000)
 return {"lag":lag,"matches":len(res),"total":len(events),"mad_ms":statistics.median([abs(x) for x in res]) if res else None}

with zipfile.ZipFile(ZIP) as z:
 names=[x.filename for x in z.infolist()]
 csvs={bn(x):x for x in names if x.endswith(".csv") and bn(x) in BATCHES}
 pcaps={bn(x):x for x in names if x.endswith(".pcapng") and bn(x) in BATCHES}
 csv_events={}; targets=[]
 for b,m in sorted(csvs.items()):
  cols,rows=rcsv(z,m); part=choose(cols,["part_id"]); scan=choose(cols,["scan_id"]); order=choose(cols,["event_order"]); seq=choose(cols,["event_seq"]); tsc=choose(cols,["ts_plc"])
  by=defaultdict(list)
  for r in rows: by[str(r.get(part))].append(r)
  evs=[]
  for p,rr in by.items():
   rr.sort(key=lambda r:(sk(r.get(scan)),sk(r.get(order)),sk(r.get(seq))))
   for i in range(1,len(rr)):
    t=pts(rr[i].get(tsc))
    for s in SIGS:
     a,bv=v(rr[i-1].get(s)),v(rr[i].get(s))
     if a!=bv and bv in (0,1): evs.append({"t":t,"sig":s,"bit":BIT[s],"old":a,"new":bv})
   for i in range(1,len(rr)-1):
    if str(rr[i].get(scan))!=str(rr[i+1].get(scan)): continue
    if v(rr[i+1].get("gemma"))==7 and v(rr[i].get("gemma"))!=7:
     for s in SIGS:
      if v(rr[i-1].get(s))==1 and v(rr[i].get(s))==0:
       targets.append({"batch":b,"part_id":p,"scan_id":rr[i].get(scan),"signal":s,"bit":BIT[s],"tA":pts(rr[i].get(tsc)),"tB":pts(rr[i+1].get(tsc)),"ts_A":rr[i].get(tsc),"ts_B":rr[i+1].get(tsc)})
  csv_events[b]=sorted(evs,key=lambda x:x["t"])
 pcap_trans={}
 for b,m in sorted(pcaps.items()):
  tmp=Path(f"/tmp/al_b{b}.pcapng")
  with z.open(m) as s,open(tmp,"wb") as d:
   while True:
    x=s.read(16*1024*1024)
    if not x: break
    d.write(x)
  lastcyc={}; lastdata={}; trans=defaultdict(lambda:defaultdict(lambda:defaultdict(list)))
  for t,fr in packets(tmp):
   q=pn(fr)
   if not q: continue
   src,dst,fid,cyc,data=q; k=(src,dst,fid)
   if lastcyc.get(k)==cyc: continue
   lastcyc[k]=cyc; prev=lastdata.get(k)
   if prev is not None:
    L=min(len(prev),len(data),16)
    for off in range(L):
     ch=prev[off]^data[off]
     if ch:
      for bit in range(6):
       if ch&(1<<bit): trans[k][off][(bit,(data[off]>>bit)&1)].append(t)
   lastdata[k]=data
  pcap_trans[b]=trans; tmp.unlink(missing_ok=True)

 keys=set()
 for d in pcap_trans.values():
  for stream,offs in d.items():
   for off in offs: keys.add((stream,off))
 scored=[]
 for stream,off in keys:
  matches=0; total=0; fits={}
  for b in BATCHES:
   if stream in pcap_trans.get(b,{}) and off in pcap_trans[b][stream]:
    f=fit_lag(csv_events[b],pcap_trans[b][stream][off])
    if f: fits[b]=f; matches+=f["matches"]; total+=f["total"]
  scored.append({"stream":stream,"off":off,"matches":matches,"total":total,"fits":fits})
 scored.sort(key=lambda x:(x["matches"],-x["off"]),reverse=True); best=scored[0]
 results=[]
 for q in targets:
  b=q["batch"]; fit=best["fits"].get(b); stream=best["stream"]; off=best["off"]; found=None
  if fit:
   arr=pcap_trans[b][stream][off].get((q["bit"],0),[]); expected=q["tA"]+fit["lag"]; tt=nearest(arr,expected)
   if tt is not None and abs(tt-expected)<=.004: found=tt
  eq=(found-fit["lag"]) if found is not None and fit else None
  signed=(eq-q["tB"])*1000 if eq is not None else None
  results.append({**q,"src":stream[0],"dst":stream[1],"fid":stream[2],"byte_offset":off,
   "clock_lag_pcap_minus_plc_ms":fit["lag"]*1000 if fit else None,"clock_fit_matches":fit["matches"] if fit else 0,"clock_fit_total":fit["total"] if fit else 0,"clock_fit_mad_ms":fit["mad_ms"] if fit else None,
   "network_clear_pcap_epoch":found,"network_clear_plc_equiv_epoch":eq,"network_clear_minus_internal_clear_ms":(eq-q["tA"])*1000 if eq is not None else None,
   "exposure_after_D2_ms_signed":signed,"exposure_after_D2_ms":max(0,signed) if signed is not None else None,"mapped":int(found is not None)})
 with open(OUT/"aligned_exposure_windows.csv","w",newline="",encoding="utf8") as f:
  w=csv.DictWriter(f,fieldnames=list(results[0])); w.writeheader(); w.writerows(results)
 ex=[r["exposure_after_D2_ms"] for r in results if r["exposure_after_D2_ms"] is not None]; signed=[r["exposure_after_D2_ms_signed"] for r in results if r["exposure_after_D2_ms_signed"] is not None]
 summary={"targets":len(targets),"mapped":sum(r["mapped"] for r in results),
  "best_mapping":{"src":best["stream"][0],"dst":best["stream"][1],"fid":best["stream"][2],"byte_offset":best["off"],"matches":best["matches"],"total":best["total"],"batch_fits":best["fits"]},
  "top_candidates":[{"src":x["stream"][0],"dst":x["stream"][1],"fid":x["stream"][2],"byte_offset":x["off"],"matches":x["matches"],"total":x["total"]} for x in scored[:10]],
  "exposure_stats_ms":None if not ex else {"min":min(ex),"median":statistics.median(ex),"mean":statistics.mean(ex),"max":max(ex),"positive":sum(x>0 for x in ex),"zero":sum(x==0 for x in ex)},
  "signed_stats_ms":None if not signed else {"min":min(signed),"median":statistics.median(signed),"mean":statistics.mean(signed),"max":max(signed)}}
 (OUT/"aligned_exposure_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf8")
 (OUT/"aligned_exposure_report.md").write_text("# Aligned cross-layer exposure audit\n\n"+json.dumps(summary,indent=2)+"\n",encoding="utf8")
 print(json.dumps(summary,indent=2))
