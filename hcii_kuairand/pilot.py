#!/usr/bin/env python3
"""KuaiRand-Pure verifiable small real-data pilot; NOT causal dislike inference.
Randomized feed replacement vs standard policy is different treatment distribution.
"""
import hashlib,json,tarfile,os,time
from pathlib import Path
import requests,duckdb
URL="https://zenodo.org/records/10439422/files/KuaiRand-Pure.tar.gz"
MD5="0820331067a3784d9691136f772b35a7"
TAR=Path("/tmp/KuaiRand-Pure.tar.gz");ROOT=Path("/tmp/kuairand-unpack")
OUTPUT=Path("hcii_kuairand/results");OUTPUT.mkdir(parents=True,exist_ok=True)
def get_data():
 h=hashlib.md5()
 with requests.get(URL+"?download=1",stream=True,timeout=(20,75)) as r:
  print("DOWNLOAD",r.status_code,r.headers.get("content-length"),flush=True)
  r.raise_for_status()
  with TAR.open("wb") as f:
   for ch in r.iter_content(2*1024*1024):
    if ch:f.write(ch);h.update(ch)
 print("DOWNLOAD_VERIFIED",TAR.stat().st_size,h.hexdigest(),flush=True)
 if h.hexdigest()!=MD5: raise RuntimeError("Official MD5 mismatch")
 ROOT.mkdir(parents=True,exist_ok=True)
 with tarfile.open(TAR,"r:gz") as t:
  members=[m for m in t.getmembers() if m.isfile() and m.name.endswith(".csv") and "log_" in m.name]
  print("TAR_LOG_FILES",[(m.name,m.size) for m in members],flush=True)
  for m in members:
   # Whitelisted log files only; no symlinks or arbitrary filesystem writes.
   target=ROOT/Path(m.name).name
   with t.extractfile(m) as src,target.open("wb") as dst:
    while 1:
     data=src.read(2*1024*1024)
     if not data:break
     dst.write(data)
  if len(members)!=3:raise RuntimeError("Expected three pure log CSVs")
 return {p.name:str(p) for p in ROOT.glob("log_*pure.csv")}
def main():
 paths=get_data()
 c=duckdb.connect()
 c.execute("SET threads=3");c.execute("SET memory_limit='5GB'")
 c.execute("SET temp_directory='/tmp/kuairandtmp'")
 files=sorted(paths)
 for p in files:
  schema=c.execute("DESCRIBE SELECT * FROM read_csv_auto(?,sample_size=10000)",[paths[p]]).fetchall()
  print("SCHEMA",p,[z[0] for z in schema],flush=True)
 rpath=next(v for k,v in paths.items() if 'log_random' in k).replace("'","''")
 spath=next(v for k,v in paths.items() if 'log_standard_4_22' in k).replace("'","''")
 c.execute(f"""CREATE VIEW logs AS
   SELECT *, 'random' AS arm FROM read_csv_auto('{rpath}')
   UNION ALL BY NAME
   SELECT *, 'standard_same_dates' AS arm FROM read_csv_auto('{spath}')""")
 # Keep ratio clipped to [0,1] for binning, but preserve negative and >100% diagnostics separately.
 c.execute("""CREATE TEMP VIEW annotated AS SELECT arm,user_id,video_id,tab,
    CAST(is_rand AS INT) is_rand, CAST(is_like AS INT) is_like,
    CAST(is_hate AS INT) is_hate,CAST(is_click AS INT) is_click,
    CAST(long_view AS INT) long_view,
    play_time_ms,duration_ms,
    CASE WHEN duration_ms>0 AND play_time_ms>=0
         THEN LEAST(CAST(play_time_ms AS DOUBLE)/duration_ms,1.0) END AS frac,
    CASE WHEN duration_ms>0 AND play_time_ms>=0 THEN
      CASE WHEN play_time_ms*4<duration_ms THEN 'lt25'
           WHEN play_time_ms<duration_ms THEN '25to99'
           ELSE '100plus' END
    ELSE 'invalid' END AS depth
    FROM logs""")
 counts=c.execute("""SELECT arm,count(*) n,count(DISTINCT user_id) users,
    count(DISTINCT video_id) videos,sum(is_rand) rand,
    sum(is_hate) hates,sum(is_like) likes,
    sum(CAST(depth='invalid' AS INT)) invalid,
    sum(CAST(depth='lt25' AS INT)) short,
    avg(is_hate) hate_rate,avg(is_like) like_rate
    FROM annotated GROUP BY 1 ORDER BY 1""").fetchall()
 print("COUNTS",counts,flush=True)
 depth=c.execute("""SELECT arm,depth,count(*) n,
    sum(is_hate) hates,sum(is_like) likes,
    avg(is_hate) hate_rate,avg(is_like) like_rate,
    avg(is_click) click_rate,avg(long_view) long_view_rate
    FROM annotated GROUP BY 1,2 ORDER BY 1,2""").fetchall()
 print("DEPTH_HATE_LIKE",depth,flush=True)
 tab=c.execute("""SELECT arm,tab,count(*) n,
    count(*) FILTER(WHERE depth='lt25') short_n,
    sum(is_hate) hates,sum(is_like) likes
    FROM annotated GROUP BY 1,2 ORDER BY 1,2""").fetchall()
 print("TAB_COUNTS",tab,flush=True)
 # Same users and videos, but NOT same randomized exposures or controlled causal contrast.
 pair=c.execute("""SELECT count(*) total_user_video_pairs,
    count(*) FILTER(WHERE n_rand>0 AND n_std>0) overlap_both_arms,
    count(*) FILTER(WHERE n_rand>0) pair_random,
    count(*) FILTER(WHERE n_std>0) pair_standard
    FROM (SELECT user_id,video_id,count(*) FILTER(WHERE arm='random') n_rand,
    count(*) FILTER(WHERE arm='standard_same_dates') n_std FROM annotated
    GROUP BY 1,2)""").fetchone()
 print("OVERLAP",pair,flush=True)
 # short-view relationship to explicit negative feedback only, within randomized arm:
 within=c.execute("""SELECT depth,count(*) n,
    sum(is_hate) hates,sum(is_like) likes,
    sum(is_hate)*1.0/nullif(count(*),0) hate_fraction,
    sum(is_like)*1.0/nullif(count(*),0) like_fraction
    FROM annotated WHERE arm='random' GROUP BY 1 ORDER BY 1""").fetchall()
 print("WITHIN_RANDOM",within,flush=True)
 audit=c.execute("""SELECT count(*) n,
    count(*) FILTER(WHERE is_hate=1 AND is_like=1) conflicting_explicit,
    count(*) FILTER(WHERE depth='lt25' AND is_hate=0) short_without_hate,
    count(*) FILTER(WHERE depth!='lt25' AND is_hate=1) hate_without_short,
    count(*) FILTER(WHERE depth='lt25' AND is_like=1) short_with_like,
    count(*) FILTER(WHERE duration_ms<=0 OR play_time_ms<0) invalid_play,
    count(*) FILTER(WHERE duration_ms>0 AND play_time_ms>duration_ms) above_duration
    FROM annotated WHERE arm='random'""").fetchone()
 print("DIAGNOSTICS",audit,flush=True)
 out={"dataset":"KuaiRand-Pure","download":URL,"md5":MD5,
    "arm_counts":[dict(zip(["arm","n","users","videos","random_flags","hates","likes","invalid","short","hate_rate","like_rate"],r)) for r in counts],
    "depth":[dict(zip(["arm","depth","n","hates","likes","hate_rate","like_rate","click_rate","long_view_rate"],r)) for r in depth],
    "tab":[dict(zip(["arm","tab","n","short_n","hates","likes"],r)) for r in tab],
    "overlap":dict(zip(["user_video_pairs","both_arms","random","standard"],pair)),
    "within_random":[dict(zip(["depth","n","hates","likes","hate_rate","like_rate"],r)) for r in within],
    "diagnostics":dict(zip(["n","explicit_like_hate_conflict","short_without_hate","hate_without_short","short_with_like","invalid_play","playtime_above_duration"],audit)),
    "disclaimers":["Actual user like/hate presses distinct from watch-duration proxies",
       "Pure retains only random candidate pool standard items: nonrandom standard subset is heavily selected",
       "Random item replacement is randomized within feed; standard arm vs random arm is NOT a randomized item-controlled design",
       "Some UI tabs use is_click as valid play rather than literal click",
       "No proof absence of hate means favorable feedback","No evidence that watch time is a literal skip button",
       "This is small real-data pilot, not deployed policy effectiveness or a causal intervention test"]}
 (OUTPUT/"kuairand_pure_stage0.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
 print("RESULT_WRITTEN",str(OUTPUT/"kuairand_pure_stage0.json"),flush=True)
 print("RESULT_SUMMARY",json.dumps({"counts":counts,"depth":depth,"diagnostics":audit},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
