import csv,json,re,struct,zipfile,statistics
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path

OUT=Path("runs/j-7f2a/out"); OUT.mkdir(parents=True,exist_ok=True)
ZIP=Path("/tmp/source.zip")
TARGET_BATCHES={2,5,8,9,11}
BIT={"YA_p":0,"YA_m":1,"YB_p":2,"YB_m":3,"YC_p":4,"YC_m":5}

def norm(s): return re.sub(r"[^a-z0-9]+","",str(s).lower())
def choose(cols,names):
 d={norm(c):c for c in cols}; return next((d[norm(n)] for n in names if norm(n) in d),None)
def val(v):
 try:
  x=float(str(v).strip()); return int(x) if x.is_integer() else x
 except: return str(v).strip() if v is not None else None
def sk(v):
 x=val(v); return (0,float(x)) if isinstance(x,(int,float)) else (1,str(x))
def bn(s):
 m=re.search(r"batch\s*0*([0-9]+)",s,re.I); return int(m.group(1)) if m else None
def rcsv(z,m):
 raw=z.read(m); txt=raw.decode("utf-8-sig","replace"); sm=txt[:8192]
 try: d=csv.Sniffer().sniff(sm,delimiters=",;\t|").delimiter
 except: d=";" if sm.count(";")>sm.count(",") else ","
 r=csv.DictReader(txt.splitlines(),delimiter=d); return r.fieldnames or [],list(r)
def pts(v):
 if not v or not str(v).strip(): return None
 s=str(v).strip().replace("Z","+00:00")
 try: d=datetime.fromisoformat(s)
 except:
  d=None
  for fmt in ("%d/%m/%Y %H:%M:%S,%f","%d/%m/%Y %H:%M:%S"):
   try: d=datetime.strptime(s,fmt); break
   except: pass
  if d is None:return None
 if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
 return d.timestamp()
def state(r,cols): return tuple(val(r.get(c)) for c in cols)
def delta(a,b,cols): return {c:val(b.get(c)) for c in cols if val(a.get(c))!=val(b.get(c))}
def apply(s,d,ix):
 x=list(s)
 for c,v in d.items():x[ix[c]]=v
 return tuple(x)

def opt(body,endian,start):
 p=start; out={}
 while p+4<=len(body):
  code,l=struct.unpack(endian+"HH",body[p:p+4]);p+=4
  if code==0:break
  x=body[p:p+l];p+=((l+3)//4)*4;out.setdefault(code,[]).append(x)
 return out
def iterpcap(path):
 f=open(path,"rb");endian="<";res=[];sec=False
 try:
  while 1:
   h=f.read(12)
   if len(h)<12:break
   if h[:4]==b"\x0a\x0d\x0d\x0a":
    magic=h[8:12]
    endian="<" if magic==b"\x4d\x3c\x2b\x1a" else ">"
    bl=struct.unpack(endian+"I",h[4:8])[0];f.read(bl-12);res=[];sec=True;continue
   if not sec:raise RuntimeError("bad pcapng")
   typ=struct.unpack(endian+"I",h[:4])[0];bl=struct.unpack(endian+"I",h[4:8])[0];body0=h[8:12];rest=f.read(bl-12);body=body0+rest[:-4]
   if typ==1 and len(body)>=8:
    oo=opt(body,endian,8);rr=1e-6
    if 9 in oo and oo[9] and oo[9][0]:
     b=oo[9][0][0];rr=2.0**-(b&127) if b&128 else 10.0**-b
    res.append(rr)
   elif typ==6 and len(body)>=20:
    iid,hi,lo,cap,pkt=struct.unpack(endian+"IIIII",body[:20]);data=body[20:20+cap];rr=res[iid] if iid<len(res) else 1e-6;yield ((hi<<32)|lo)*rr,data
 finally:f.close()
def pn(frame):
 if len(frame)<18:return None
 dst=frame[:6];src=frame[6:12];et=int.from_bytes(frame[12:14],"big");o=14
 while et in (0x8100,0x88a8,0x9100) and len(frame)>=o+4:
  et=int.from_bytes(frame[o+2:o+4],"big");o+=4
 if et!=0x8892:return None
 p=frame[o:]
 if len(p)<8:return None
 fid=int.from_bytes(p[:2],"big")
 if not 0x8000<=fid<=0xfbff:return None
 cyc=int.from_bytes(p[-4:-2],"big");data=p[2:-4]
 mac=lambda x:":".join(f"{b:02x}" for b in x)
 return mac(src),mac(dst),fid,cyc,data

with zipfile.ZipFile(ZIP) as z:
 names=[i.filename for i in z.infolist()]
 csvs={bn(x):x for x in names if x.endswith(".csv") and bn(x) in TARGET_BATCHES}
 pcaps={bn(x):x for x in names if x.endswith(".pcapng") and bn(x) in TARGET_BATCHES}
 desired=["gemma","a0","a1","b0","b1","c0","c1","B_1","B_2","YA_p","YA_m","YB_p","YB_m","YC_p","YC_m"]
 targets=[]
 for b,m in sorted(csvs.items()):
  cols,rows=rcsv(z,m); part=choose(cols,["part_id"]);scan=choose(cols,["scan_id"]);order=choose(cols,["event_order"]);evseq=choose(cols,["event_seq"]);tsc=choose(cols,["ts_plc"])
  cs=[x for x in desired if x in cols];ix={c:i for i,c in enumerate(cs)};by=defaultdict(list)
  for r in rows:by[str(r.get(part))].append(r)
  for p,rr in by.items():
   rr.sort(key=lambda r:(sk(r.get(scan)),sk(r.get(order)),sk(r.get(evseq))))
   ss=[state(r,cs) for r in rr];ds=[None]+[delta(rr[i-1],rr[i],cs) for i in range(1,len(rr))]
   for i in range(1,len(rr)-1):
    if str(rr[i].get(scan))!=str(rr[i+1].get(scan)):continue
    A,B=ds[i],ds[i+1]
    if not A or not B or B.get("gemma")!=7:continue
    clears=[c for c,v in A.items() if c in BIT and v==0]
    if not clears:continue
    for sig in clears:
     targets.append({"batch":b,"part_id":p,"scan_id":rr[i].get(scan),"signal":sig,"bit":BIT[sig],
                     "tA":pts(rr[i].get(tsc)),"tB":pts(rr[i+1].get(tsc)),"ts_A":rr[i].get(tsc),"ts_B":rr[i+1].get(tsc)})
 print("targets",len(targets))
 byb=defaultdict(list)
 for q in targets:byb[q["batch"]].append(q)
 # collect deduped unique-cycle frames within +-6 ms of any target
 allrows=[]
 for b,m in sorted(pcaps.items()):
  qlist=byb[b];lo=min(q["tA"] for q in qlist)-.006;hi=max(q["tB"] for q in qlist)+.006
  windows=[(q["tA"]-.006,q["tB"]+.006,q) for q in qlist]
  tmp=Path(f"/tmp/exposure_b{b}.pcapng")
  with z.open(m) as s,open(tmp,"wb") as d:
   while 1:
    x=s.read(16*1024*1024)
    if not x:break
    d.write(x)
  last_cycle={}
  for t,frame in iterpcap(tmp):
   if t<lo or t>hi:continue
   x=pn(frame)
   if not x:continue
   src,dst,fid,cyc,data=x;k=(src,dst,fid)
   if last_cycle.get(k)==cyc:continue
   last_cycle[k]=cyc
   for wl,wh,q in windows:
    if wl<=t<=wh:
     allrows.append({"batch":b,"part_id":q["part_id"],"scan_id":q["scan_id"],"signal":q["signal"],"bit":q["bit"],
                     "tA":q["tA"],"tB":q["tB"],"src":src,"dst":dst,"fid":fid,"time":t,"cycle":cyc,"payload":data.hex()})
  tmp.unlink(missing_ok=True)

# infer a single stream+byte offset that explains target 1->0 transitions.
groups=defaultdict(list)
for r in allrows:groups[(r["batch"],r["part_id"],r["scan_id"],r["signal"],r["src"],r["dst"],r["fid"])].append(r)
candidates=Counter()
transitions=[]
for k,rr in groups.items():
 rr.sort(key=lambda x:x["time"]); bit=rr[0]["bit"]; tA=rr[0]["tA"];tB=rr[0]["tB"]
 payloads=[bytes.fromhex(x["payload"]) for x in rr]; maxlen=min(map(len,payloads)) if payloads else 0
 for off in range(maxlen):
  for i in range(1,len(rr)):
   before=(payloads[i-1][off]>>bit)&1;after=(payloads[i][off]>>bit)&1
   if before==1 and after==0 and (tA-.003)<=rr[i]["time"]<=(tB+.004):
    candidates[(rr[i]["src"],rr[i]["dst"],rr[i]["fid"],off)]+=1
    transitions.append({"batch":rr[i]["batch"],"part_id":rr[i]["part_id"],"scan_id":rr[i]["scan_id"],"signal":rr[i]["signal"],
                        "src":rr[i]["src"],"dst":rr[i]["dst"],"fid":rr[i]["fid"],"byte_offset":off,
                        "clear_frame_time":rr[i]["time"],"prev_frame_time":rr[i-1]["time"],"tA":tA,"tB":tB,
                        "clear_minus_A_ms":(rr[i]["time"]-tA)*1000,"clear_minus_B_ms":(rr[i]["time"]-tB)*1000,
                        "prev_bit":before,"new_bit":after})
best=candidates.most_common(10)
# Apply best mapping, then compute exact per-case first 1->0.
results=[]
if best:
 bestkey=best[0][0]
 for q in targets:
  src,dst,fid,off=bestkey
  rr=groups.get((q["batch"],q["part_id"],q["scan_id"],q["signal"],src,dst,fid),[])
  rr=sorted(rr,key=lambda x:x["time"])
  bit=q["bit"]; found=None
  for i in range(1,len(rr)):
   a=bytes.fromhex(rr[i-1]["payload"]);bb=bytes.fromhex(rr[i]["payload"])
   if off>=len(a) or off>=len(bb):continue
   if ((a[off]>>bit)&1)==1 and ((bb[off]>>bit)&1)==0 and q["tA"]-.003<=rr[i]["time"]<=q["tB"]+.004:
    found=(rr[i-1],rr[i]);break
  results.append({**q,"mapping_src":src,"mapping_dst":dst,"mapping_fid":fid,"byte_offset":off,
                  "clear_frame_time":found[1]["time"] if found else None,
                  "prev_frame_time":found[0]["time"] if found else None,
                  "exposure_after_D2_ms":max(0,(found[1]["time"]-q["tB"])*1000) if found else None,
                  "network_clear_minus_internal_clear_ms":(found[1]["time"]-q["tA"])*1000 if found else None,
                  "found":int(found is not None)})

for name,rows in [("exposure_windows.csv",results),("exposure_candidate_transitions.csv",transitions)]:
 if rows:
  with open(OUT/name,"w",newline="",encoding="utf8") as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0].keys()));w.writeheader();w.writerows(rows)
summary={"targets":len(targets),"candidate_rank":[{"src":k[0],"dst":k[1],"fid":k[2],"byte_offset":k[3],"matches":v} for k,v in best],
         "best_mapping":None if not best else {"src":best[0][0][0],"dst":best[0][0][1],"fid":best[0][0][2],"byte_offset":best[0][0][3],"matches":best[0][1]},
         "mapped_cases":sum(r["found"] for r in results),
         "exposure_ms":[r["exposure_after_D2_ms"] for r in results if r["exposure_after_D2_ms"] is not None]}
if summary["exposure_ms"]:
 x=sorted(summary["exposure_ms"]);summary["exposure_stats_ms"]={"min":min(x),"median":statistics.median(x),"mean":statistics.mean(x),"max":max(x),"positive_cases":sum(v>0 for v in x),"zero_cases":sum(v==0 for v in x)}
(OUT/"exposure_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf8")
(OUT/"exposure_report.md").write_text("# Targeted exposure audit\n\n"+json.dumps(summary,indent=2),encoding="utf8")
print(json.dumps(summary,indent=2))
