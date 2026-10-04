import io, json, math, os, random, re, statistics, time
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image
import imagehash
from datasets import load_dataset
from huggingface_hub import HfApi

SEED=20261004
TARGET=int(os.environ.get("TARGET_N","600"))
MIN_N=int(os.environ.get("MIN_N","500"))
MAX_PER_DEMO=int(os.environ.get("MAX_PER_DEMO","14"))
WORKERS=int(os.environ.get("WORKERS","6"))
PHASH_T=int(os.environ.get("PHASH_T","4"))
RAW=Path("wl_vp"); OUT=Path("out_vp"); OUT.mkdir(exist_ok=True)
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

def parse_candidates(s):
    out=[]
    for m in REC.finditer(str(s or "")):
        uid=m.group(1); body=m.group(2); f={}
        for fm in FIELD.finditer(body): f[fm.group(1).lower()]=norm(fm.group(2),2000)
        attrs={k.lower():norm(v,160) for k,_,v in KV.findall(f.get("attributes",""))}
        sem=tuple((k,attrs.get(k,"")) for k in ("role","type","name","aria-label","title","placeholder","alt","href","value","for") if attrs.get(k))
        out.append({"uid":uid,"tag":norm(f.get("tag",""),40),"text":norm(f.get("text",""),240),"sem":sem,"bbox":parse_bbox(f.get("bbox",""))})
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
            if r.status_code==429:
                time.sleep(min(45,2*(a+1)**2));continue
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

def state_screenshot(replay,idx):
    # WebLINX browser actions normally carry state.screenshot; nearest browser-state fallback is deterministic.
    if 0<=idx<len(replay):
        st=(replay[idx].get("state") or {})
        if st.get("screenshot"):return st["screenshot"]
    for delta in range(1,max(len(replay),2)):
        for j in (idx-delta,idx+delta):
            if 0<=j<len(replay):
                x=replay[j]
                if x.get("type")=="browser":
                    st=x.get("state") or {}
                    if st.get("screenshot"):return st["screenshot"]
    return None

def crop_hash(img,b):
    if b is None:return None,None
    x,y,w,h=b
    L=max(0,int(math.floor(x)));T=max(0,int(math.floor(y)))
    R=min(img.width,int(math.ceil(x+w)));B=min(img.height,int(math.ceil(y+h)))
    if R-L<3 or B-T<3:return None,None
    crop=img.crop((L,T,R,B)).convert("RGB")
    h=imagehash.phash(crop,hash_size=8)
    buf=io.BytesIO();crop.save(buf,format="PNG",optimize=True)
    return h,len(buf.getvalue())

def contains(b,px,py):
    if b is None:return False
    x,y,w,h=b
    return x<=px<=x+w and y<=py<=y+h

def summarize(rows,key):
    ns=[r[key] for r in rows]
    return {"n":len(ns),"unique_rate":sum(x==1 for x in ns)/len(ns),
            "collision_rate":sum(x>1 for x in ns)/len(ns),
            "median_candidates":statistics.median(ns),
            "p90_candidates":sorted(ns)[max(0,math.ceil(.9*len(ns))-1)],
            "mean_log2_candidates":sum(math.log2(max(1,x)) for x in ns)/len(ns)}

api=HfApi()
pre_sha=api.dataset_info("McGill-NLP/WebLINX").sha
raw_sha=api.dataset_info("McGill-NLP/WebLINX-full").sha
ds=load_dataset("McGill-NLP/WebLINX","chat",split="test_iid",revision=pre_sha)
pool=[]
for x in ds:
    uid=action_uid(x.get("action")); c=x.get("candidates")
    if not uid or not c:continue
    cs=parse_candidates(c); t=next((z for z in cs if z["uid"]==uid),None)
    if t is None or t["bbox"] is None or len(cs)<2:continue
    pool.append({"demo":str(x["demo"]),"turn":int(x["turn"]),"uid":uid,"cs":cs})

by=defaultdict(list)
for r in pool:by[r["demo"]].append(r)
rnd=random.Random(SEED); demos=sorted(by);rnd.shuffle(demos)
sel=[]
for d in demos:
    g=by[d][:];rnd.shuffle(g);sel.extend(g[:MAX_PER_DEMO])
    if len(sel)>=int(TARGET*1.25):break
sel=sel[:int(TARGET*1.25)]

# Headers
for d in sorted(set(r["demo"] for r in sel)):
    raw_get(f"demonstrations/{d}/replay.json",raw_sha)
replays={}
for d in sorted(set(r["demo"] for r in sel)):
    replays[d]=json.loads((RAW/f"demonstrations/{d}/replay.json").read_text())

for r in sel:r["screenshot"]=state_screenshot(replays[r["demo"]],r["turn"])
sel=[r for r in sel if r["screenshot"]]
paths=sorted(set(f'demonstrations/{r["demo"]}/screenshots/{r["screenshot"]}' for r in sel))
fail=Counter()
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    fut={ex.submit(raw_get,p,raw_sha):p for p in paths}
    for i,f in enumerate(as_completed(fut),1):
        try:f.result()
        except Exception as e:fail[type(e).__name__]+=1
        if i%100==0:print("SCREENSHOTS",i,"OF",len(paths))

rows=[]
for r in sel:
    if len(rows)>=TARGET:break
    sp=RAW/f'demonstrations/{r["demo"]}/screenshots/{r["screenshot"]}'
    if not sp.exists():continue
    try:
        with Image.open(sp) as im:
            im=im.convert("RGB")
            enriched=[]
            for c in r["cs"]:
                h,nbytes=crop_hash(im,c["bbox"]) if c["bbox"] is not None else (None,None)
                enriched.append({**c,"phash":h,"crop_bytes":nbytes})
    except Exception:
        continue
    target=next((c for c in enriched if c["uid"]==r["uid"]),None)
    if target is None or target["phash"] is None:continue
    text_n=sum(c["text"]==target["text"] for c in enriched)
    dom_n=sum((c["tag"],c["sem"])==(target["tag"],target["sem"]) for c in enriched)
    visual_n=sum(c["phash"] is not None and (c["phash"]-target["phash"])<=PHASH_T for c in enriched)
    joint_n=sum(c["phash"] is not None and c["text"]==target["text"] and (c["tag"],c["sem"])==(target["tag"],target["sem"]) and (c["phash"]-target["phash"])<=PHASH_T for c in enriched)
    x,y,w,h=target["bbox"]; px=x+w/2;py=y+h/2
    coord_n=sum(contains(c["bbox"],px,py) for c in enriched)
    rows.append({"demo":r["demo"],"turn":r["turn"],"candidates":len(enriched),
                 "text_n":text_n,"dom_n":dom_n,"visual_n":visual_n,"joint_n":joint_n,"coord_n":coord_n,
                 "blank":int(target["text"]==""),"crop_bytes":target["crop_bytes"] or 0})

if len(rows)<MIN_N:raise SystemExit(f"below minimum {len(rows)}")
summary={
 "dataset_pins":{"preprocessed":pre_sha,"raw":raw_sha},
 "n":len(rows),"demo_n":len(set(r["demo"] for r in rows)),"screenshots_n":len(paths),"fetch_failures":dict(fail),
 "universe":"WebLINX preprocessed top-candidate lists; target bbox crop from frozen raw screenshot",
 "phash_threshold":PHASH_T,
 "metrics":{k:summarize(rows,k+"_n") for k in ("text","dom","visual","joint","coord")},
 "blank_target_text_rate":sum(r["blank"] for r in rows)/len(rows),
 "median_target_crop_png_bytes":statistics.median(r["crop_bytes"] for r in rows),
 "rescue":{
   "text_amb_dom_unique":sum(r["text_n"]>1 and r["dom_n"]==1 for r in rows),
   "text_amb_visual_unique":sum(r["text_n"]>1 and r["visual_n"]==1 for r in rows),
   "dom_amb_text_unique":sum(r["dom_n"]>1 and r["text_n"]==1 for r in rows),
   "dom_amb_visual_unique":sum(r["dom_n"]>1 and r["visual_n"]==1 for r in rows),
   "visual_amb_dom_unique":sum(r["visual_n"]>1 and r["dom_n"]==1 for r in rows),
   "all_single_amb_joint_unique":sum(r["text_n"]>1 and r["dom_n"]>1 and r["visual_n"]>1 and r["joint_n"]==1 for r in rows)
 }
}
(OUT/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
print("VISUAL_PILOT_SUMMARY",json.dumps(summary,sort_keys=True))

# trigger-v1
