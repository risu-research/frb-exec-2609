#!/usr/bin/env python3
"""Probe source-ID keyset pagination support without retrieving private records."""
import urllib.request,urllib.parse,json
SOURCES=[('co_master','data.colorado.gov','4ykn-tg5h'),('co_events','data.colorado.gov','casm-dbbj'),('ny_events','data.ny.gov','63wc-4exh'),('ny_status','data.ny.gov','3gg2-jgnp')]
def query(host,id,args):
 url='https://'+host+'/resource/'+id+'.json?'+urllib.parse.urlencode(args)
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RISUAP-keyset-preflight'}),timeout=90) as h:
  return json.load(h)
for name,host,id in SOURCES:
 try:
  page=query(host,id,{'$select':':id','$order':':id','$limit':3})
  if not len(page)==3 or not all(':id' in r for r in page):raise ValueError('first page unavailable')
  last=page[-1][':id'].replace("'","''")
  next_page=query(host,id,{'$select':':id','$where':":id > '"+last+"'","$order":':id','$limit':3})
  if not next_page or not all(r[':id']>page[-1][':id'] for r in next_page):raise ValueError('No monotone keyset page')
  print(json.dumps({'kind':name,'keyset_supported':True,'first_page_count':len(page),'next_page_count':len(next_page)}))
 except Exception as e:
  print(json.dumps({'kind':name,'keyset_supported':False,'reason':type(e).__name__+': '+str(e)[:100]}))
