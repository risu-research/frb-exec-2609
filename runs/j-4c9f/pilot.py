import json, math, os, random, re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
import imagehash
from lxml import html as lxml_html
from datasets import load_dataset
from huggingface_hub import HfApi, snapshot_download
import weblinx as wl

SEED = 20261004
RNG = random.Random(SEED)
TARGET_N = int(os.environ.get("TARGET_N", "900"))
MIN_N = int(os.environ.get("MIN_N", "500"))
MAX_DEMOS = int(os.environ.get("MAX_DEMOS", "60"))
MAX_PER_DEMO = int(os.environ.get("MAX_PER_DEMO", "22"))
VIS_THRESHOLDS = [0, 4, 8]
MAIN_VIS_T = 4
OUT = Path("out")
OUT.mkdir(exist_ok=True)
RAW_DIR = Path("wl_data")

UID_RE = re.compile(r"""uid\s*=\s*["']([^"']+)["']""")
INTENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(")
WS_RE = re.compile(r"\s+")
INTERACTIVE_TAGS = {"a","button","input","select","textarea","option","summary","label"}
INTERACTIVE_ROLES = {"button","link","checkbox","radio","menuitem","option","tab","textbox","combobox","switch","slider","spinbutton","treeitem"}
SEM_ATTRS = ("role","type","name","aria-label","aria-labelledby","title","placeholder","alt","href","value","for")

def norm_text(s):
    if s is None:
        return ""
    return WS_RE.sub(" ", str(s)).strip().lower()[:240]

def clean_attr(k, v):
    v = norm_text(v)
    if k == "href":
        v = v.split("#",1)[0].split("?",1)[0]
    return v[:160]

def bbox_tuple(b):
    if b is None:
        return None
    if isinstance(b, dict):
        try:
            return float(b.get("x",0)), float(b.get("y",0)), float(b.get("width",0)), float(b.get("height",0))
        except Exception:
            return None
    if isinstance(b, (list,tuple)) and len(b) >= 4:
        try:
            return tuple(map(float,b[:4]))
        except Exception:
            return None
    return None

def intersects_view(b, W, H):
    if not b:
        return False
    x,y,w,h = b
    if w < 3 or h < 3:
        return False
    return x < W and y < H and x+w > 0 and y+h > 0

def crop_hash(img, b):
    x,y,w,h = b
    W,H = img.size
    x0=max(0,int(math.floor(x))); y0=max(0,int(math.floor(y)))
    x1=min(W,int(math.ceil(x+w))); y1=min(H,int(math.ceil(y+h)))
    if x1-x0 < 3 or y1-y0 < 3:
        return None
    crop=img.crop((x0,y0,x1,y1)).convert("RGB")
    try:
        hsh=imagehash.phash(crop, hash_size=8)
        return int(str(hsh),16)
    except Exception:
        return None

def phash_dist(a,b):
    if a is None or b is None:
        return 999
    return (int(a)^int(b)).bit_count()

def element_text(el):
    try:
        return norm_text(" ".join(el.itertext()))
    except Exception:
        return ""

def dom_signature(el):
    tag = (el.tag or "").lower() if isinstance(el.tag, str) else ""
    parent = el.getparent()
    ptag = (parent.tag or "").lower() if parent is not None and isinstance(parent.tag,str) else ""
    role = norm_text(el.attrib.get("role",""))
    attrs=[]
    for k in SEM_ATTRS:
        if k in el.attrib:
            v=clean_attr(k,el.attrib.get(k,""))
            if v:
                attrs.append((k,v))
    child_tags=[]
    for c in list(el)[:6]:
        if isinstance(c.tag,str):
            child_tags.append(c.tag.lower())
    depth=0
    p=parent
    while p is not None and depth < 20:
        depth += 1
        p=p.getparent()
    return (tag, ptag, role, tuple(attrs), tuple(child_tags), min(depth//3,5))

def is_interactive(el):
    tag=(el.tag or "").lower() if isinstance(el.tag,str) else ""
    if tag in INTERACTIVE_TAGS:
        return True
    role=norm_text(el.attrib.get("role",""))
    if role in INTERACTIVE_ROLES:
        return True
    if "onclick" in el.attrib:
        return True
    tabindex=el.attrib.get("tabindex")
    try:
        if tabindex is not None and int(tabindex) >= 0:
            return True
    except Exception:
        pass
    return False

def is_related(a,b):
    if a is b:
        return True
    try:
        p=a.getparent()
        while p is not None:
            if p is b:
                return True
            p=p.getparent()
        p=b.getparent()
        while p is not None:
            if p is a:
                return True
            p=p.getparent()
    except Exception:
        pass
    return False

def parse_uid(action):
    m=UID_RE.search(str(action))
    return m.group(1) if m else None

def parse_intent(action):
    m=INTENT_RE.search(str(action).strip())
    return m.group(1).lower() if m else "unknown"

def count_matches(records, target, mode, vis_t=MAIN_VIS_T, collapse_related=True, interactive_only=False):
    def match(r):
        if mode == "text":
            return r["text"] == target["text"]
        if mode == "dom":
            return r["dom"] == target["dom"]
        if mode == "visual":
            if target["phash"] is None or r["phash"] is None:
                return False
            ar1=max(target["w"]/max(target["h"],1e-6),1e-6)
            ar2=max(r["w"]/max(r["h"],1e-6),1e-6)
            if abs(math.log2(ar1/ar2)) > math.log2(1.6):
                return False
            return phash_dist(r["phash"],target["phash"]) <= vis_t
        if mode == "text_dom":
            return r["text"]==target["text"] and r["dom"]==target["dom"]
        if mode == "joint":
            if r["text"]!=target["text"] or r["dom"]!=target["dom"]:
                return False
            if target["phash"] is None or r["phash"] is None:
                return False
            ar1=max(target["w"]/max(target["h"],1e-6),1e-6)
            ar2=max(r["w"]/max(r["h"],1e-6),1e-6)
            if abs(math.log2(ar1/ar2)) > math.log2(1.6):
                return False
            return phash_dist(r["phash"],target["phash"]) <= vis_t
        raise ValueError(mode)
    matches=[]
    for r in records:
        if interactive_only and not r["interactive"] and r is not target:
            continue
        if match(r):
            matches.append(r)
    if not collapse_related:
        return len(matches)
    unrelated=[r for r in matches if not is_related(r["el"],target["el"])]
    family_any=any(is_related(r["el"],target["el"]) for r in matches)
    return (1 if family_any else 0) + len(unrelated)

def page_records(turn):
    if not (turn.has_screenshot() and turn.has_html() and turn.has_bboxes()):
        return None
    if turn.get_screenshot_status() not in (None,"good"):
        return None
    sp=turn.get_screenshot_path(throw_error=False)
    if not sp or not Path(sp).exists():
        return None
    try:
        img=Image.open(sp).convert("RGB")
    except Exception:
        return None
    W,H=img.size
    try:
        root=lxml_html.fromstring(turn.html)
        bboxes=turn.bboxes
    except Exception:
        return None
    uidmap={}
    for el in root.iter():
        if not isinstance(el.tag,str):
            continue
        uid=el.attrib.get("data-webtasks-id")
        if uid:
            uidmap[uid]=el
    recs=[]
    for uid,el in uidmap.items():
        b=bbox_tuple(bboxes.get(uid) if isinstance(bboxes,dict) else None)
        if not intersects_view(b,W,H):
            continue
        x,y,w,h=b
        recs.append({
            "uid":uid, "el":el, "text":element_text(el), "dom":dom_signature(el),
            "phash":crop_hash(img,b), "interactive":is_interactive(el),
            "x":x,"y":y,"w":w,"h":h,
        })
    return recs, {r["uid"]:r for r in recs}, (W,H), str(sp)

def summarize(df, col):
    s=df[col].dropna().astype(float)
    if len(s)==0:
        return {}
    return {
        "n":int(len(s)),
        "unique_rate":float((s==1).mean()),
        "collision_rate":float((s>1).mean()),
        "median_candidates":float(s.median()),
        "p90_candidates":float(s.quantile(.9)),
        "mean_ambiguity_bits":float(np.log2(s.clip(lower=1)).mean()),
    }

def main():
    api=HfApi()
    pre_sha=api.dataset_info("McGill-NLP/WebLINX").sha
    raw_sha=api.dataset_info("McGill-NLP/WebLINX-full").sha
    print("DATASET_PINS", json.dumps({"preprocessed_sha":pre_sha,"raw_sha":raw_sha}))

    ds=load_dataset("McGill-NLP/WebLINX","chat",split="test_iid",revision=pre_sha)
    pdf=ds.to_pandas()
    pdf["uid"]=pdf["action"].map(parse_uid)
    pdf["intent"]=pdf["action"].map(parse_intent)
    eligible=pdf[pdf["uid"].notna() & pdf["intent"].isin(["click","change","submit","hover","textinput","paste"])].copy()
    print("PREPROCESSED_ROWS", len(pdf), "ELEMENT_TARGET_ROWS", len(eligible), "DEMOS", eligible["demo"].nunique())

    groups={d:g.copy() for d,g in eligible.groupby("demo")}
    demos=sorted(groups)
    RNG.shuffle(demos)
    selected=[]; approx=0
    for d in demos:
        n=min(len(groups[d]),MAX_PER_DEMO)
        if n < 2:
            continue
        selected.append(d); approx += n
        if approx >= TARGET_N*1.35 or len(selected)>=MAX_DEMOS:
            break
    if not selected:
        raise RuntimeError("No demos selected")
    print("SELECTED_DEMOS",len(selected),"APPROX_ROWS",approx)

    patterns=[]
    for d in selected:
        base=f"demonstrations/{d}"
        patterns += [f"{base}/replay.json",f"{base}/metadata.json",f"{base}/form.json",f"{base}/screenshots/*",f"{base}/pages/*",f"{base}/bboxes/*"]
    snapshot_download("McGill-NLP/WebLINX-full",repo_type="dataset",revision=raw_sha,local_dir=str(RAW_DIR),allow_patterns=patterns)

    chosen_rows=[]
    for d in selected:
        inds=list(groups[d].index)
        RNG.shuffle(inds)
        chosen_rows.extend(inds[:MAX_PER_DEMO])
    RNG.shuffle(chosen_rows)

    cache={}
    rows=[]
    per_demo=Counter()
    skip_types=Counter()
    for idx in chosen_rows:
        if len(rows)>=TARGET_N:
            break
        r=eligible.loc[idx]
        d=str(r["demo"]); t=int(r["turn"]); uid=str(r["uid"]); intent=str(r["intent"])
        if per_demo[d] >= MAX_PER_DEMO:
            continue
        try:
            demo=wl.Demonstration(d,base_dir=RAW_DIR/"demonstrations")
            replay=wl.Replay.from_demonstration(demo)
            turn=replay[t]
            if not turn.has_screenshot():
                replay.assign_screenshot_to_turn(turn)
            if not turn.has_html():
                replay.assign_html_path_to_turn(turn)
            key=(turn.get_screenshot_path(throw_error=False),turn.get_html_path(throw_error=False),turn.get_bboxes_path(throw_error=False))
            if key not in cache:
                cache[key]=page_records(turn)
            pr=cache[key]
            if pr is None:
                skip_types["page_records_none"] += 1
                continue
            recs,byuid,(W,H),sp=pr
            target=byuid.get(uid)
            if target is None:
                skip_types["target_not_visible"] += 1
                continue
            if target["phash"] is None:
                skip_types["target_no_visual_hash"] += 1
                continue
            outrow={"turn":t,"intent":intent,"n_visible_uid":len(recs),"target_text_blank":int(target["text"]=="")}
            for interactive_only,suffix in [(False,""),(True,"_i")]:
                for collapse,sfx2 in [(True,""),(False,"_strict")]:
                    for mode in ["text","dom","visual","text_dom","joint"]:
                        outrow[f"{mode}{suffix}{sfx2}"]=count_matches(recs,target,mode,MAIN_VIS_T,collapse_related=collapse,interactive_only=interactive_only)
            for vt in VIS_THRESHOLDS:
                outrow[f"visual_t{vt}"]=count_matches(recs,target,"visual",vt,collapse_related=True)
                outrow[f"joint_t{vt}"]=count_matches(recs,target,"joint",vt,collapse_related=True)
            rows.append(outrow)
            per_demo[d]+=1
        except Exception as e:
            skip_types[type(e).__name__] += 1
            continue

    res=pd.DataFrame(rows)
    print("ANALYZED",len(res),"DEMOS_ANALYZED",len(per_demo),"INTENTS",dict(res["intent"].value_counts()) if len(res) else {})
    print("SKIPS", dict(skip_types))
    if len(res) < MIN_N:
        raise RuntimeError(f"Insufficient analyzable rows: {len(res)} < {MIN_N}")

    modes=["text","dom","visual","text_dom","joint"]
    matrix=[]
    for m in modes:
        s=summarize(res,m); s["representation"]=m; matrix.append(s)
    matrix_df=pd.DataFrame(matrix)[["representation","n","unique_rate","collision_rate","median_candidates","p90_candidates","mean_ambiguity_bits"]]
    matrix_df.to_csv(OUT/"matrix.csv",index=False)

    by_int=[]
    for intent,g in res.groupby("intent"):
        for m in modes:
            s=summarize(g,m); s["intent"]=intent; s["representation"]=m; by_int.append(s)
    pd.DataFrame(by_int).to_csv(OUT/"by_intent.csv",index=False)

    sens=[]
    for vt in VIS_THRESHOLDS:
        for m in [f"visual_t{vt}",f"joint_t{vt}"]:
            s=summarize(res,m); s["threshold"]=vt; s["representation"]=m.split("_t")[0]; sens.append(s)
    pd.DataFrame(sens).to_csv(OUT/"sensitivity.csv",index=False)

    rescue={
        "n":int(len(res)),
        "text_collision":int((res["text"]>1).sum()),
        "dom_collision":int((res["dom"]>1).sum()),
        "visual_collision":int((res["visual"]>1).sum()),
        "joint_collision":int((res["joint"]>1).sum()),
        "text_collision_dom_unique":int(((res["text"]>1)&(res["dom"]==1)).sum()),
        "text_collision_visual_unique":int(((res["text"]>1)&(res["visual"]==1)).sum()),
        "dom_collision_text_unique":int(((res["dom"]>1)&(res["text"]==1)).sum()),
        "visual_collision_text_unique":int(((res["visual"]>1)&(res["text"]==1)).sum()),
        "all_single_modalities_collide_joint_unique":int(((res["text"]>1)&(res["dom"]>1)&(res["visual"]>1)&(res["joint"]==1)).sum()),
        "text_blank_rate":float(res["target_text_blank"].mean()),
        "median_visible_uid_elements":float(res["n_visible_uid"].median()),
    }

    summary={
        "seed":SEED,
        "target_n":TARGET_N,
        "analyzed_n":int(len(res)),
        "demo_n":int(len(per_demo)),
        "dataset_pins":{"McGill-NLP/WebLINX":pre_sha,"McGill-NLP/WebLINX-full":raw_sha},
        "primary_universe":"visible data-webtasks-id elements; ancestor/descendant target-family collapsed to one operational branch",
        "representations":{
            "text":"normalized visible element text",
            "dom":"tag + selected semantic/accessibility attributes + parent tag/role + shallow child tags + depth bucket; excludes uid/id/class/style and visible text",
            "visual":"64-bit perceptual hash of target crop, Hamming<=4, aspect ratio within 1.6x",
            "joint":"intersection of text, DOM, and visual criteria"
        },
        "metrics":{m:summarize(res,m) for m in modes},
        "rescue":rescue,
        "intent_counts":{str(k):int(v) for k,v in res["intent"].value_counts().items()},
        "strict_element_metrics":{m:summarize(res,m+"_strict") for m in modes},
        "interactive_heuristic_metrics":{m:summarize(res,m+"_i") for m in modes},
        "skip_types":dict(skip_types),
    }
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True))
    print("PRIMARY_MATRIX")
    print(matrix_df.to_string(index=False))
    print("RESCUE",json.dumps(rescue,sort_keys=True))
    print("SUMMARY_JSON",json.dumps(summary,sort_keys=True))

if __name__=="__main__":
    main()
