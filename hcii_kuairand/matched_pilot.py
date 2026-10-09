#!/usr/bin/env python3
"""KuaiRand-1K real-data same-date random vs standard comparison.
Exact user + tab + duration bin overlap; random-arm poststratification.
Estimand is DESCRIPTIVE contrast between differently selected exposed items,
not causal effect or inference of true dislike.
"""
import requests,hashlib,json,time
from pathlib import Path
import duckdb

BASE="https://huggingface.co/datasets/numberbeat6/kuairand/resolve/main/"
FNAMES=["log_random_4_22_to_5_08_1k.csv","log_standard_4_22_to_5_08_1k.csv"]
OUT=Path("hcii_kuairand/results_matched");OUT.mkdir(parents=True,exist_ok=True)
TEMP=Path("/tmp/kuairand_matching");TEMP.mkdir(exist_ok=True)
def grab(file):
 p=TEMP/file
 h=hashlib.sha256()
 with requests.get(BASE+file+"?download=true",stream=True,timeout=(20,90)) as r:
  print("DOWNLOAD_HTTP",file,r.status_code,"size_header",r.headers.get("content-length"),flush=True)
  r.raise_for_status()
  with p.open("wb") as w:
   for chunk in r.iter_content(chunk_size=2**20):
    if chunk:w.write(chunk);h.update(chunk)
 print("DOWNLOAD_OK",file,p.stat().st_size,h.hexdigest(),flush=True)
 if p.stat().st_size<100000: raise RuntimeError("Truncated CSV")
 return str(p),h.hexdigest()
def main():
 paths={};hashes={}
 for fname in FNAMES:
  paths[fname],hashes[fname]=grab(fname)
 c=duckdb.connect()
 c.execute("SET threads=3");c.execute("SET memory_limit='5GB'")
 c.execute("SET temp_directory='/tmp/kua_ducktmp'")
 rpath=paths[FNAMES[0]].replace("'","''")
 spath=paths[FNAMES[1]].replace("'","''")
 for name,path in (("r",rpath),("s",spath)):
  c.execute(f"CREATE VIEW {name} AS SELECT * FROM read_csv_auto('{path}',sample_size=30000)")
  print("SCHEMA",name,[x[0] for x in c.execute(f"DESCRIBE {name}").fetchall()],flush=True)
  print("ARM_SIZE",name,c.execute(f"SELECT count(*),count(DISTINCT user_id),min(date),max(date),min(is_rand),max(is_rand) FROM {name}").fetchone(),flush=True)
  assert c.execute(f"SELECT min(date)>=20220422 AND max(date)<=20220508 FROM {name}").fetchone()[0],name+": date window outside"
 assert c.execute("SELECT min(is_rand)=1 AND max(is_rand)=1 FROM r").fetchone()[0],"not exclusively randomized arm"
 # Same-day raw event analysis. Show invalid playback separately, and exclude these rows from matched estimates.
 c.execute(f"""CREATE VIEW combined AS
 SELECT 'random' arm,user_id,video_id,tab,date,duration_ms,play_time_ms,
   is_rand,CAST(is_like AS INT) AS is_like,CAST(is_hate AS INT) AS is_hate
   FROM r
 UNION ALL BY NAME
 SELECT 'standard' arm,user_id,video_id,tab,date,duration_ms,play_time_ms,
   is_rand,CAST(is_like AS INT) AS is_like,CAST(is_hate AS INT) AS is_hate
   FROM s""")
 # For length matching 5 predeclared coarse classes; note played ratio 25% may mean different time spent.
 c.execute("""CREATE VIEW valid AS
 SELECT *, CASE
   WHEN duration_ms<10000 THEN '1_under10s'
   WHEN duration_ms<30000 THEN '2_10to29s'
   WHEN duration_ms<60000 THEN '3_30to59s'
   WHEN duration_ms<120000 THEN '4_60to119s'
   ELSE '5_ge120s' END AS length_bin,
 CAST(play_time_ms*4<duration_ms AS INT) AS short25,
 CAST(play_time_ms>=duration_ms AS INT) AS full100
 FROM combined WHERE duration_ms>0 AND play_time_ms>=0
 AND is_hate IN (0,1) AND is_like IN (0,1)""")
 arm=c.execute("""SELECT arm,count(*) n,count(DISTINCT user_id) users,
     count(DISTINCT video_id) videos, count(DISTINCT tab) tabs,
     avg(CAST(short25 AS DOUBLE)) short25,
     avg(CAST(is_like AS DOUBLE)) like_rate,
     avg(CAST(is_hate AS DOUBLE)) hate_rate,
     count(*) FILTER (WHERE is_hate=1 AND short25=1) short_hate,
     count(*) FILTER (WHERE is_hate=1 AND short25=0) nons_hate,
     count(*) FILTER (WHERE is_like=1 AND short25=1) short_like,
     avg(duration_ms) mean_duration_ms
     FROM valid GROUP BY arm ORDER BY arm""").fetchall()
 print("RAW_ARM",arm,flush=True)
 tab=c.execute("SELECT arm,tab,count(*) n,avg(CAST(short25 AS DOUBLE)) short_rate,avg(CAST(is_hate AS DOUBLE)) hate_rate,avg(CAST(is_like AS DOUBLE)) like_rate FROM valid GROUP BY arm,tab ORDER BY tab,arm").fetchall()
 print("TABS",tab,flush=True)
 # Exact same user and UI/tab, with video duration bin. Standard selected item vs random candidate still differ.
 c.execute("""CREATE TEMP TABLE cell AS
 SELECT arm,user_id,tab,length_bin,
 count(*) n,sum(short25) nshort,sum(is_hate) nhate,sum(is_like) nlike,
 sum(CAST(short25=1 AND is_hate=1 AS INT)) nshort_hate,
 sum(CAST(short25=1 AND is_like=1 AS INT)) nshort_like
 FROM valid GROUP BY arm,user_id,tab,length_bin""")
 c.execute("""CREATE TEMP TABLE paired AS SELECT
   r.user_id,r.tab,r.length_bin,
   r.n rand_n,s.n standard_n,
   CAST(r.nshort AS DOUBLE)/r.n rand_short,CAST(s.nshort AS DOUBLE)/s.n standard_short,
   CAST(r.nhate AS DOUBLE)/r.n rand_hate,CAST(s.nhate AS DOUBLE)/s.n standard_hate,
   CAST(r.nlike AS DOUBLE)/r.n rand_like,CAST(s.nlike AS DOUBLE)/s.n standard_like,
   r.nshort_hate rand_short_hate,s.nshort_hate standard_short_hate,
   r.nshort_like rand_short_like,s.nshort_like standard_short_like
 FROM cell r JOIN cell s ON r.user_id=s.user_id AND r.tab=s.tab AND r.length_bin=s.length_bin
 WHERE r.arm='random' AND s.arm='standard'
 AND r.n>=1 AND s.n>=1""")
 support=c.execute("""SELECT count(*) cells,count(DISTINCT user_id) users,
 sum(rand_n) rand_events,sum(standard_n) standard_events,
 sum(CAST(rand_n>=5 AS INT)) cells_rand5,
 sum(rand_n) FILTER (WHERE rand_n>=5 AND standard_n>=5) matched_rand5
 FROM paired""").fetchone()
 print("MATCH_SUPPORT",support,flush=True)
 # Weight EACH paired cell by number randomized observations -> common-support randomized-arm target.
 def estimator(where):
  a=c.execute(f"""SELECT count(*) cells,count(DISTINCT user_id) users,sum(rand_n) random_weight,
  sum(rand_n*rand_short)/sum(rand_n) r_short,
  sum(rand_n*standard_short)/sum(rand_n) s_short,
  sum(rand_n*rand_hate)/sum(rand_n) r_hate,
  sum(rand_n*standard_hate)/sum(rand_n) s_hate,
  sum(rand_n*rand_like)/sum(rand_n) r_like,
  sum(rand_n*standard_like)/sum(rand_n) s_like
  FROM paired {where}""").fetchone()
  return dict(zip(["cells","users","random_weight","random_short25","standard_short25","random_hate","standard_hate","random_like","standard_like"],a))
 matched=estimator("")
 robust=estimator("WHERE rand_n>=5 AND standard_n>=5")
 print("MATCHED_WEIGHTED",matched,flush=True)
 print("MATCHED_FIVE_PLUS",robust,flush=True)
 # Store user-level paired-cell components, bootstrap users using these (not raw events) for descriptive CI.
 user=c.execute("""SELECT user_id,sum(rand_n) w,
    sum(rand_n*rand_short) rs,sum(rand_n*standard_short) ss,
    sum(rand_n*rand_hate) rh,sum(rand_n*standard_hate) sh,
    sum(rand_n*rand_like) rl,sum(rand_n*standard_like) sl
    FROM paired GROUP BY user_id""").fetchall()
 import random
 rng=random.Random(20261009)
 vals=[tuple(float(t) for t in x[1:]) for x in user]
 samples=[]
 for _ in range(350):
  sums=[0.]*7
  for i in range(len(vals)):
   v=vals[rng.randrange(len(vals))]
   for j in range(7):sums[j]+=v[j]
  samples.append(((sums[1]-sums[2])/sums[0],(sums[3]-sums[4])/sums[0],(sums[5]-sums[6])/sums[0]))
 def ci(i):
  x=sorted(t[i] for t in samples)
  return [x[int(.025*(len(x)-1))],x[int(.975*(len(x)-1))]]
 interval={"random_minus_standard_short25":ci(0),"random_minus_standard_hate":ci(1),"random_minus_standard_like":ci(2),"resamples":len(samples),"users":len(vals)}
 print("CLUSTER_BOOTSTRAP",interval,flush=True)
 # Stronger diagnostic with exact video_id as well, only where same user and item overlap in BOTH arms.
 same=c.execute("""SELECT count(*) overlap_pairs,count(DISTINCT r.user_id) users,
  sum(r.n) n_random,sum(s.n) n_standard
 FROM (SELECT user_id,video_id,count(*) n FROM valid WHERE arm='random' GROUP BY 1,2) r
 JOIN (SELECT user_id,video_id,count(*) n FROM valid WHERE arm='standard' GROUP BY 1,2) s
 USING(user_id,video_id)""").fetchone()
 print("SAME_USER_VIDEO_OVERLAP",same,flush=True)
 diag=c.execute("""SELECT arm,count(*) n,
    count(*) FILTER (WHERE duration_ms<=0 OR play_time_ms<0) invalid,
    count(*) FILTER (WHERE duration_ms>0 AND play_time_ms>duration_ms) over_duration,
    min(is_rand),max(is_rand)
    FROM combined GROUP BY arm ORDER BY arm""").fetchall()
 print("INVALID_DIAGNOSTICS",diag,flush=True)
 result={
 "sources":{k:{"url":BASE+k,"sha256":hashes[k]} for k in FNAMES},
 "data":"KuaiRand-1K community HF mirror, same calendar window 2022-04-22 through 2022-05-08",
 "primary_estimand":"random exposure weighted common-support within exact user, tab, video duration bin",
 "length_bins_ms":["<10000","10000-29999","30000-59999","60000-119999",">=120000"],
 "raw_arms":[dict(zip(["arm","n","users","videos","tabs","short25","like_rate","hate_rate","short_hate","nonshort_hate","short_like","duration_mean_ms"],a)) for a in arm],
 "tab":[dict(zip(["arm","tab","n","short_rate","hate_rate","like_rate"],a)) for a in tab],
 "support":dict(zip(["matched_cells","users","random_events","standard_events","cells_random_ge5","random_events_in_both_ge5"],support)),
 "matched_random_weighted":matched,"matched_min5":robust,"user_cluster_ci":interval,
 "same_user_video_overlap":dict(zip(["pairs","users","random_events","standard_events"],same)),
 "data_diagnostics":[dict(zip(["arm","n","invalid_duration_or_playtime","over_duration","min_rand_flag","max_rand_flag"],a)) for a in diag],
 "limitations":["Observational comparison of randomized replacement item pool vs algorithm-selected items, not an unconditional randomized A/B treatment effect",
   "Same user/tab/length bin still differs in video content, exposure opportunity, position, intrinsic preferences",
   "Content length bins coarse; common-support poststratification weights can be unstable",
   "Randomized inserted item is not equal to users randomized to algorithm policies",
   "Random vs standard dataset overlap can be sparse in users/items",
   "No Hate does not imply favorable preference; play ratio is not a literal skip press",
   "User cluster bootstrap is descriptive not a causal identification method",
   "HF mirror data hash is tracked but not cross-validated to official Zenodo record"]
 }
 (OUT/"kuairand_random_standard_matched.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print("FINAL_AGGREGATE",json.dumps({"raw":result["raw_arms"],"support":result["support"],"matched":matched,"matched_min5":robust,"CI":interval,"same_video":result["same_user_video_overlap"]},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
