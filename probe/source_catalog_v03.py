#!/usr/bin/env python3
"""Capture official Socrata publisher metadata and non-personal source statistics.

No source rows, entity names, addresses, or private files are published.
Metadata is a source-edition receipt, not evidence of a completed bulk ingest.
"""
import datetime
import hashlib
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DATASETS = (
    ("US-CO", "data.colorado.gov", "4ykn-tg5h", "entity_master"),
    ("US-CO", "data.colorado.gov", "casm-dbbj", "transaction_history"),
    ("US-NY", "data.ny.gov", "63wc-4exh", "all_filings"),
    ("US-NY", "data.ny.gov", "3gg2-jgnp", "entity_status_history"),
    ("US-NY", "data.ny.gov", "k4vb-judh", "daily_filings_window"),
)

def fetch(url):
    req=urllib.request.Request(url,headers={"Accept":"application/json","User-Agent":"RISUAP-source-edition-audit/0.3"})
    with urllib.request.urlopen(req,timeout=60) as f:
        raw=f.read(2_000_000)
        return json.loads(raw),hashlib.sha256(raw).hexdigest(),f.headers.get("ETag")

def examine(item):
    state,domain,dataset,role=item
    result={"jurisdiction":state,"dataset":dataset,"role":role,"domain":domain}
    try:
        meta,sha,etag=fetch("https://"+domain+"/api/views/"+dataset+".json")
        result.update({"title":meta.get("name"),"view_type":meta.get("viewType"),
                       "publisher_created_epoch":meta.get("createdAt"),
                       "publisher_rows_updated_epoch":meta.get("rowsUpdatedAt"),
                       "publisher_metadata_updated_epoch":meta.get("viewLastModified"),
                       "publisher_publication_epoch":meta.get("publicationDate"),
                       "publisher_license":meta.get("license"),
                       "publisher_metadata_response_sha256":sha,"publisher_metadata_etag":etag,
                       "columns":[{"field":c.get("fieldName"),"type":c.get("dataTypeName")}
                                  for c in meta.get("columns",[]) if c.get("fieldName") and not c.get("fieldName").startswith(":")]
                       })
    except Exception as exc:
        result["metadata_error"]=type(exc).__name__+": "+str(exc)[:150]
        return result
    try:
        count,_,_=fetch("https://"+domain+"/resource/"+dataset+".json?"+urllib.parse.urlencode({"$select":"count(*)"}))
        result["api_record_count"]=int(count[0]["count"])
    except Exception as exc:
        result["count_error"]=type(exc).__name__+": "+str(exc)[:150]
    return result

def main():
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows=list(pool.map(examine,DATASETS))
    print(json.dumps({"schema":"risuap_official_socrata_source_catalog_v03",
          "acquired_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
          "dataset_receipts":rows},sort_keys=True,indent=2))

if __name__=="__main__":
    main()
