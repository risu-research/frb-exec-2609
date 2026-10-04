import ast, json, math, os, random, re, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import imagehash
import numpy as np
import pandas as pd
import requests
from PIL import Image
from datasets import load_dataset
from huggingface_hub import HfApi

SEED=20261004
RNG=random.Random(SEED)
TARGET_N=int(os.environ.get("TARGET_N","600"))
MIN_N=int(os.environ.get("MIN_N","500"))
MAX_DEMOS=int(os.environ.get("MAX_DEMOS","32"))
MAX_PER_DEMO=int(os.environ.get("MAX_PER_DEMO","24"))
MAIN_VIS_T=4
VIS_THRESHOLDS=[0,4,8]
OUT=Path("out"); OUT.mkdir(exist_ok=True)
RAW=Path("wl_fast"); RAW.mkdir(exist_ok=True)

ACTION_UID_RE=re.compile(r"""uid\s*=\s*["']([^"']+)["']""")
INTENT_RE=re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(")
START_RE=re.compile(r"\(uid\s*=\s*([^)]+?)\)\s*\[\[tag\]\]\s*",re.S)
ATTR_RE=re.compile(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)=(?:'([^']*)'|"([^"]*)"|([^\s]+))""")
BBOX_RE=re.compile(r"x=(-?\d+(?:\.\d+)?)\s+y=(-?\d+(?:\.\d+)?)\s+width=(\d+(?:\.\d+)?)\s+height=(\d+(?:\.\d+)?)")
WS_RE=re.compile(r"\s+")
SEM_ATTRS={"role","type","name","aria-label","aria-labelledby","title","placeholder","alt","href","value","for","tabindex"}

def norm(s,lim=240):
    return WS_RE.sub(" ",str(s or "")).strip().lower()[:lim]

def action_uid(s):
    m=ACTION_UID_RE.search(str(s)); return m.group(1) if m else None

def action_intent(s):
    m=INTENT_RE.search(str(s).strip()); return m.group(1).lower() if m else "unknown"

def segment(body,start,end=None):
    i=body.find(start)
    if i<0: return ""
    i+=len(start)
    if end is None: return body[i:].strip()
    j=body.find(end,i)
    return body[i:j if j>=0 else None].strip()

def parse_attrs(s):
    out={}
    for m in ATTR_RE.finditer(s or ""):
        k=m.group(1).lower()
        v=next((x for x in m.groups()[1:] if x is not None),"")
        out[k]=norm(v,160)
    return out

def parse_candidates(s):
    if not isinstance(s,str) or "(uid" not in s: return []
    ms=list(START_RE.finditer(s)); out=[]
    for i,m in enumerate(ms):
        body=s[m.end(): ms[i+1].start() if i+1<len(ms) else len(s)]
        uid=m.group(1).strip().strip("'\"")
        tag=norm(segment(body,"", "[[xpath]]"),60)
        xpath=segment(body,"[[xpath]]","[[text]]")
        text=norm(segment(body,"[[text]]","[[bbox]]"),240)
        bbox_s=segment(body,"[[bbox]]","[[attributes]]")
        bm=BBOX_RE.search(bbox_s)
        if not bm: continue
        x,y,w,h=map(float,bm.groups())
        attrs=parse_attrs(segment(body,"[[attributes]]","[[children]]"))
        children=tuple(norm(x,40) for x in segment(body,"[[children]]").split()[:6])
        sem=[]
        for k in sorted(SEM_ATTRS):
            if k in attrs:
                v=attrs[k]
                if k=="href": v=v.split("#",1)[0].split("?",1)[0]
                sem.append((k,v))
        # excludes uid/id/class/style/xpath/text by construction
        dom=(tag,tuple(sem),children)
        out.append({"uid":uid,"tag":tag,"xpath":xpath,"text":text,"dom":dom,"x":x,"y":y,"w":w,"h":h})
    return out

def crop_hash(img,r):
    W,H=img.size; x,y,w,h=r["x"],r["y"],r["w"],r["h"]
    x0=max(0,int(math.floor(x))); y0=max(0,int(math.floor(y)))
    x1=min(W,int(math.ceil(x+w))); y1=min(H,int(math.ceil(y+h)))
    if x1-x0<3 or y1-y0<3: return None
    try:
        return int(str(imagehash.phash(img.crop((x0,y0,x1,y1)).convert("RGB"),hash_size=8)),16)
    except Exception:
        return None

def pdist(a,b):
    if a is None or b is None: return 999
    return (int(a)^int(b)).bit_count()

def xpath_related(a,b):
    a=(a or "").rstrip("/"); b=(b or "").rstrip("/")
    if not a or not b: return False
    return a==b or a.startswith(b+"/") or b.startswith(a+"/")

def collapse_branches(matches):
    n=len(matches)
    if n<=1: return n
    parent=list(range(n))
    def find(x):
        while parent[x]!=x:
            parent[x]=parent[parent[x]]; x=parent[x]
        return x
    def union(a,b):
        a=find(a); b=find(b)
        if a!=b: parent[b]=a
    for i in range(n):
        for j in range(i):
            if xpath_related(matches[i].get("xpath"),matches[j].get("xpath")):
                union(i,j)
    return len({find(i) for i in range(n)})

def count(records,t,mode,vt=MAIN_VIS_T,collapse=True):
    matches=[]
    for r in records:
        ok=False
        if mode=="text": ok=r["text"]==t["text"]
        elif mode=="dom": ok=r["dom"]==t["dom"]
        elif mode=="text_dom": ok=r["text"]==t["text"] and r["dom"]==t["dom"]
        elif mode in ("visual","joint"):
            if t["phash"] is not None and r["phash"] is not None:
                ar1=max(t["w"]/max(t["h"],1e-6),1e-6); ar2=max(r["w"]/max(r["h"],1e-6),1e-6)
                vok=abs(math.log2(ar1/ar2))<=math.log2(1.6) and pdist(r["phash"],t["phash"])<=vt
                ok=vok if mode=="visual" else (vok and r["text"]==t["text"] and r["dom"]==t["dom"])
        if ok: matches.append(r)
    return collapse_branches(matches) if collapse else len(matches)

def summ(df,col):
    s=df[col].dropna().astype(float)
    return {"n":int(len(s)),"unique_rate":float((s==1).mean()),"collision_rate":float((s>1).mean()),
            "median_candidates":float(s.median()),"p90_candidates":float(s.quantile(.9)),
            "mean_ambiguity_bits":float(np.log2(s.clip(lower=1)).mean())}

def local_path(rel):
    p=RAW/rel; p.parent.mkdir(parents=True,exist_ok=True); return p

def fetch_one(rel,sha):
    p=local_path(rel)
    if p.exists() and p.stat().st_size>0: return str(p)
    url=f"https://huggingface.co/datasets/McGill-NLP/WebLINX-full/resolve/{sha}/{quote(rel,safe='/')}?download=true"
    last=None
    for a in range(7):
        try:
            with requests.get(url,stream=True,timeout=(20,180),allow_redirects=True) as rr:
                rr.raise_for_status()
                tmp=p.with_suffix(p.suffix+".part")
                with open(tmp,"wb") as f:
                    for chunk in rr.iter_content(1024*1024):
                        if chunk: f.write(chunk)
                tmp.replace(p)
                return str(p)
        except Exception as e:
            last=e
            time.sleep(min(2**a,20))
    raise last

def load_replay(d,sha):
    rel=f"demonstrations/{d}/replay.json"; fetch_one(rel,sha)
    x=json.loads(local_path(rel).read_text())
    return x["data"] if isinstance(x,dict) and "data" in x else x

def screenshot_name(replay,t):
    # Official preprocessing can inherit the latest browser observation; emulate that conservatively.
    for k in range(min(t,len(replay)-1),-1,-1):
        state=(replay[k] or {}).get("state") or {}
        s=state.get("screenshot")
        if s: return s
    return None

def main():
    api=HfApi()
    pre_sha=api.dataset_info("McGill-NLP/WebLINX").sha
    raw_sha=api.dataset_info("McGill-NLP/WebLINX-full").sha
    print("PINS",json.dumps({"pre":pre_sha,"raw":raw_sha}))

    ds=load_dataset("McGill-NLP/WebLINX","chat",split="test_iid",revision=pre_sha)
    df=ds.to_pandas()
    df["uid"]=df["action"].map(action_uid); df["intent"]=df["action"].map(action_intent)
    e=df[df["uid"].notna() & df["candidates"].notna() & df["intent"].isin(["click","change","submit","textinput","hover","paste"])].copy()
    e["parsed"]=e["candidates"].map(parse_candidates)
    e["has_target"]=e.apply(lambda r:any(x["uid"]==r["uid"] for x in r["parsed"]),axis=1)
    e=e[e["has_target"] & e["parsed"].map(lambda x:len(x)>=2)].copy()
    print("ELIGIBLE",len(e),"DEMOS",e["demo"].nunique(),"CAND_MED",float(e["parsed"].map(len).median()))

    groups={d:g.copy() for d,g in e.groupby("demo")}
    demos=sorted(groups); RNG.shuffle(demos)
    selected=[]; rows_idx=[]
    for d in demos:
        inds=list(groups[d].index); RNG.shuffle(inds); inds=inds[:MAX_PER_DEMO]
        if len(inds)<3: continue
        selected.append(str(d)); rows_idx+=inds
        if len(rows_idx)>=TARGET_N*1.25 or len(selected)>=MAX_DEMOS: break
    RNG.shuffle(rows_idx)

    replay_cache={}
    for d in selected:
        try: replay_cache[d]=load_replay(d,raw_sha)
        except Exception as ex: print("REPLAY_FAIL",d,type(ex).__name__)

    work=[]
    for idx in rows_idx:
        if len(work)>=TARGET_N*1.12: break
        r=e.loc[idx]; d=str(r["demo"]); t=int(r["turn"])
        rp=replay_cache.get(d)
        if rp is None: continue
        sf=screenshot_name(rp,t)
        if not sf: continue
        rel=f"demonstrations/{d}/screenshots/{sf}"
        work.append((idx,rel))
    unique=sorted(set(rel for _,rel in work))
    print("SCREENSHOT_REQUESTS",len(unique),"WORK_ROWS",len(work))
    failures=Counter()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs={ex.submit(fetch_one,rel,raw_sha):rel for rel in unique}
        for f in as_completed(futs):
            try: f.result()
            except Exception as er: failures[type(er).__name__]+=1
    print("DOWNLOAD_FAILURES",dict(failures))

    out=[]; demo_counts=Counter(); skips=Counter()
    for idx,rel in work:
        if len(out)>=TARGET_N: break
        r=e.loc[idx]; d=str(r["demo"])
        if demo_counts[d]>=MAX_PER_DEMO: continue
        p=local_path(rel)
        if not p.exists(): skips["missing_screenshot"]+=1; continue
        try: img=Image.open(p).convert("RGB")
        except Exception: skips["bad_image"]+=1; continue
        recs=[dict(x) for x in r["parsed"]]
        for x in recs: x["phash"]=crop_hash(img,x)
        target=next((x for x in recs if x["uid"]==r["uid"]),None)
        if target is None: skips["target_missing"]+=1; continue
        if target["phash"] is None: skips["target_uncroppable"]+=1; continue
        z={"intent":str(r["intent"]),"candidate_n":len(recs),"text_blank":int(target["text"]=="")}
        for m in ["text","dom","visual","text_dom","joint"]:
            z[m]=count(recs,target,m,collapse=True)
            z[m+"_strict"]=count(recs,target,m,collapse=False)
        for vt in VIS_THRESHOLDS:
            z[f"visual_t{vt}"]=count(recs,target,"visual",vt)
            z[f"joint_t{vt}"]=count(recs,target,"joint",vt)
        out.append(z); demo_counts[d]+=1

    res=pd.DataFrame(out)
    print("ANALYZED",len(res),"DEMOS_ANALYZED",len(demo_counts),"SKIPS",dict(skips))
    if len(res)<MIN_N: raise RuntimeError(f"only {len(res)} analyzable rows")

    modes=["text","dom","visual","text_dom","joint"]
    mx=pd.DataFrame([{"representation":m,**summ(res,m)} for m in modes])
    mx.to_csv(OUT/"matrix.csv",index=False)
    bi=[]
    for intent,g in res.groupby("intent"):
        for m in modes: bi.append({"intent":intent,"representation":m,**summ(g,m)})
    pd.DataFrame(bi).to_csv(OUT/"by_intent.csv",index=False)
    sens=[]
    for vt in VIS_THRESHOLDS:
        for m in ("visual","joint"):
            sens.append({"threshold":vt,"representation":m,**summ(res,f"{m}_t{vt}")})
    pd.DataFrame(sens).to_csv(OUT/"sensitivity.csv",index=False)

    rescue={
      "n":int(len(res)),
      "text_collision_dom_unique":int(((res.text>1)&(res.dom==1)).sum()),
      "text_collision_visual_unique":int(((res.text>1)&(res.visual==1)).sum()),
      "dom_collision_text_unique":int(((res.dom>1)&(res.text==1)).sum()),
      "visual_collision_text_unique":int(((res.visual>1)&(res.text==1)).sum()),
      "all_single_collide_joint_unique":int(((res.text>1)&(res.dom>1)&(res.visual>1)&(res.joint==1)).sum()),
      "blank_target_text_rate":float(res.text_blank.mean()),
      "median_official_candidate_n":float(res.candidate_n.median()),
    }
    summary={"seed":SEED,"analyzed_n":int(len(res)),"demo_n":int(len(demo_counts)),
      "dataset_pins":{"WebLINX":pre_sha,"WebLINX-full":raw_sha},
      "universe":"official WebLINX preprocessed candidate panel; conservative lower bound on full-page collision",
      "representations":{"text":"normalized candidate visible text","dom":"tag + selected semantic/accessibility attrs + child tags; excludes uid/id/class/style/xpath/text","visual":"pHash of candidate bbox crop, Hamming<=4, aspect ratio <=1.6x","joint":"intersection of text+dom+visual"},
      "metrics":{m:summ(res,m) for m in modes},"rescue":rescue,
      "intent_counts":{str(k):int(v) for k,v in res.intent.value_counts().items()},
      "strict_metrics":{m:summ(res,m+"_strict") for m in modes},
      "download_failures":dict(failures),"skips":dict(skips)}
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
    print("PRIMARY_MATRIX\n"+mx.to_string(index=False))
    print("RESCUE",json.dumps(rescue,sort_keys=True))
    print("SUMMARY_JSON",json.dumps(summary,sort_keys=True))

if __name__=="__main__": main()
