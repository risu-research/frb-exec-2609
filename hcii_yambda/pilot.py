#!/usr/bin/env python3
"""Yambda 50M quick matched-source feasibility pilot; observational, not causal."""
import hashlib,json,os,time
from pathlib import Path
import requests,duckdb
URL="https://huggingface.co/datasets/yandex/yambda/resolve/main/flat/50m/listens.parquet?download=true"
EXPECTED_SHA256="eed9cbd094af1e189507d2f8132a0dc9653b90e65480125c7cdccd601e0592d1"
OUT=Path("hcii_yambda/results");OUT.mkdir(parents=True,exist_ok=True)
DATA=Path("/tmp/yambda_50m_listens.parquet")
def download():
    sha=hashlib.sha256();n=0;t=time.time()
    print("DOWNLOAD_START",URL,flush=True)
    with requests.get(URL,stream=True,timeout=(20,70),headers={"User-Agent":"RISU-HCII-Yambda-feasibility/1.0"}) as response:
        print("HTTP",response.status_code,"length",response.headers.get("Content-Length"),"final_domain",requests.utils.urlparse(response.url).hostname,flush=True)
        response.raise_for_status()
        with DATA.open("wb") as f:
            for buf in response.iter_content(chunk_size=2*1024*1024):
                if buf: f.write(buf);sha.update(buf);n+=len(buf)
                if n and n%(80*1024*1024)<2*1024*1024:print("DOWNLOAD_BYTES",n,flush=True)
    digest=sha.hexdigest()
    print("DOWNLOAD_COMPLETE_BYTES",n,"SHA256",digest,"SECONDS",round(time.time()-t,1),flush=True)
    if digest != EXPECTED_SHA256:raise RuntimeError("SHA256 mismatch for officially published LFS object")
def main():
    download()
    t=time.time()
    con=duckdb.connect()
    con.execute("SET threads=3")
    con.execute("SET memory_limit='4GB'")
    con.execute("SET temp_directory='/tmp/yambda_duck_temp'")
    p=str(DATA).replace("'","''")
    print("PARQUET_SCHEMA",con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall(),flush=True)
    con.execute(f"CREATE VIEW listens AS SELECT * FROM read_parquet('{p}')")
    overall=con.execute("""SELECT CAST(is_organic AS INT) AS source, count(*) AS n,
       count(DISTINCT uid) AS users, avg(played_ratio_pct) AS mean_ratio,
       avg(CAST(played_ratio_pct < 25 AS INT)) AS low25,
       avg(CAST(played_ratio_pct < 50 AS INT)) AS low50,
       avg(CAST(played_ratio_pct >=90 AS INT)) AS full90,
       avg(CAST(played_ratio_pct >100 AS INT)) AS over100,
       avg(track_length_seconds) AS avg_length
       FROM listens GROUP BY 1 ORDER BY 1""").fetchall()
    print("OVERALL",overall,flush=True)
    # Same user, exact same track, both organic and recommendation-driven listening.
    # Each matched pair contributes equal weight. Repeated listen means, no claim of randomized source.
    con.execute("""CREATE TEMP TABLE both_contexts AS
      SELECT uid,item_id,
      count(*) FILTER (WHERE is_organic=1) AS n_org,
      count(*) FILTER (WHERE is_organic=0) AS n_rec,
      avg(CAST(played_ratio_pct<25 AS DOUBLE)) FILTER (WHERE is_organic=1) AS low25_org,
      avg(CAST(played_ratio_pct<25 AS DOUBLE)) FILTER (WHERE is_organic=0) AS low25_rec,
      avg(CAST(played_ratio_pct>=90 AS DOUBLE)) FILTER (WHERE is_organic=1) AS full90_org,
      avg(CAST(played_ratio_pct>=90 AS DOUBLE)) FILTER (WHERE is_organic=0) AS full90_rec,
      avg(CAST(played_ratio_pct AS DOUBLE)) FILTER (WHERE is_organic=1) AS ratio_org,
      avg(CAST(played_ratio_pct AS DOUBLE)) FILTER (WHERE is_organic=0) AS ratio_rec,
      min(timestamp) FILTER (WHERE is_organic=1) AS first_org_ts,
      min(timestamp) FILTER (WHERE is_organic=0) AS first_rec_ts,
      min(track_length_seconds) AS length_sec
      FROM listens GROUP BY uid,item_id
      HAVING count(*) FILTER (WHERE is_organic=1)>0
       AND count(*) FILTER (WHERE is_organic=0)>0""")
    matched=con.execute("""SELECT count(*) AS pairs,count(DISTINCT uid) AS users,count(DISTINCT item_id) AS tracks,
      sum(n_org) AS org_events,sum(n_rec) AS rec_events,
      avg(low25_org) AS low25_org,avg(low25_rec) AS low25_rec,
      avg(low25_org-low25_rec) AS low25_delta,
      avg(full90_org) AS full90_org,avg(full90_rec) AS full90_rec,
      avg(full90_org-full90_rec) AS full90_delta,
      avg(ratio_org-ratio_rec) AS ratio_delta,
      count(*) FILTER(WHERE first_org_ts<first_rec_ts) AS organic_first,
      count(*) FILTER(WHERE first_rec_ts<first_org_ts) AS recommended_first,
      count(*) FILTER(WHERE first_rec_ts=first_org_ts) AS ties
      FROM both_contexts""").fetchone()
    print("MATCHED_STATS",matched,flush=True)
    # Repeated observations each mode >= 2, to test robustness against one-time encounters.
    repeated=con.execute("""SELECT count(*) AS pairs,count(DISTINCT uid) AS users,
    avg(low25_org-low25_rec) AS low25_delta,avg(full90_org-full90_rec) AS full90_delta
    FROM both_contexts WHERE n_org>=2 AND n_rec>=2""").fetchone()
    print("REPEATED_BOTH",repeated,flush=True)
    order=con.execute("""SELECT
      CASE WHEN first_org_ts<first_rec_ts THEN 'organic_first'
           WHEN first_rec_ts<first_org_ts THEN 'recommended_first' ELSE 'tie' END AS first_source,
      count(*) AS pairs,
      avg(low25_org-low25_rec) AS delta_low25,
      avg(full90_org-full90_rec) AS delta_full90
      FROM both_contexts GROUP BY 1 ORDER BY 1""").fetchall()
    print("ORDER_STRATA",order,flush=True)
    # User-wise aggregates for cluster-level descriptive evidence; no user ID exported.
    user_stats=con.execute("""SELECT count(*) AS users,count(*) FILTER(WHERE pair_count>=10) AS users_ge10,
        AVG(pair_delta) AS mean_user_delta,
        STDDEV_SAMP(pair_delta) AS sd_user_delta
      FROM (SELECT uid,count(*) AS pair_count,avg(low25_org-low25_rec) AS pair_delta
            FROM both_contexts GROUP BY uid)""").fetchone()
    print("USER_STATS",user_stats,flush=True)
    results={"dataset":"yandex/yambda flat/50m/listens.parquet",
      "dataset_sha256":EXPECTED_SHA256,"n_rows":int(sum(x[1] for x in overall)),
      "source_summary":[dict(zip(["organic","n","users","mean_ratio","low25","low50","full90","over100","avg_length"],row)) for row in overall],
      "matched_summary":dict(zip(["pairs","users","tracks","org_events","rec_events","low25_org","low25_rec","low25_delta","full90_org","full90_rec","full90_delta","ratio_delta","organic_first","recommended_first","ties"],matched)),
      "repeated_both_summary":dict(zip(["pairs","users","low25_delta","full90_delta"],repeated)),
      "order_strata":[dict(zip(["first_source","pairs","delta_low25","delta_full90"],row)) for row in order],
      "user_stats":dict(zip(["users","users_ge10","mean_user_delta","sd_user_delta"],user_stats)),
      "no_causal_claim":True,
      "notes":["Low played ratio is a proxy, not verified user skip","Source is pathway, not randomized assignment","Same user+track controls their identities but not mood, position, prior exposure or novelty","No local-time-of-day inference from binned timestamps"] }
    if matched[0] is None or matched[0]<10000: results["decision"]="FAIL matched sample below 10k"
    elif abs(matched[8])<0.01 and abs(matched[11])<0.01: results["decision"]="FAIL matched effect sizes tiny"
    else: results["decision"]="FEASIBLE matched-source comparison; novelty remains to be reviewed"
    (OUT/"pilot_results.json").write_text(json.dumps(results,indent=2,ensure_ascii=False,allow_nan=False))
    print("FINAL_DECISION",results["decision"],"SECONDS_ANALYSIS",round(time.time()-t,1),flush=True)
    print("FINAL_JSON",json.dumps(results,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
