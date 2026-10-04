import json, os, random, re, math, statistics
from collections import Counter, defaultdict
from pathlib import Path
from datasets import load_dataset
from huggingface_hub import HfApi

SEED=20261004
TARGET=int(os.environ.get("TARGET_N","900"))
MAX_PER_DEMO=int(os.environ.get("MAX_PER_DEMO","22"))
OUT=Path("out_preflight"); OUT.mkdir(exist_ok=True)
WS=re.compile(r"\s+")
UID=re.compile(r"""uid\s*=\s*["']?([0-9a-zA-Z-]+)["']?""")
REC=re.compile(r"\(uid\s*=\s*([0-9a-zA-Z-]+)\)\s*(.*?)(?=(?:\(uid\s*=)|\Z)",re.S)
FIELD=re.compile(r"\[\[([a-zA-Z_]+)\]\]\s*(.*?)(?=(?:\[\[[a-zA-Z_]+\]\])|\Z)",re.S)
KV=re.compile(r"""([:\w-]+)\s*=\s*(['"])(.*?)\2""",re.S)

def norm(x,lim=240):
    return WS.sub(" ",str(x or "")).strip().lower()[:lim]

def parse_action_uid(a):
    m=UID.search(str(a or "")); return m.group(1) if m else None

def parse_candidates(s):
    out=[]
    for m in REC.finditer(str(s or "")):
        uid=m.group(1); body=m.group(2); f={}
        for fm in FIELD.finditer(body):
            f[fm.group(1).lower()]=norm(fm.group(2),1200)
        attrs={k.lower():norm(v,160) for k,_,v in KV.findall(f.get("attributes",""))}
        tag=norm(f.get("tag",""),40)
        text=norm(f.get("text",""),240)
        sem=tuple((k,attrs.get(k,"")) for k in ("role","type","name","aria-label","title","placeholder","alt","href","value","for") if attrs.get(k))
        out.append({"uid":uid,"tag":tag,"text":text,"sem":sem,"xpath":f.get("xpath",""),"bbox":f.get("bbox","")})
    return out

def metric(rows,key):
    ns=[r[key] for r in rows]
    return {
        "n":len(ns),
        "unique_rate":sum(x==1 for x in ns)/len(ns),
        "collision_rate":sum(x>1 for x in ns)/len(ns),
        "median_candidates":statistics.median(ns),
        "p90_candidates":sorted(ns)[max(0,math.ceil(.9*len(ns))-1)],
        "mean_log2_candidates":sum(math.log2(max(1,x)) for x in ns)/len(ns),
    }

api=HfApi()
sha=api.dataset_info("McGill-NLP/WebLINX").sha
ds=load_dataset("McGill-NLP/WebLINX","chat",split="test_iid",revision=sha)
rows=[]
for x in ds:
    uid=parse_action_uid(x.get("action"))
    if not uid or not x.get("candidates"): continue
    cs=parse_candidates(x["candidates"])
    target=next((c for c in cs if c["uid"]==uid),None)
    if target is None or len(cs)<2: continue
    text_n=sum(c["text"]==target["text"] for c in cs)
    tag_text_n=sum((c["tag"],c["text"])==(target["tag"],target["text"]) for c in cs)
    semdom_n=sum((c["tag"],c["sem"])==(target["tag"],target["sem"]) for c in cs)
    joint_n=sum((c["tag"],c["text"],c["sem"])==(target["tag"],target["text"],target["sem"]) for c in cs)
    rows.append({"demo":x["demo"],"turn":x["turn"],"n_candidates":len(cs),"text_n":text_n,"tag_text_n":tag_text_n,"semdom_n":semdom_n,"joint_n":joint_n,"blank":int(target["text"]=="")})

rnd=random.Random(SEED)
by=defaultdict(list)
for r in rows: by[r["demo"]].append(r)
demos=sorted(by); rnd.shuffle(demos)
sample=[]
for d in demos:
    g=by[d][:]
    rnd.shuffle(g)
    sample.extend(g[:MAX_PER_DEMO])
    if len(sample)>=TARGET: break
sample=sample[:TARGET]
if not sample: raise SystemExit("no sample")
summary={
 "dataset_sha":sha,"n":len(sample),"demo_n":len(set(r["demo"] for r in sample)),
 "candidate_list_note":"preprocessed WebLINX candidate lists; preflight only, not full-page universe",
 "median_candidate_list":statistics.median(r["n_candidates"] for r in sample),
 "blank_target_text_rate":sum(r["blank"] for r in sample)/len(sample),
 "metrics":{k:metric(sample,k+"_n") for k in ("text","tag_text","semdom","joint")},
 "rescue":{
   "text_collision_semdom_unique":sum(r["text_n"]>1 and r["semdom_n"]==1 for r in sample),
   "semdom_collision_text_unique":sum(r["semdom_n"]>1 and r["text_n"]==1 for r in sample),
   "both_single_collide_joint_unique":sum(r["text_n"]>1 and r["semdom_n"]>1 and r["joint_n"]==1 for r in sample),
 }
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
print("PREFLIGHT_SUMMARY",json.dumps(summary,sort_keys=True))
