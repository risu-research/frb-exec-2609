#!/usr/bin/env python3
"""Public-site cookie consent audit. No logins, no form submission, no stored cookie values."""
import json,re,time,os
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

SITES=["coursera.org","npr.org","stackoverflow.blog","etsy.com","orange.fr"]
TRACKERS=("doubleclick.net","google-analytics.com","googlesyndication.com",
"facebook.net","criteo.com","taboola.com","outbrain.com","hotjar.com",
"scorecardresearch.com","quantserve.com","mixpanel.com","amplitude.com",
"bat.bing.com","analytics.tiktok.com")
REJECT=[r"reject( all)?( cookies)?",r"decline( all)?( cookies)?",
r"refuse( all)?( cookies)?",r"deny( all)?( cookies)?",
r"(use |allow |only )?(strictly )?(necessary|essential)( cookies)?( only)?",
r"continue without accepting",r"tout refuser",r"alle ablehnen"]
SETTINGS=[r"(manage|change|customize|customise|edit) (cookie )?(preferences|settings|choices)",
r"(cookie|privacy) settings",r"manage options",r"more options"]
def utc():return datetime.now(timezone.utc).isoformat()
def norm(x):return " ".join((x or "").split()).strip()
def ismatch(x,rxs):return any(re.fullmatch(y,norm(x),re.I) for y in rxs)
def host(url):return (urlsplit(url).hostname or "").lower()
def registrable(x):
    p=(x or "").split(".")
    if len(p)>2 and ".".join(p[-2:]) in ("co.uk","com.au","co.jp"):return ".".join(p[-3:])
    return ".".join(p[-2:])
def tracker(x):return any(x==s or x.endswith("."+s) for s in TRACKERS)
def status(page):
    try:
        body=page.locator("body").inner_text(timeout=2500)[:12000]
    except Exception:body=""
    try:
        banner=page.locator("#onetrust-banner-sdk, #CybotCookiebotDialog, #didomi-host, .cky-consent-container, .cmplz-cookiebanner, [aria-label*='cookie' i]").count()>0
    except Exception:banner=False
    return {"banner_dom":banner,"ack_text":bool(re.search(r"(preferences|settings|consent|choice).{0,55}(saved|updated|recorded)|cookies.{0,40}(rejected|declined)",body,re.I))}
def buttons(page):
    found=[]
    for fr in page.frames:
        try:
            loc=fr.locator('button, [role="button"], input[type="button"], input[type="submit"]')
            for i in range(min(90,loc.count())):
                el=loc.nth(i)
                try:
                    if not el.is_visible(timeout=400):continue
                    label=norm(el.get_attribute("aria-label",timeout=400) or el.get_attribute("value",timeout=400) or el.inner_text(timeout=400))
                    if label:found.append((el,label[:120]))
                except Exception:pass
        except Exception:pass
    return found
def click_unique(page,patterns):
    match=[(el,label) for el,label in buttons(page) if ismatch(label,patterns)]
    if len(match)!=1:return False,("none" if not match else "ambiguous"),[s for _,s in match]
    el,label=match[0]
    try:
        el.click(timeout=2500)
        return True,label,[label]
    except Exception as exc:return False,"click_error:"+type(exc).__name__,[label]
def tcf(page):
    try:
        return page.evaluate("""async()=> {
          if(typeof window.__tcfapi!=='function')return {present:false};
          return await Promise.race([
            new Promise(resolve=>{try{window.__tcfapi('getTCData',2,(x,ok)=>resolve({
              present:true,ok:!!ok,
              purpose_granted:Object.values(x?.purpose?.consents||{}).filter(Boolean).length,
              vendor_granted:Object.values(x?.vendor?.consents||{}).filter(Boolean).length
            }))}catch(e){resolve({present:true,error:true})}}),
            new Promise(resolve=>setTimeout(()=>resolve({present:true,timeout:true}),1200))]);
        }""")
    except Exception:return {"present":False,"error":True}
def measure(browser,site,arm,out):
    ctx=browser.new_context(locale="en-US",timezone_id="America/New_York",viewport={"width":1280,"height":800})
    page=ctx.new_page();events=[];stage=["initial"]
    page.on("request",lambda req: events.append({"phase":stage[0],"host":host(req.url),"kind":req.resource_type}))
    result={"site":site,"arm":arm,"utc":utc(),"attempted":True,"reject_clicked":False,"error":None}
    try:
        res=page.goto("https://"+site,wait_until="domcontentloaded",timeout=18000)
        result["status"]=res.status if res else None
        if res and res.status>=400:raise RuntimeError("HTTP_"+str(res.status))
        page.wait_for_timeout(2200)
        result["initial_status"]=status(page)
        initial_buttons=[label for _,label in buttons(page)]
        result["initial_buttons"]=initial_buttons[:35]
        print("BUTTONS",site,arm,initial_buttons[:35],flush=True)
        result["banner_visible"]=bool(result["initial_status"]["banner_dom"] or any(ismatch(z,REJECT+SETTINGS) or "cookie" in z.lower() for z in initial_buttons))
        result["tcf_initial"]=tcf(page)
        result["cookies_initial"]=[{"name":c["name"],"domain":c["domain"]} for c in ctx.cookies()]
        if arm=="reject":
            ok,how,matches=click_unique(page,REJECT)
            result["direct_reject"]={"clicked":ok,"label":how,"candidates":matches}
            if not ok and how=="none" and result["banner_visible"]:
                settings,slab,_=click_unique(page,SETTINGS)
                result["settings_click"]={"clicked":settings,"label":slab}
                if settings:
                    page.wait_for_timeout(900)
                    ok,how,matches=click_unique(page,REJECT)
                    result["nested_reject"]={"clicked":ok,"label":how,"candidates":matches}
            result["reject_clicked"]=ok
            print("CLICK_DIAGNOSTIC",site,ok,how,"settings",result.get("settings_click"),flush=True)
            if ok:page.wait_for_timeout(1600)
            result["post_action_status"]=status(page)
        stage[0]="reload"
        page.reload(wait_until="domcontentloaded",timeout=18000)
        page.wait_for_timeout(2300)
        result["tcf_reload"]=tcf(page)
        result["cookies_reload"]=[{"name":c["name"],"domain":c["domain"]} for c in ctx.cookies()]
        result["post_reload_status"]=status(page)
        origin=registrable(host(page.url))
        reload_hosts=sorted(set(x["host"] for x in events if x["phase"]=="reload" and x["host"] and registrable(x["host"])!=origin))
        result["cross_site_hosts_reload"]=reload_hosts
        result["tracker_candidates_reload"]=[x for x in reload_hosts if tracker(x)]
        result["request_count_reload"]=sum(x["phase"]=="reload" for x in events)
        try:
            out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/(site.replace(".","_")+"_"+arm+"_reload.png")),timeout=5000)
        except Exception:pass
    except Exception as exc:result["error"]=type(exc).__name__+":"+str(exc).splitlines()[0][:100]
    finally:
        if result["error"]:
            result["user_notice"]="접속 또는 관찰이 실패했습니다. 거부 적용 여부는 확인되지 않았습니다."
        elif not result["reject_clicked"] and arm=="reject":
            result["user_notice"]="명확한 거부 동작을 실행하지 못했습니다. 수락하지 않았으며 거부 적용 여부는 미확인입니다."
        elif result["reject_clicked"] and result.get("tracker_candidates_reload"):
            result["user_notice"]="거부 버튼을 눌렀지만 재방문 시 추적 관련 후보 네트워크 요청이 관찰되었습니다. 실제 추적 상태는 확정할 수 없습니다."
        elif result["reject_clicked"]:
            result["user_notice"]="거부 버튼을 눌렀습니다. 관찰 범위 내에서 알려진 추적 도메인 요청은 없었으나 전면적 추적 중단은 입증되지 않았습니다."
        else:result["user_notice"]="비교용 무조작 세션. 개인정보 거부 요청을 실행하지 않았습니다."
        result["finished_utc"]=utc()
        try:ctx.close()
        except Exception:pass
    return result
def main():
    output=Path("hcii_privacy/results");output.mkdir(parents=True,exist_ok=True)
    rows=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=["--no-sandbox"])
        for site in SITES:
            for arm in ["no_action","reject"]:
                print("RUN",site,arm,flush=True)
                z=measure(browser,site,arm,output);rows.append(z)
                (output/"observations.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False))
                print("RESULT",site,arm,z.get("status"),z.get("reject_clicked"),z.get("error"),flush=True)
        browser.close()
    pairs=[]
    for site in SITES:
        b=next(r for r in rows if r["site"]==site and r["arm"]=="no_action")
        t=next(r for r in rows if r["site"]==site and r["arm"]=="reject")
        pairs.append({"site":site,"baseline_error":b["error"],"reject_error":t["error"],
          "banner_visible":t.get("banner_visible"),"reject_clicked":t["reject_clicked"],
          "tracker_base":b.get("tracker_candidates_reload"),"tracker_reject":t.get("tracker_candidates_reload"),
          "tcf_initial":t.get("tcf_initial"),"tcf_reload":t.get("tcf_reload"),
          "user_notice":t["user_notice"]})
    (output/"summary.json").write_text(json.dumps(pairs,indent=2,ensure_ascii=False))
    for row in pairs:print("SUMMARY",json.dumps(row,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
