import io,json,math,random,re,statistics,time
from collections import defaultdict,Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image
import imagehash
from huggingface_hub import HfApi,hf_hub_download
import weblinx as wl

SEED=2026100403
TARGET=600
OVERSAMPLE=750
MAX_PER_DEMO=14
PHASH_T=4
PHASH_TS=(0,4,8,12)
WORKERS=6
KS=(10,20,50)
RAW=Path("wl_confirm"); OUT=Path("out_confirm"); OUT.mkdir(exist_ok=True)
WS=re.compile(r"\s+")
FIELD=re.compile(r"\[\[([a-zA-Z_]+)\]\]\s*(.*?)(?=(?:\[\[[a-zA-Z_]+\]\])|\Z)",re.S)
KV=re.compile(r"""([:\w-]+)\s*=\s*(['"])(.*?)\2""",re.S)
NUM=re.compile(r"""(x|y|width|height)\s*=\s*(-?\d+(?:\.\d+)?)""")

def norm(x,lim=240): return WS.sub(" ",str(x or "")).strip().lower()[:lim]
def parse_bbox(s):
    d={k:float(v) for k,v in NUM.findall(str(s or ""))}
    if all(k in d for k in ("x","y","width","height")) and d["width"]>2 and d["height"]>2:
        return (d["x"],d["y"],d["width"],d["height"])
    return None
def parse_doc(doc,uid):
    f={}
    for fm in FIELD.finditer(str(doc or "")): f[fm.group(1).lower()]=norm(fm.group(2),2000)
    attrs={k.lower():norm(v,160) for k,_,v in KV.findall(f.get("attributes",""))}
    sem=tuple((k,attrs.get(k,"")) for k in ("role","type","name","aria-label","title","placeholder","alt","href","value") if attrs.get(k))
    return {"uid":str(uid),"tag":norm(f.get("tag",""),40),"text":norm(f.get("text",""),240),"sem":sem,"bbox":parse_bbox(f.get("bbox",""))}
def raw_get(repo_path,sha,optional=False):
    dest=RAW/repo_path
    if dest.exists() and dest.stat().st_size>0:return dest
    dest.parent.mkdir(parents=True,exist_ok=True)
    url=f"https://huggingface.co/datasets/McGill-NLP/WebLINX-full/resolve/{sha}/{quote(repo_path,safe='/')}?download=true"
    last=None
    for a in range(8):
        try:
            r=requests.get(url,stream=True,timeout=(25,180))
            if r.status_code==404 and optional:return None
            if r.status_code==429:time.sleep(min(45,2*(a+1)**2));continue
            r.raise_for_status(); tmp=dest.with_suffix(dest.suffix+".part")
            with open(tmp,"wb") as h:
                for chunk in r.iter_content(1024*1024):
                    if chunk:h.write(chunk)
            tmp.replace(dest);return dest
        except Exception as e:last=e;time.sleep(min(30,2**a))
    if optional:return None
    raise RuntimeError(f"fetch failed {repo_path}: {last}")
def crop_hash(im,b):
    if b is None:return None
    x,y,w,h=b;L=max(0,int(math.floor(x)));T=max(0,int(math.floor(y)))
    R=min(im.width,int(math.ceil(x+w)));B=min(im.height,int(math.ceil(y+h)))
    if R-L<3 or B-T<3:return None
    return imagehash.phash(im.crop((L,T,R,B)).convert("RGB"),hash_size=8)
def rate(rs,p): return sum(1 for r in rs if p(r))/len(rs) if rs else float("nan")
def metric(rs,key):
    vs=[r[key] for r in rs]
    return {"n":len(vs),"unique_rate":sum(v==1 for v in vs)/len(vs),"collision_rate":sum(v>1 for v in vs)/len(vs),
            "median":statistics.median(vs),"p90":sorted(vs)[max(0,math.ceil(.9*len(vs))-1)]}
def bootstrap(rows,reps=5000):
    by=defaultdict(list)
    for r in rows:by[r["demo"]].append(r)
    demos=sorted(by);rng=random.Random(2026100404); vals=defaultdict(list)
    for _ in range(reps):
        rs=[r for __ in demos for r in by[rng.choice(demos)]]
        b=[r for r in rs if r["blank"]]; n=[r for r in rs if not r["blank"]]
        q={"text_unique":rate(rs,lambda r:r["text_n"]==1),
           "visual_unique":rate(rs,lambda r:r["visual_n"]==1),
           "joint_unique":rate(rs,lambda r:r["joint_n"]==1),
           "semantic_unique":rate(rs,lambda r:r["textdom_n"]==1),
           "visual_escalation":rate(rs,lambda r:r["textdom_n"]>1),
           "blank_text_unique":rate(b,lambda r:r["text_n"]==1),
           "nonblank_text_unique":rate(n,lambda r:r["text_n"]==1),
           "blank_visual_unique":rate(b,lambda r:r["visual_n"]==1),
           "nonblank_visual_unique":rate(n,lambda r:r["visual_n"]==1),
           "blank_joint_unique":rate(b,lambda r:r["joint_n"]==1),
           "nonblank_joint_unique":rate(n,lambda r:r["joint_n"]==1)}
        q["text_inversion_gap"]=q["nonblank_text_unique"]-q["blank_text_unique"]
        for k,v in q.items():
            if not math.isnan(v):vals[k].append(v)
    b=[r for r in rows if r["blank"]];n=[r for r in rows if not r["blank"]]
    point={"text_unique":rate(rows,lambda r:r["text_n"]==1),"visual_unique":rate(rows,lambda r:r["visual_n"]==1),
           "joint_unique":rate(rows,lambda r:r["joint_n"]==1),"semantic_unique":rate(rows,lambda r:r["textdom_n"]==1),
           "visual_escalation":rate(rows,lambda r:r["textdom_n"]>1),
           "blank_text_unique":rate(b,lambda r:r["text_n"]==1),"nonblank_text_unique":rate(n,lambda r:r["text_n"]==1),
           "blank_visual_unique":rate(b,lambda r:r["visual_n"]==1),"nonblank_visual_unique":rate(n,lambda r:r["visual_n"]==1),
           "blank_joint_unique":rate(b,lambda r:r["joint_n"]==1),"nonblank_joint_unique":rate(n,lambda r:r["joint_n"]==1)}
    point["text_inversion_gap"]=point["nonblank_text_unique"]-point["blank_text_unique"]
    out={}
    for k,v in point.items():
        a=sorted(vals[k]);out[k]={"estimate":v,"ci95":[a[math.floor(.025*(len(a)-1))],a[math.ceil(.975*(len(a)-1))]]}
    return {"unit":"demo","reps":reps,"demo_n":len(demos),"metrics":out}

api=HfApi();raw_sha=api.dataset_info("McGill-NLP/WebLINX-full").sha
cand_path=hf_hub_download("McGill-NLP/WebLINX-full","candidates/test_iid.jsonl",repo_type="dataset",revision=raw_sha)

# Pass 1: official target-turn population, with no top-K conditioning.
# Freeze only groups with exactly one positive target; ambiguous/multi-positive groups
# are excluded before sampling rather than becoming post-hoc compute skips.
target_lists=defaultdict(list);group_sizes=Counter()
with open(cand_path,encoding="utf-8") as h:
    for line in h:
        z=json.loads(line);key=(str(z["demo_name"]),int(z["turn_index"]));group_sizes[key]+=1
        if int(z.get("label",0))==1:
            target_lists[key].append({"demo":key[0],"turn":key[1],"uid":str(z["uid"]),"rank":int(z["rank"])})
targets=[vs[0] for key,vs in target_lists.items() if len(vs)==1]
ambiguous_target_groups=sum(len(vs)!=1 for vs in target_lists.values())

by=defaultdict(list)
for r in targets:by[r["demo"]].append(r)
rng=random.Random(SEED); demos=sorted(by);rng.shuffle(demos);chosen=[]
for d in demos:
    g=by[d][:];rng.shuffle(g);chosen.extend(g[:MAX_PER_DEMO])
    if len(chosen)>=OVERSAMPLE:break
chosen=chosen[:OVERSAMPLE];chosen_keys={(r["demo"],r["turn"]) for r in chosen}

# Pass 2: collect only selected official records, dropping repeated query text.
records=defaultdict(list)
with open(cand_path,encoding="utf-8") as h:
    for line in h:
        z=json.loads(line);key=(str(z["demo_name"]),int(z["turn_index"]))
        if key in chosen_keys:
            records[key].append({"uid":str(z["uid"]),"doc":z["doc"],"rank":int(z["rank"]),"label":int(z.get("label",0))})

# Map replay turns to frozen screenshots.
for d in sorted({r["demo"] for r in chosen}):
    raw_get(f"demonstrations/{d}/replay.json",raw_sha)
    raw_get(f"demonstrations/{d}/metadata.json",raw_sha,optional=True)
    raw_get(f"demonstrations/{d}/form.json",raw_sha,optional=True)
replays={}
for d in sorted({r["demo"] for r in chosen}):
    replays[d]=wl.Replay.from_demonstration(wl.Demonstration(d,base_dir=RAW/"demonstrations"))
mapped=[];map_skips=Counter()
for r in chosen:
    try:
        turn=replays[r["demo"]][r["turn"]]
        if not turn.has_screenshot():replays[r["demo"]].assign_screenshot_to_turn(turn)
        ss=(turn.get("state") or {}).get("screenshot")
        if ss:mapped.append({**r,"screenshot":ss})
        else:map_skips["no_screenshot"]+=1
    except Exception as e:map_skips[type(e).__name__]+=1
sample=mapped[:TARGET]
paths=sorted(set(f'demonstrations/{r["demo"]}/screenshots/{r["screenshot"]}' for r in sample))
fail=Counter()
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    fut={ex.submit(raw_get,p,raw_sha):p for p in paths}
    for f in as_completed(fut):
        try:f.result()
        except Exception as e:fail[type(e).__name__]+=1

rows=[];skips=Counter()
for i,r in enumerate(sample,1):
    key=(r["demo"],r["turn"]);recs=records[key]
    sp=RAW/f'demonstrations/{r["demo"]}/screenshots/{r["screenshot"]}'
    if not sp.exists():skips["missing_screen"]+=1;continue
    try:
        with Image.open(sp) as im:
            im=im.convert("RGB"); cs=[]
            for z in recs:
                c=parse_doc(z["doc"],z["uid"]);c["rank"]=z["rank"];c["label"]=z["label"];c["phash"]=crop_hash(im,c["bbox"]);cs.append(c)
    except Exception as e:skips["image_"+type(e).__name__]+=1;continue
    ts=[c for c in cs if c["label"]==1]
    if len(ts)!=1:skips["target_count"]+=1;continue
    t=ts[0]
    if t["phash"] is None:skips["target_no_hash"]+=1;continue
    row={"demo":r["demo"],"turn":r["turn"],"target_rank":r["rank"],"candidate_n":len(cs),"blank":int(t["text"]=="")}
    row["text_n"]=sum(c["text"]==t["text"] for c in cs)
    row["dom_n"]=sum((c["tag"],c["sem"])==(t["tag"],t["sem"]) for c in cs)
    row["textdom_n"]=sum(c["text"]==t["text"] and (c["tag"],c["sem"])==(t["tag"],t["sem"]) for c in cs)
    row["visual_n"]=sum(c["phash"] is None or (c["phash"]-t["phash"])<=PHASH_T for c in cs)
    row["joint_n"]=sum(c["text"]==t["text"] and (c["tag"],c["sem"])==(t["tag"],t["sem"]) and (c["phash"] is None or (c["phash"]-t["phash"])<=PHASH_T) for c in cs)
    row["candidate_visual_valid_n"]=sum(c["phash"] is not None for c in cs)
    row["textdom_missing_visual_n"]=sum(c["text"]==t["text"] and (c["tag"],c["sem"])==(t["tag"],t["sem"]) and c["phash"] is None for c in cs)
    for pt in PHASH_TS:
        row[f"visual_t{pt}_n"]=sum(c["phash"] is None or (c["phash"]-t["phash"])<=pt for c in cs)
        row[f"joint_t{pt}_n"]=sum(c["text"]==t["text"] and (c["tag"],c["sem"])==(t["tag"],t["sem"]) and (c["phash"] is None or (c["phash"]-t["phash"])<=pt) for c in cs)
    for k in KS:
        sub=[c for c in cs if c["rank"]<=k]
        present=r["rank"]<=k
        row[f"k{k}_present"]=int(present)
        if present:
            row[f"k{k}_joint_n"]=sum(c["text"]==t["text"] and (c["tag"],c["sem"])==(t["tag"],t["sem"]) and (c["phash"] is None or (c["phash"]-t["phash"])<=PHASH_T) for c in sub)
    rows.append(row)
    if i%100==0:print("CONFIRM_PROCESSED",i)

blank=[r for r in rows if r["blank"]];nonblank=[r for r in rows if not r["blank"]]
sizes=[r["candidate_n"] for r in rows]
rankpop=[r["rank"] for r in targets]
def bootstrap_phash(rows,reps=5000):
    by=defaultdict(list)
    for r in rows: by[r["demo"]].append(r)
    demos=sorted(by); rng=random.Random(2026100405)
    vals={str(pt):{"visual":[],"joint":[]} for pt in PHASH_TS}
    for _ in range(reps):
        rs=[r for __ in demos for r in by[rng.choice(demos)]]
        for pt in PHASH_TS:
            vals[str(pt)]["visual"].append(rate(rs,lambda r,pt=pt:r[f"visual_t{pt}_n"]==1))
            vals[str(pt)]["joint"].append(rate(rs,lambda r,pt=pt:r[f"joint_t{pt}_n"]==1))
    out={}
    for pt in PHASH_TS:
        p=str(pt); out[p]={}
        for name in ("visual","joint"):
            a=sorted(vals[p][name])
            est=rate(rows,lambda r,pt=pt,name=name:r[f"{name}_t{pt}_n"]==1)
            out[p][name]={"estimate":est,"ci95":[a[math.floor(.025*(len(a)-1))],a[math.ceil(.975*(len(a)-1))]]}
    return {"unit":"demo","reps":reps,"demo_n":len(demos),"metrics":out}

phash_sensitivity={}
for pt in PHASH_TS:
    phash_sensitivity[str(pt)]={
      "overall":{
        "visual":metric(rows,f"visual_t{pt}_n"),
        "joint":metric(rows,f"joint_t{pt}_n")},
      "blank":{
        "visual":metric(blank,f"visual_t{pt}_n"),
        "joint":metric(blank,f"joint_t{pt}_n")},
      "nonblank":{
        "visual":metric(nonblank,f"visual_t{pt}_n"),
        "joint":metric(nonblank,f"joint_t{pt}_n")}
    }
phash_bootstrap=bootstrap_phash(rows)

summary={
 "raw_sha":raw_sha,
 "population":{"target_turns":len(targets),"ambiguous_target_groups_excluded":ambiguous_target_groups,"demo_n":len(by),
   "target_rank_coverage":{str(k):sum(x<=k for x in rankpop)/len(rankpop) for k in KS}},
 "sampling":{"oversampled":len(chosen),"mapped":len(mapped),"requested":TARGET,"analyzed":len(rows),
   "demo_n":len(set(r["demo"] for r in rows)),"map_skips":dict(map_skips),"compute_skips":dict(skips),"fetch_failures":dict(fail),
   "sample_target_rank_coverage":{str(k):sum(r["target_rank"]<=k for r in rows)/len(rows) for k in KS}},
 "candidate_universe":{"median":statistics.median(sizes),"p90":sorted(sizes)[max(0,math.ceil(.9*len(sizes))-1)],"min":min(sizes),"max":max(sizes)},
 "all_universe":{"text":metric(rows,"text_n"),"dom":metric(rows,"dom_n"),"textdom":metric(rows,"textdom_n"),"visual":metric(rows,"visual_n"),"joint":metric(rows,"joint_n"),
   "visual_escalation_rate":rate(rows,lambda r:r["textdom_n"]>1)},
 "protocol_audit":{
   "candidate_total":sum(r["candidate_n"] for r in rows),
   "candidate_visual_valid_total":sum(r["candidate_visual_valid_n"] for r in rows),
   "candidate_visual_valid_rate":sum(r["candidate_visual_valid_n"] for r in rows)/sum(r["candidate_n"] for r in rows),
   "actions_with_any_missing_candidate_visual":sum(r["candidate_visual_valid_n"]<r["candidate_n"] for r in rows),
   "actions_with_semantic_match_missing_visual":sum(r["textdom_missing_visual_n"]>0 for r in rows)
 },
 "strata":{
   "blank":{"n":len(blank),"text":metric(blank,"text_n"),"visual":metric(blank,"visual_n"),"joint":metric(blank,"joint_n"),"textdom":metric(blank,"textdom_n")},
   "nonblank":{"n":len(nonblank),"text":metric(nonblank,"text_n"),"visual":metric(nonblank,"visual_n"),"joint":metric(nonblank,"joint_n"),"textdom":metric(nonblank,"textdom_n")}},
 "bootstrap":bootstrap(rows),
 "phash_threshold":PHASH_T,
 "phash_sensitivity":phash_sensitivity,
 "phash_sensitivity_bootstrap":phash_bootstrap,
 "topk_unconditional":{str(k):{
    "target_present_rate":rate(rows,lambda r,k=k:r["target_rank"]<=k),
    "joint_unique_over_all_actions":sum((r["target_rank"]<=k and r.get(f"k{k}_joint_n")==1) for r in rows)/len(rows),
    "joint_unique_conditional_present":rate([r for r in rows if r["target_rank"]<=k],lambda r,k=k:r.get(f"k{k}_joint_n")==1)
 } for k in KS}
}
def jd(o):
    if hasattr(o,"item"):return o.item()
    raise TypeError(type(o).__name__)
(OUT/"confirm_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True,default=jd))
print("CONFIRM_SUMMARY",json.dumps(summary,sort_keys=True,default=jd))
