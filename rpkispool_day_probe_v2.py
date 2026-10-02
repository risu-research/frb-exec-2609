#!/usr/bin/env python3
import re,json,urllib.request,urllib.parse
from pathlib import Path
OUT=Path(__file__).resolve().parent/'results'/'rpkispool_day_probe_v2_20261002';OUT.mkdir(parents=True,exist_ok=True)
UA='risu-rpki-rpkispool-day-probe-v2/1.0'
MIRRORS=['https://rpkiviews.kerfuffle.net/rpkidata/rpkispools/','https://josephine.sobornost.net/rpkidata/rpkispools/']
DAYS=['01','03','04','05']

def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':UA})
 with urllib.request.urlopen(req,timeout=60) as r:return r.read().decode('utf8','replace')

def head(url):
 try:
  req=urllib.request.Request(url,headers={'User-Agent':UA},method='HEAD')
  with urllib.request.urlopen(req,timeout=30) as r:return {'status':r.status,'length':r.headers.get('Content-Length'),'type':r.headers.get('Content-Type'),'modified':r.headers.get('Last-Modified')}
 except Exception as e:return {'error':repr(e)}

def main():
 out={}
 for base in MIRRORS:
  out[base]={}
  for day in DAYS:
   u=f'{base}2026/09/{day}/'
   try:
    h=get(u); hrefs=[x for x in re.findall(r'href=["\']([^"\']+)["\']',h,re.I) if x not in ('../','./') and not x.startswith('?')]
    links=[urllib.parse.urljoin(u,x) for x in hrefs]
    sample=[]
    for i in sorted(set(list(range(min(12,len(links))))+list(range(max(0,len(links)-12),len(links))))):
     sample.append({'name':hrefs[i],'url':links[i],'head':head(links[i])})
    out[base][day]={'n_links':len(links),'names':hrefs,'head_sample':sample}
   except Exception as e:out[base][day]={'error':repr(e)}
 (OUT/'inventory.json').write_text(json.dumps(out,indent=2),encoding='utf8')
 print(json.dumps({b:{d:{'n':x.get('n_links'),'first':x.get('names',[])[:5],'last':x.get('names',[])[-5:],'err':x.get('error')} for d,x in v.items()} for b,v in out.items()},indent=2))
if __name__=='__main__':main()
