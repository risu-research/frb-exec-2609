import io,json,math,os,random,re,statistics,time
from collections import defaultdict,Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image
import imagehash
from datasets import load_dataset
from huggingface_hub import HfApi,hf_hub_download
import weblinx as wl

SEED=20261004
TARGET=600
MAX_PER_DEMO=14
WORKERS=6
PHASH_T=4
KS=(10,20,50)
RAW=Path("wl_audit"); OUT=Path("out_audit"); OUT.mkdir(exist_ok=True)
WS=re.compile(r"\s+")
UID=re.compile(r"""uid\s*=\s*["']?([0-9a-zA-Z-]+)["']?""")
REC=re.compile(r"\(uid\s*=\s*([0-9a-zA-Z-]+)\)\s*(.*?)(?=(?:\(uid\s*=)|\Z)",re.S)
FIELD=re.compile(r"\[\[([a-zA-Z_]+)\]\]\s*(.*?)(?=(?:\[\[[a-zA-Z_]+\]\])|\Z)",re.S)
KV=re.compile(r"""([:\w-]+)\s*=\s*(['"])(.*?)\2""",re.S)
NUM=re.compile(r"""(x|y|width|height)\s*=\s*(-?\d+(?:\.\d+)?)""")

def norm(x,lim=240): return WS.sub(" ",str(x or "")).strip().lower()[:lim]
def action_uid(a):
    m=UID.search(str(a or "")); return m.group(1) if m else None
def parse_bbox(s):
    d={k:float(v) for k,v in NUM.findall(str(s or ""))}
    if all(k in d for k in ("x","y","width","height")) and d["width"]>2 and d["height"]>2:
        return (d["x"],d["y"],d["width"],d["height"])
    return None
def parse_doc(doc,uid=None):
    f={}
    for fm in FIELD.finditer(str(doc or "")): f[fm.group(1).lower()]=norm(fm.group(2),2000)
    attrs={k.lower():norm(v,160) for k,_,v in KV.findall(f.get("attributes",""))}
    sem=tuple((k,attrs.get(k,"")) for k in ("role","type","name","aria-label","title","placeholder","alt","href","value") if attrs.get(k))
    return {"uid":str(uid or attrs.get("data-webtasks-id","")),"tag":norm(f.get("tag",""),40),
            "text":norm(f.get("text",""),240),"sem":sem,"bbox":parse_bbox(f.get("bbox",""))}
def parse_preprocessed(s):
    out=[]
    for m in REC.finditer(str(s or "")):
        z=parse_doc(m.group(2),m.group(1)); out.append(z)
    return out
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
            if r.status_code==429: time.sleep(min(45,2*(a+1)**2));continue
            r.raise_for_status()
            tmp=dest.with_suffix(dest.suffix+".part")
            with open(tmp,"wb") as h:
                for chunk in r.iter_content(1024*1024):
                    if chunk:h.write(chunk)
            tmp.replace(dest);return dest
        except Exception as e:
            last=e;time.sleep(min(30,2**a))
    if optional:return None
    raise RuntimeError(f"fetch failed {repo_path}: {last}")
def crop_hash(img,b):
    if b is None:return None
    x,y,w,h=b; L=max(0,int(math.floor(x)));T=max(0,int(math.floor(y)))
    R=min(img.width,int(math.ceil(x+w)));B=min(img.height,int(math.ceil(y+h)))
    if R-L<3 or B-T<3:return None
    return imagehash.phash(img.crop((L,T,R,B)).convert("RGB"),hash_size=8)
def smry(rows,key):
    vals=[r[key] for r in rows]
    return {"n":len(vals),"unique_rate":sum(v==1 for v in vals)/len(vals),
            "collision_rate":sum(v>1 for v in vals)/len(vals),
            "median":statistics.median(vals),
            "p90":sorted(vals)[max(0,math.ceil(.9*len(vals))-1)]}

api=HfApi(); pre_sha=api.dataset_info("McGill-NLP/WebLINX").sha; raw_sha=api.dataset_info("McGill-NLP/WebLINX-full").sha
ds=load_dataset("McGill-NLP/WebLINX","chat",split="test_iid",revision=pre_sha)
flow=Counter(total_chat_rows=len(ds))
pool=[]
for x in ds:
    uid=action_uid(x.get("action"))
    if not uid: continue
    flow["element_target_action"]+=1
    if not x.get("candidates"): continue
    flow["with_preprocessed_candidates"]+=1
    cs=parse_preprocessed(x["candidates"])
    if len(cs)>=2: flow["candidate_list_ge2"]+=1
    t=next((z for z in cs if z["uid"]==uid),None)
    if t is None: continue
    flow["target_in_preprocessed_list"]+=1
    if t["bbox"] is None: continue
    flow["target_with_valid_bbox"]+=1
    if len(cs)<2: continue
    pool.append({"demo":str(x["demo"]),"turn":int(x["turn"]),"uid":uid,"pre_uids":tuple(z["uid"] for z in cs)})
flow["pool"]=len(pool)

by=defaultdict(list)
for r in pool: by[r["demo"]].append(r)
rnd=random.Random(SEED); demos=sorted(by); rnd.shuffle(demos)
sel=[]
for d in demos:
    g=by[d][:]; rnd.shuffle(g); sel.extend(g[:MAX_PER_DEMO])
    if len(sel)>=int(TARGET*1.25): break
sel=sel[:int(TARGET*1.25)]
flow["oversample_before_visual_mapping"]=len(sel)
sample0=sel[:TARGET]
keys=set((r["demo"],r["turn"]) for r in sample0)

# Official DMR scores file: all filtered candidate elements, with explicit rank.
cand_path=hf_hub_download("McGill-NLP/WebLINX-full","candidates/test_iid.jsonl",repo_type="dataset",revision=raw_sha)
selected_records=defaultdict(list); target_ranks={}; all_group_sizes=Counter(); rank_counts=Counter(); target_turns=set()
with open(cand_path,"r",encoding="utf-8") as h:
    for line in h:
        z=json.loads(line); key=(str(z["demo_name"]),int(z["turn_index"]))
        all_group_sizes[key]+=1
        if int(z.get("label",0))==1:
            target_turns.add(key); target_ranks[key]=int(z["rank"])
        if key in keys:
            selected_records[key].append(z)
for rk in target_ranks.values():
    for k in KS:
        if rk<=k: rank_counts[f"target_rank_le_{k}"]+=1
rank_counts["target_turns"]=len(target_ranks)

# Validate the frozen top-10 set against official DMR top-10 for the selected sample.
pre_map={(r["demo"],r["turn"]):r for r in sample0}
set_matches=0; overlaps=[]; selected_rank_counts=Counter()
for key,recs in selected_records.items():
    official10={str(z["uid"]) for z in recs if int(z["rank"])<=10}
    pre=set(pre_map[key]["pre_uids"])
    if official10==pre:set_matches+=1
    overlaps.append(len(official10&pre)/max(1,len(official10|pre)))
    tr=target_ranks.get(key)
    if tr is not None:
        for k in KS:
            if tr<=k:selected_rank_counts[f"target_rank_le_{k}"]+=1

# Replay mapping and screenshots for the exact 600 frozen actions.
demo_names=sorted(set(d for d,_ in keys))
for d in demo_names:
    raw_get(f"demonstrations/{d}/replay.json",raw_sha)
    raw_get(f"demonstrations/{d}/metadata.json",raw_sha,optional=True)
    raw_get(f"demonstrations/{d}/form.json",raw_sha,optional=True)
replays={}
for d in demo_names:
    demo=wl.Demonstration(d,base_dir=RAW/"demonstrations")
    replays[d]=wl.Replay.from_demonstration(demo)
mapped=[]; map_skips=Counter()
for r in sample0:
    try:
        turn=replays[r["demo"]][r["turn"]]
        if not turn.has_screenshot(): replays[r["demo"]].assign_screenshot_to_turn(turn)
        ss=(turn.get("state") or {}).get("screenshot")
        if not ss: map_skips["no_screenshot"]+=1;continue
        mapped.append({**r,"screenshot":ss})
    except Exception as e: map_skips[type(e).__name__]+=1
flow["mapped_with_screenshot"]=len(mapped)
paths=sorted(set(f'demonstrations/{r["demo"]}/screenshots/{r["screenshot"]}' for r in mapped))
fail=Counter()
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    fut={ex.submit(raw_get,p,raw_sha):p for p in paths}
    for f in as_completed(fut):
        try:f.result()
        except Exception as e:fail[type(e).__name__]+=1
flow["unique_screenshot_paths"]=len(paths)
flow["screenshot_fetch_failures"]=sum(fail.values())

rows_by_k={str(k):[] for k in KS}; rows_by_k["all"]=[]
skip=Counter()
for i,r in enumerate(mapped,1):
    key=(r["demo"],r["turn"]); recs=selected_records.get(key,[])
    if not recs: skip["no_official_records"]+=1; continue
    sp=RAW/f'demonstrations/{r["demo"]}/screenshots/{r["screenshot"]}'
    if not sp.exists(): skip["missing_screenshot"]+=1;continue
    try:
        with Image.open(sp) as im:
            im=im.convert("RGB")
            parsed=[]
            for z in recs:
                c=parse_doc(z["doc"],z["uid"]); c["rank"]=int(z["rank"]); c["label"]=int(z.get("label",0)); c["phash"]=crop_hash(im,c["bbox"])
                parsed.append(c)
    except Exception as e:
        skip["image_"+type(e).__name__]+=1;continue
    targets=[c for c in parsed if c["label"]==1]
    if len(targets)!=1: skip["target_count"]+=1;continue
    target=targets[0]
    if target["phash"] is None: skip["target_no_hash"]+=1;continue
    for kval in list(KS)+["all"]:
        subset=parsed if kval=="all" else [c for c in parsed if c["rank"]<=kval]
        if not any(c["uid"]==target["uid"] for c in subset):
            rows_by_k[str(kval)].append({"demo":r["demo"],"target_present":0,"text_n":999999,"dom_n":999999,"textdom_n":999999,"visual_n":999999,"joint_n":999999})
            continue
        text_n=sum(c["text"]==target["text"] for c in subset)
        dom_n=sum((c["tag"],c["sem"])==(target["tag"],target["sem"]) for c in subset)
        textdom_n=sum(c["text"]==target["text"] and (c["tag"],c["sem"])==(target["tag"],target["sem"]) for c in subset)
        visual_n=sum(c["phash"] is None or (c["phash"]-target["phash"])<=PHASH_T for c in subset)
        joint_n=sum(c["text"]==target["text"] and (c["tag"],c["sem"])==(target["tag"],target["sem"]) and (c["phash"] is None or (c["phash"]-target["phash"])<=PHASH_T) for c in subset)
        rows_by_k[str(kval)].append({"demo":r["demo"],"target_present":1,"text_n":text_n,"dom_n":dom_n,"textdom_n":textdom_n,"visual_n":visual_n,"joint_n":joint_n})
    if i%100==0: print("PROCESSED",i)

universe={}
for k,rs in rows_by_k.items():
    present=[r for r in rs if r["target_present"]==1]
    universe[k]={
      "n":len(rs),"target_present_rate":len(present)/len(rs) if rs else 0,
      "candidate_size_median":statistics.median([all_group_sizes[(r["demo"], next(x["turn"] for x in sample0 if x["demo"]==r["demo"] and (x["demo"],x["turn"]) in selected_records))] for r in []]) if False else None,
      "text":smry(present,"text_n"),"dom":smry(present,"dom_n"),"textdom":smry(present,"textdom_n"),
      "visual":smry(present,"visual_n"),"joint":smry(present,"joint_n"),
      "visual_escalation_rate":sum(r["textdom_n"]>1 for r in present)/len(present) if present else None
    }

group_sizes=list(all_group_sizes.values())
summary={
 "dataset_pins":{"preprocessed":pre_sha,"raw":raw_sha},
 "sampling_flow":dict(flow),
 "official_population":{
   "target_turns":len(target_ranks),
   "candidate_group_n":len(all_group_sizes),
   "candidate_group_size":{"median":statistics.median(group_sizes),"p90":sorted(group_sizes)[max(0,math.ceil(.9*len(group_sizes))-1)],"min":min(group_sizes),"max":max(group_sizes)},
   "target_rank_coverage":{str(k):sum(r<=k for r in target_ranks.values())/len(target_ranks) for k in KS},
 },
 "selected_sample":{
   "n":len(sample0),"demo_n":len(set(r["demo"] for r in sample0)),
   "official_groups_found":len(selected_records),
   "official_top10_exact_set_match_rate":set_matches/len(sample0),
   "official_top10_mean_jaccard":sum(overlaps)/len(overlaps),
   "target_rank_coverage":{str(k):sum(target_ranks.get((r["demo"],r["turn"]),10**9)<=k for r in sample0)/len(sample0) for k in KS},
   "map_skips":dict(map_skips),"compute_skips":dict(skip),"fetch_failures":dict(fail)
 },
 "universe_sensitivity":universe,
}
def json_default(o):
    if hasattr(o,"item"): return o.item()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
(OUT/"universe_summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True,default=json_default))
print("UNIVERSE_SUMMARY",json.dumps(summary,sort_keys=True,default=json_default))
