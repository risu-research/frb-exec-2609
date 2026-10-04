import csv, json, math, os, random, re, statistics
from collections import Counter, defaultdict
from pathlib import Path
from datasets import load_dataset
from huggingface_hub import snapshot_download
from lxml import html as lhtml
from PIL import Image
import imagehash
import weblinx as wl

JOB="j-4c9e"; SEED=0x4C9E
TARGET_N=int(os.environ.get("TARGET_N","900"))
MIN_N=int(os.environ.get("MIN_N","500"))
MAX_PER_DEMO=int(os.environ.get("MAX_PER_DEMO","22"))
MAX_DEMOS=int(os.environ.get("MAX_DEMOS","72"))
PHASH_MAX=int(os.environ.get("PHASH_MAX","8"))
DATA_DIR=Path("wl_data"); OUT=Path("out"); OUT.mkdir(exist_ok=True)
UID_KEY="data-webtasks-id"
INTERACTIVE_TAGS={"a","button","input","select","textarea","option","summary","label"}
INTERACTIVE_ROLES={"button","link","menuitem","menuitemcheckbox","menuitemradio","checkbox","radio","tab","option","textbox","combobox","switch","slider","spinbutton","treeitem"}
DROP_ATTRS={UID_KEY,"id","class","style","xpath","data-testid","data-test","data-cy","data-reactid","nonce"}
SEM_ATTRS={"role","type","aria-label","aria-labelledby","aria-describedby","alt","title","placeholder","value","href","src","for","checked","selected","disabled","target"}
_ws=re.compile(r"\s+")

def norm(s,lim=180):
    if s is None:return ""
    return _ws.sub(" ",str(s)).strip().lower()[:lim]

def semantic_text(el):
    txt=norm(" ".join(el.itertext()),160)
    if txt:return txt
    for k in ("aria-label","alt","title","placeholder","value"):
        v=norm(el.attrib.get(k),160)
        if v:return v
    return ""

def text_sig(el): return (str(el.tag).lower(),semantic_text(el))

def clean_href(v):
    v=norm(v,180)
    return re.sub(r"[?#].*$","",v)[:120] if v else ""

def sem_attrs(el):
    pairs=[]
    for k,v in el.attrib.items():
        k2=str(k).lower()
        if k2 in DROP_ATTRS or (k2.startswith("data-") and k2 not in SEM_ATTRS): continue
        if k2 in SEM_ATTRS or k2.startswith("aria-"):
            vv=clean_href(v) if k2 in ("href","src") else norm(v,120)
            if vv:pairs.append((k2,vv))
    return tuple(sorted(pairs))

def local_dom_sig(el):
    p=el.getparent(); a=el.getprevious(); b=el.getnext()
    return (str(el.tag).lower(),semantic_text(el),sem_attrs(el),
            str(p.tag).lower() if p is not None else "",
            semantic_text(p)[:80] if p is not None else "",
            (str(a.tag).lower(),semantic_text(a)[:50]) if a is not None else ("",""),
            (str(b.tag).lower(),semantic_text(b)[:50]) if b is not None else ("",""))

def bbox_xywh(b):
    if not isinstance(b,dict):return None
    x=b.get("x",b.get("left")); y=b.get("y",b.get("top")); w=b.get("width"); h=b.get("height")
    try:x,y,w,h=float(x),float(y),float(w),float(h)
    except Exception:return None
    return (x,y,w,h) if w>1 and h>1 else None

def visible_bbox(b,vw,vh):
    q=bbox_xywh(b)
    if q is None:return False
    x,y,w,h=q
    return (x<vw and y<vh and x+w>0 and y+h>0) if vw and vh else True

def iou(a,b):
    aa=bbox_xywh(a); bb=bbox_xywh(b)
    if aa is None or bb is None:return 0.0
    ax,ay,aw,ah=aa; bx,by,bw,bh=bb
    x1=max(ax,bx);y1=max(ay,by);x2=min(ax+aw,bx+bw);y2=min(ay+ah,by+bh)
    inter=max(0,x2-x1)*max(0,y2-y1); union=aw*ah+bw*bh-inter
    return inter/union if union>0 else 0.0

def is_interactive(el):
    tag=str(el.tag).lower()
    if tag in INTERACTIVE_TAGS:return True
    if norm(el.attrib.get("role")) in INTERACTIVE_ROLES:return True
    if "onclick" in el.attrib:return True
    t=el.attrib.get("tabindex")
    return t is not None and str(t).strip() not in ("","-1")

def ancestor_of(a,b):
    p=b.getparent()
    while p is not None:
        if p is a:return True
        p=p.getparent()
    return False

def collapse_candidates(items,target_uid):
    used=set(); out=[]
    for i in range(len(items)):
        if i in used:continue
        group=[i]
        for j in range(i+1,len(items)):
            if j in used:continue
            ei,bi,_=items[i]; ej,bj,_=items[j]
            if (ancestor_of(ei,ej) or ancestor_of(ej,ei)) and iou(bi,bj)>=0.95:group.append(j)
        used.update(group)
        choose=next((j for j in group if items[j][2]==target_uid),None)
        if choose is None:
            inter=[j for j in group if is_interactive(items[j][0])]
            choose=inter[0] if inter else group[0]
        out.append(items[choose])
    return out

def crop_hash(img,b):
    q=bbox_xywh(b)
    if q is None:return None
    x,y,w,h=q
    L=max(0,int(math.floor(x)));T=max(0,int(math.floor(y)))
    R=min(img.width,int(math.ceil(x+w)));B=min(img.height,int(math.ceil(y+h)))
    if R-L<2 or B-T<2:return None
    return imagehash.phash(img.crop((L,T,R,B)).convert("RGB"),hash_size=16)

def groups(rows,key):
    d=defaultdict(list)
    for r in rows:d[r[key]].append(r)
    return d

def choose_demo_names():
    ds=load_dataset("McGill-NLP/WebLINX",split="validation")
    key="demo_name" if "demo_name" in ds.column_names else "demo"
    names=sorted(set(str(x) for x in ds[key]))
    rnd=random.Random(SEED);rnd.shuffle(names)
    return names[:MAX_DEMOS],len(names)

def download_headers(names):
    pats=[]
    for n in names:
        pats += [f"demonstrations/{n}/replay.json",f"demonstrations/{n}/metadata.json",f"demonstrations/{n}/form.json"]
    snapshot_download(repo_id="McGill-NLP/WebLINX-full",repo_type="dataset",local_dir=str(DATA_DIR),allow_patterns=pats)

def selected_turn_files(name,max_turns):
    demo=wl.Demonstration(name,base_dir=DATA_DIR/"demonstrations"); replay=wl.Replay.from_demonstration(demo)
    sel=[]
    for turn in replay:
        if len(sel)>=max_turns:break
        if turn.type!="browser" or not isinstance(turn.element,dict):continue
        uid=(turn.element.get("attributes") or {}).get(UID_KEY)
        state=turn.get("state") or {}; page=state.get("page"); shot=state.get("screenshot")
        if not uid or not page or not shot:continue
        nums=re.findall(r"\d+",str(page))
        if not nums:continue
        sel.append((turn.index,page,shot,f"bboxes-{nums[0]}.json"))
    return sel

def download_payload(names):
    chosen={}; pats=[]
    for n in names:
        try:ts=selected_turn_files(n,MAX_PER_DEMO)
        except Exception:continue
        if not ts:continue
        chosen[n]=ts
        for _,page,shot,bb in ts:
            pats += [f"demonstrations/{n}/pages/{page}",f"demonstrations/{n}/screenshots/{shot}",f"demonstrations/{n}/bboxes/{bb}"]
    snapshot_download(repo_id="McGill-NLP/WebLINX-full",repo_type="dataset",local_dir=str(DATA_DIR),allow_patterns=sorted(set(pats)))
    return chosen

def action_row(name,turn):
    attrs=(turn.element or {}).get("attributes") or {}; target_uid=attrs.get(UID_KEY)
    if not target_uid or turn.html is None or turn.bboxes is None:return None
    try:root=lhtml.fromstring(turn.html)
    except Exception:return None
    bboxes=turn.bboxes; vw=turn.viewport_width; vh=turn.viewport_height; elems=[]
    for el in root.xpath(f"//*[@{UID_KEY}]"):
        uid=el.attrib.get(UID_KEY); b=bboxes.get(uid)
        if uid and b is not None and visible_bbox(b,vw,vh):elems.append((el,b,uid))
    if not any(uid==target_uid for _,_,uid in elems):return None
    target_el=next(el for el,_,uid in elems if uid==target_uid); tt=str(target_el.tag).lower(); tx=semantic_text(target_el)
    filt=[]
    for el,b,uid in elems:
        if uid==target_uid or is_interactive(el) or str(el.tag).lower()==tt or (tx and semantic_text(el)==tx):filt.append((el,b,uid))
    filt=collapse_candidates(filt,target_uid)
    if len(filt)<2:return None
    ti=next((i for i,(_,_,uid) in enumerate(filt) if uid==target_uid),None)
    if ti is None:return None
    ts=[text_sig(el) for el,_,_ in filt]; ds=[local_dom_sig(el) for el,_,_ in filt]
    text_n=sum(1 for x in ts if x==ts[ti]); domset={i for i,x in enumerate(ds) if x==ds[ti]}; dom_n=len(domset)
    sp=turn.get_screenshot_path(throw_error=False)
    if not sp or not Path(sp).exists():return None
    try:
        with Image.open(sp) as im:hs=[crop_hash(im.convert("RGB"),b) for _,b,_ in filt]
    except Exception:return None
    th=hs[ti]
    if th is None:return None
    vset={i for i,h in enumerate(hs) if h is not None and (th-h)<=PHASH_MAX}; visual_n=len(vset)
    joint_n=len(domset & vset)
    return {"demo":name,"turn":turn.index,"intent":turn.intent,"candidates":len(filt),
            "text_n":text_n,"dom_n":dom_n,"visual_n":visual_n,"joint_n":joint_n,
            "text_unique":int(text_n==1),"dom_unique":int(dom_n==1),"visual_unique":int(visual_n==1),"joint_unique":int(joint_n==1),
            "dom_amb_visual_unique":int(dom_n>1 and visual_n==1),
            "visual_amb_dom_unique":int(visual_n>1 and dom_n==1),
            "both_amb_joint_unique":int(dom_n>1 and visual_n>1 and joint_n==1),
            "target_tag":tt,"target_text_empty":int(not bool(tx))}

def summarize(rows):
    out={"job":JOB,"n":len(rows),"phash_max":PHASH_MAX}
    for k in ("text","dom","visual","joint"):
        ns=[r[f"{k}_n"] for r in rows]
        out[k]={"unique_rate":sum(r[f"{k}_unique"] for r in rows)/len(rows) if rows else None,
                "collision_rate":sum(r[f"{k}_n"]>1 for r in rows)/len(rows) if rows else None,
                "median_candidates":statistics.median(ns) if ns else None,
                "mean_log2_candidates":sum(math.log2(x) for x in ns if x>0)/len(ns) if ns else None,
                "p90_candidates":sorted(ns)[max(0,math.ceil(.9*len(ns))-1)] if ns else None}
    out["complementarity"]={
        "dom_amb_visual_unique_rate":sum(r["dom_amb_visual_unique"] for r in rows)/len(rows) if rows else None,
        "visual_amb_dom_unique_rate":sum(r["visual_amb_dom_unique"] for r in rows)/len(rows) if rows else None,
        "both_amb_joint_unique_rate":sum(r["both_amb_joint_unique"] for r in rows)/len(rows) if rows else None}
    out["by_intent"]={str(key):{"n":len(g),**{f"{k}_collision":sum(r[f"{k}_n"]>1 for r in g)/len(g) for k in ("text","dom","visual","joint")}} for key,g in groups(rows,"intent").items()}
    out["by_target_text_empty"]={str(key):{"n":len(g),**{f"{k}_collision":sum(r[f"{k}_n"]>1 for r in g)/len(g) for k in ("text","dom","visual","joint")}} for key,g in groups(rows,"target_text_empty").items()}
    return out

def main():
    names,total=choose_demo_names(); download_headers(names); chosen=download_payload(names)
    rows=[]; errors=Counter()
    for n in names:
        if len(rows)>=TARGET_N:break
        try:
            demo=wl.Demonstration(n,base_dir=DATA_DIR/"demonstrations"); replay=wl.Replay.from_demonstration(demo)
            ids={x[0] for x in chosen.get(n,[])}; used=0
            for turn in replay:
                if len(rows)>=TARGET_N or used>=MAX_PER_DEMO:break
                if turn.index not in ids:continue
                try:row=action_row(n,turn)
                except Exception as e:errors[type(e).__name__]+=1;continue
                if row is not None:rows.append(row);used+=1
        except Exception as e:errors["demo_"+type(e).__name__]+=1
    if rows:
        with open(OUT/"actions.csv","w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    s=summarize(rows);s.update({"valid_demo_pool":total,"demos_requested":len(names),"demos_with_selected_turns":len(chosen),"demos_in_rows":len(set(r["demo"] for r in rows)),"errors":dict(errors),"threshold_ok":len(rows)>=MIN_N})
    with open(OUT/"summary.json","w",encoding="utf-8") as f:json.dump(s,f,indent=2,sort_keys=True)
    print(json.dumps(s,indent=2,sort_keys=True))
    if len(rows)<MIN_N:raise SystemExit(f"pilot below minimum: {len(rows)} < {MIN_N}")

if __name__=="__main__":main()
