#!/usr/bin/env python3
"""Fast, verifiable narrow KuaiRand-1K randomized-insertion log pilot.
Source: HuggingFace community mirror numberbeat6/kuairand; no official CSV digest.
Zero causal generalization. Short view != hate.
"""
from pathlib import Path
import requests,hashlib,json,duckdb
SOURCE="https://huggingface.co/datasets/numberbeat6/kuairand/resolve/main/log_random_4_22_to_5_08_1k.csv?download=true"
DATA=Path("/tmp/kuairand_1k_random.csv")
OUT=Path("hcii_kuairand/results_1k");OUT.mkdir(parents=True,exist_ok=True)
def run():
 h=hashlib.sha256()
 with requests.get(SOURCE,stream=True,timeout=(15,45)) as r:
  print("HTTP",r.status_code,"LENGTH",r.headers.get("content-length"),"HOST",requests.utils.urlparse(r.url).hostname,flush=True)
  r.raise_for_status()
  with DATA.open("wb") as f:
   for chunk in r.iter_content(1024*1024):
    if chunk:f.write(chunk);h.update(chunk)
 print("DOWNLOADED",DATA.stat().st_size,"SHA256",h.hexdigest(),flush=True)
 if DATA.stat().st_size<10000: raise RuntimeError("Not a full 1K CSV")
 c=duckdb.connect()
 c.execute("SET threads=3")
 cols=[r[0] for r in c.execute(f"DESCRIBE SELECT * FROM read_csv_auto('{DATA}')").fetchall()]
 print("COLUMNS",cols,flush=True)
 need={"is_rand","is_like","is_hate","play_time_ms","duration_ms","tab","user_id","video_id"}
 assert need.issubset(cols), "Necessary columns absent"
 c.execute(f"""CREATE VIEW t AS SELECT *, CASE WHEN duration_ms>0 AND play_time_ms>=0 AND play_time_ms*4<duration_ms THEN 'short_lt25'
    WHEN duration_ms>0 AND play_time_ms>=0 AND play_time_ms<duration_ms THEN 'mid_25to99'
    WHEN duration_ms>0 AND play_time_ms>=0 THEN 'ge100'
    ELSE 'invalid' END AS depth
    FROM read_csv_auto('{DATA}')""")
 stats=c.execute("""SELECT count(*) n,count(DISTINCT user_id) users,count(DISTINCT video_id) videos,
      min(is_rand) min_rand,max(is_rand) max_rand,
      sum(is_hate) hate_count,sum(is_like) like_count,
      sum(CASE WHEN depth='short_lt25' THEN 1 ELSE 0 END) short_count
    FROM t""").fetchone()
 print("STATS",stats,flush=True)
 d=c.execute("""SELECT depth,count(*) n,sum(is_hate) hates,sum(is_like) likes,
    avg(CAST(is_hate AS DOUBLE)) hate_rate,
    avg(CAST(is_like AS DOUBLE)) like_rate
    FROM t GROUP BY 1 ORDER BY 1""").fetchall()
 print("DEPTH_HATE_LIKE",d,flush=True)
 tabs=c.execute("""SELECT tab,count(*) n,sum(is_hate) hates,
   sum(is_like) likes,count(*) FILTER (WHERE depth='short_lt25') short_count
   FROM t GROUP BY 1 ORDER BY 1""").fetchall()
 print("TABS",tabs,flush=True)
 audit=c.execute("""SELECT
    count(*) FILTER(WHERE depth='short_lt25' AND is_hate=0) short_without_hate,
    count(*) FILTER(WHERE depth='short_lt25' AND is_hate=1) short_with_hate,
    count(*) FILTER(WHERE depth='short_lt25' AND is_like=1) short_with_like,
    count(*) FILTER(WHERE depth<>'short_lt25' AND is_hate=1) hate_without_short,
    count(*) FILTER(WHERE is_hate=1 AND is_like=1) both_explicit,
    count(*) FILTER(WHERE duration_ms<=0 OR play_time_ms<0) invalid
   FROM t""").fetchone()
 print("AUDIT",audit,flush=True)
 result={"dataset":"KuaiRand-1K, random exposure log only (community HF mirror)",
    "source":SOURCE,"sha256":h.hexdigest(),"size_bytes":DATA.stat().st_size,
    "counts":dict(zip(["rows","users","videos","min_is_rand","max_is_rand","hates","likes","shorts"],stats)),
    "by_depth":[dict(zip(["depth","rows","hates","likes","hate_rate","like_rate"],r)) for r in d],
    "by_tab":[dict(zip(["tab","rows","hates","likes","shorts"],r)) for r in tabs],
    "audit":dict(zip(["short_without_hate","short_with_hate","short_with_like","hate_without_short","like_and_hate","invalid"],audit)),
    "limitations":["Third-party Hugging Face mirror of KuaiRand-1K; source CSV checksum is logged but not independently known",
       "Randomized-insertion-only data; NO unexposed control arm or causal A/B effects",
       "No test of personalized policy or longitudinal preference",
       "Play ratio not skip button, no hate not proof of positive preference",
       "1K user subsample, not representative of all users",
       "Instrumented UI variant and tab may change behavior"]}
 (OUT/"kuairand_random1k_pilot.json").write_text(json.dumps(result,indent=2))
 print("PILOT_FINAL",json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":run()
