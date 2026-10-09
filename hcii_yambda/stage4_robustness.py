#!/usr/bin/env python3
"""Stage 3: evaluate delayed self-directed re-engagement after first short recommendation listening.
This is an observational policy stress test, not verified skips, dislike, or causal effect.
"""
import json,time,hashlib
from pathlib import Path
import duckdb,requests
LIS="https://huggingface.co/datasets/yandex/yambda/resolve/main/flat/50m/listens.parquet?download=true"
LIK="https://huggingface.co/datasets/yandex/yambda/resolve/main/flat/50m/likes.parquet?download=true"
LIS_SHA="eed9cbd094af1e189507d2f8132a0dc9653b90e65480125c7cdccd601e0592d1"
LIK_SHA="694087077dbacfcc1d22a5ca85cc6bd8ab182361933406e60500624c6a422bc4"
DISLIK="https://huggingface.co/datasets/yandex/yambda/resolve/main/flat/50m/dislikes.parquet?download=true"
DISLIK_SHA="64f240a6d62b8acdfa6efae660a54d10ebc64f9f2f0aeeef8e6bb0dbe7dc2802"
out=Path("hcii_yambda/results_stage4");out.mkdir(parents=True,exist_ok=True)
def fetch(url,path,expected):
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==expected:
        print("CACHE_HIT",path,flush=True);return
    print("FETCH",url,flush=True)
    h=hashlib.sha256()
    with requests.get(url,stream=True,timeout=(20,90)) as r:
        print("HTTP",r.status_code,"LEN",r.headers.get("content-length"),flush=True);r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=4*1024*1024):
                if chunk:f.write(chunk);h.update(chunk)
    print("SHA",path.name,h.hexdigest(),flush=True)
    if h.hexdigest()!=expected:raise RuntimeError("bad checksum")
def main():
    fetch(LIS,Path("/tmp/yambda_listens.parquet"),LIS_SHA)
    fetch(LIK,Path("/tmp/yambda_likes.parquet"),LIK_SHA)
    fetch(DISLIK,Path("/tmp/yambda_dislikes.parquet"),DISLIK_SHA)
    c=duckdb.connect()
    c.execute("SET threads=4");c.execute("SET memory_limit='5GB'");c.execute("SET temp_directory='/tmp/yambda_tmp'")
    # Timestamp stored as seconds, quantized to 5-second precision; NOT five-second unit indices.
    c.execute("CREATE VIEW l AS SELECT * FROM read_parquet('/tmp/yambda_listens.parquet')")
    c.execute("CREATE VIEW likes AS SELECT * FROM read_parquet('/tmp/yambda_likes.parquet')")
    c.execute("CREATE VIEW dislikes AS SELECT * FROM read_parquet('/tmp/yambda_dislikes.parquet')")
    stats=c.execute("SELECT min(timestamp),max(timestamp),max(timestamp)-min(timestamp),count(DISTINCT uid) FROM l").fetchone()
    print("TIME_RANGE_SECONDS",stats, "DAYS",(stats[1]-stats[0])/86400,flush=True)
    print("UID_MOD5",c.execute("SELECT uid%5, count(DISTINCT uid),count(*) FROM l GROUP BY 1 ORDER BY 1").fetchall(),flush=True)
    print("TS_MOD5",c.execute("SELECT timestamp%5, count(*) FROM l GROUP BY 1 ORDER BY 1").fetchall(),flush=True)
    print("LIKES_SCHEMA",c.execute("DESCRIBE SELECT * FROM likes").fetchall(),flush=True)
    # Full 50M listen data. The uid values are not uniformly distributed mod 5.
    c.execute("CREATE TEMP TABLE ls AS SELECT uid,item_id,timestamp,is_organic,played_ratio_pct,track_length_seconds FROM l")
    c.execute("""CREATE TEMP TABLE firsts AS SELECT uid,item_id,timestamp AS first_ts,
    is_organic AS first_org,played_ratio_pct AS first_ratio,track_length_seconds AS duration
    FROM (SELECT *, row_number() OVER(PARTITION BY uid,item_id ORDER BY timestamp,is_organic DESC,played_ratio_pct DESC) n
          FROM ls) WHERE n=1 AND timestamp<=?""",[int(stats[1]-30*86400)])
    # Drop first-events with same-time conflicting route / play percentages, ambiguity from 5s binning.
    c.execute("""DELETE FROM firsts WHERE EXISTS(
      SELECT 1 FROM ls WHERE ls.uid=firsts.uid AND ls.item_id=firsts.item_id
      AND ls.timestamp=firsts.first_ts
      GROUP BY uid,item_id,timestamp HAVING count(*)>1)""")
    first_info=c.execute("""SELECT count(*),count(DISTINCT uid),
      count(*) FILTER (WHERE first_org=0),
      count(*) FILTER (WHERE first_org=0 AND first_ratio<25),
      count(*) FILTER (WHERE first_org=1 AND first_ratio<25)
      FROM firsts""").fetchone()
    print("FIRSTS",first_info,flush=True)
    # Any later organic, and a stronger proxy: later organic play>=90%.
    c.execute("""CREATE TEMP TABLE followed AS
     SELECT f.uid,f.item_id,f.first_ts,f.first_org,f.first_ratio,f.duration,
       min(l.timestamp) FILTER (WHERE l.is_organic=1) AS next_org,
       min(l.timestamp) FILTER (WHERE l.is_organic=1 AND l.played_ratio_pct>=90) AS next_org90,
       min(l.timestamp) FILTER (WHERE l.is_organic=1 AND l.played_ratio_pct>=90 AND l.timestamp>=f.first_ts+86400) AS next_org90_late,
       min(l.timestamp) AS next_any,
       min(l.timestamp) FILTER (WHERE l.played_ratio_pct>=90) AS next_any90
     FROM firsts f LEFT JOIN ls l ON f.uid=l.uid AND f.item_id=l.item_id AND l.timestamp>f.first_ts
     GROUP BY f.uid,f.item_id,f.first_ts,f.first_org,f.first_ratio,f.duration""")
    c.execute("""CREATE TEMP TABLE with_like AS
     SELECT f.*,min(k.timestamp) AS next_like,
       min(k.timestamp) FILTER (WHERE k.timestamp>=f.first_ts+86400) AS next_like_late
     FROM followed f LEFT JOIN likes k ON k.uid=f.uid AND k.item_id=f.item_id AND k.timestamp>f.first_ts
     GROUP BY f.uid,f.item_id,f.first_ts,f.first_org,f.first_ratio,f.duration,
       f.next_org,f.next_org90,f.next_org90_late,f.next_any,f.next_any90""")
    # Follow-up by source and initial playback. Periods in 5-second bins.
    rows=c.execute("""SELECT
       CASE WHEN first_org=1 THEN 'organic' ELSE 'recommended' END AS initial_source,
       CASE WHEN first_ratio<25 THEN 'short_lt25'
            WHEN first_ratio>=90 THEN 'full_ge90'
            ELSE 'middle_25_89' END AS initial_depth,
       count(*) AS exposures,
       count(*) FILTER (WHERE next_org>first_ts AND next_org-first_ts<=? ) AS next_org_1d,
       count(*) FILTER (WHERE next_org>first_ts AND next_org-first_ts<=? ) AS next_org_7d,
       count(*) FILTER (WHERE next_org>first_ts AND next_org-first_ts<=? ) AS next_org_30d,
       count(*) FILTER (WHERE next_org90>first_ts AND next_org90-first_ts<=? ) AS org90_7d,
       count(*) FILTER (WHERE next_org90>first_ts AND next_org90-first_ts<=? ) AS org90_30d,
       count(*) FILTER (WHERE next_any90>first_ts AND next_any90-first_ts<=? ) AS any90_30d,
       count(*) FILTER (WHERE next_like>first_ts AND next_like-first_ts<=? ) AS like_30d
     FROM with_like GROUP BY 1,2 ORDER BY 1,2""",[
       86400,7*86400,30*86400,7*86400,30*86400,30*86400,30*86400]).fetchall()
    print("FOLLOWUP_ROWS",rows,flush=True)
    cols=["source","depth","exposures","org_1d","org_7d","org_30d","org90_7d","org90_30d","any90_30d","like_30d"]
    data=[dict(zip(cols,row)) for row in rows]
    # Per-user non-overlapping users for coarse descriptive reliability; no raw user identifiers released.
    users=c.execute("""SELECT first_org,case when first_ratio<25 then 'short' when first_ratio>=90 then 'full' else 'mid' end as depth,
      count(DISTINCT uid) AS users,
      count(*) FILTER(WHERE next_org90>first_ts AND next_org90-first_ts<=?) n_later_org90
      FROM with_like GROUP BY 1,2 ORDER BY 1,2""",[30*86400]).fetchall()
    print("GROUP_USERS",users,flush=True)
    # Positive signal definition: later organic high-play or explicit like. Union rather than sum.
    pos=c.execute("""SELECT first_org,
    case when first_ratio<10 then 'lt10' when first_ratio<25 then '10_24'
         when first_ratio<50 then '25_49' when first_ratio<90 then '50_89' else 'ge90' end depth,
    count(*) n,
    count(*) FILTER(WHERE (next_org90>first_ts AND next_org90-first_ts<=?) OR
      (next_like>first_ts AND next_like-first_ts<=?)) positive_30d
    FROM with_like GROUP BY 1,2 ORDER BY 1,2""",[30*86400,30*86400]).fetchall()
    print("FUTURE_POSITIVE",pos,flush=True)

    # Add future explicit negative as an independent contrast; never call the actions user motivation.
    c.execute("""CREATE TEMP TABLE plus_negative AS
      SELECT f.*, min(d.timestamp) FILTER (WHERE d.timestamp>=f.first_ts+86400) AS next_dislike_late
      FROM with_like f LEFT JOIN dislikes d ON d.uid=f.uid AND d.item_id=f.item_id AND d.timestamp>f.first_ts
      GROUP BY f.uid,f.item_id,f.first_ts,f.first_org,f.first_ratio,f.duration,
      f.next_org,f.next_org90,f.next_org90_late,f.next_any,f.next_any90,f.next_like,f.next_like_late""")
    c.execute("""CREATE TEMP TABLE evidence AS SELECT uid,item_id,first_ts,first_org,first_ratio,duration,
       CAST((next_like_late IS NOT NULL AND next_like_late-first_ts<=2592000) AS INT) AS later_like,
       CAST((next_dislike_late IS NOT NULL AND next_dislike_late-first_ts<=2592000) AS INT) AS later_dislike,
       CAST((next_org90_late IS NOT NULL AND next_org90_late-first_ts<=2592000) AS INT) AS later_org90,
       CAST(((next_like_late IS NOT NULL AND next_like_late-first_ts<=2592000)
         OR (next_org90_late IS NOT NULL AND next_org90_late-first_ts<=2592000)) AS INT) AS later_positive,
       CASE WHEN first_ratio<10 THEN 'lt10'
         WHEN first_ratio<25 THEN '10_24'
         WHEN first_ratio<50 THEN '25_49'
         WHEN first_ratio<90 THEN '50_89' ELSE 'ge90' END AS depth
       FROM plus_negative""")
    # Only observed positive/negative event incidence; explicit unlike/dislike reversals not analyzed here.
    detail=c.execute("""SELECT first_org,depth,count(*) n,
        sum(later_like) likes_1to30d,sum(later_dislike) dislikes_1to30d,
        sum(later_org90) org90_1to30d,sum(later_positive) positive_1to30d,
        count(DISTINCT uid) users,
        count(DISTINCT uid) FILTER(WHERE later_positive=1) users_with_positive
        FROM evidence GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    print("AUDIT_DEPTH",detail,flush=True)
    cohort=c.execute("""SELECT
        CASE WHEN first_ts<7776000 THEN 'early_0to89d'
             WHEN first_ts<15552000 THEN 'middle_90to179d' ELSE 'late_180to269d' END cohort,
        count(*) n,sum(later_like) likes,sum(later_positive) positive,sum(later_dislike) dislikes,
        count(DISTINCT uid) users
      FROM evidence WHERE first_org=0 AND first_ratio<25 GROUP BY 1 ORDER BY 1""").fetchall()
    print("AUDIT_COHORT",cohort,flush=True)
    duration=c.execute("""SELECT
        CASE WHEN duration<120 THEN 'short_song'
             WHEN duration<240 THEN 'medium_song' ELSE 'long_song' END duration_group,
        count(*) n,sum(later_like) likes,sum(later_positive) positive,sum(later_dislike) dislikes
      FROM evidence WHERE first_org=0 AND first_ratio<25 GROUP BY 1 ORDER BY 1""").fetchall()
    print("AUDIT_DURATION",duration,flush=True)
    # User-block bootstrap avoids treating repeats from the same person as independent.
    # CI for positive rates after short recommendation starts; no user IDs exported.
    a=c.execute("""SELECT uid,
      count(*) FILTER(WHERE first_org=0 AND first_ratio<25) short_n,
      coalesce(sum(later_positive) FILTER(WHERE first_org=0 AND first_ratio<25),0) short_positive,
      count(*) FILTER(WHERE first_org=0 AND first_ratio>=90) long_n,
      coalesce(sum(later_positive) FILTER(WHERE first_org=0 AND first_ratio>=90),0) long_positive
      FROM evidence GROUP BY 1""").fetchall()
    import random
    rng=random.Random(20271009)
    pairs=[(int(r[1]),int(r[2]),int(r[3]),int(r[4])) for r in a]
    boot=[]
    for rep in range(240):
        n0=p0=n1=p1=0
        for _ in range(len(pairs)):
            u=pairs[rng.randrange(len(pairs))]
            n0+=u[0];p0+=u[1];n1+=u[2];p1+=u[3]
        if n0 and n1:boot.append((p0/n0,p1/n1,p0/n0-p1/n1))
    def quant(v,q):
        s=sorted(v);return s[min(len(s)-1,int(q*(len(s)-1)))]
    ci={name:[quant([x[i] for x in boot],0.025),quant([x[i] for x in boot],0.975)]
        for i,name in enumerate(("short_positive","long_positive","short_minus_long"))}
    print("AUDIT_CLUSTER_BOOTSTRAP_CI",ci,flush=True)
    audit={"depth":[dict(zip(("source_org","depth","n","like_late","dislike_late","org90_late","positive_late","users","users_with_positive"),r)) for r in detail],
      "cohort":[dict(zip(("cohort","n","late_likes","late_positives","late_dislikes","users"),r)) for r in cohort],
      "duration":[dict(zip(("duration","n","late_likes","late_positives","late_dislikes"),r)) for r in duration],
      "bootstrap_user_cluster_95pct_CI":ci,"bootstrap_reps":len(boot),
      "definition":"Follow-up after at least 1 day and no later than 30 days, with 30d right-censoring excluded",
      "limits":"Later positive actions show initial short listen is not a permanent preference ground truth. Counts do not prove skip button or causal behavior."}
    (out/"stage4_audit.json").write_text(json.dumps(audit,indent=2,ensure_ascii=False))
    print("AUDIT_FINAL",json.dumps(audit,ensure_ascii=False),flush=True)

    result={"source":"Yambda-50M listens+likes","sample":"entire available Yambda-50M listens dataset",
            "cutoff":"30 days observed follow-up at dataset end; timestamp seconds quantized to 5 seconds",
            "stats":stats,"firsts":first_info,"rows":data,
            "users":users,"future_positive":pos,
            "limitations":["observational exposures not skip button events","recommendation exposure not randomized",
            "first observed listen may not be lifetime first","later repeated interaction may be caused by exposures",
            "no UI action or direct preferences shown","naive future-outcome metrics suffer popularity/censoring biases"],
            "note":"Cannot establish user reasons or causal effects."}
    (out/"stage3_results.json").write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print("FINAL_JSON",json.dumps(result,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
