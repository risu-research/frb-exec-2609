#!/usr/bin/env python3
"""Stage 5 independent prospective evidence test.
No claim of actual skip UI actions or deployed user preference labels.
First exposure, 0-7 day evidence, then outcome day 8-38, no temporal leakage.
"""
import json,hashlib,time
from pathlib import Path
import duckdb,requests
BASE="https://huggingface.co/datasets/yandex/yambda/resolve/main/flat/50m/"
FILES={
 "listens":("listens.parquet","eed9cbd094af1e189507d2f8132a0dc9653b90e65480125c7cdccd601e0592d1"),
 "likes":("likes.parquet","694087077dbacfcc1d22a5ca85cc6bd8ab182361933406e60500624c6a422bc4"),
 "dislikes":("dislikes.parquet","64f240a6d62b8acdfa6efae660a54d10ebc64f9f2f0aeeef8e6bb0dbe7dc2802"),
 "undislikes":("undislikes.parquet","8cdbcf6e7e79491d560637057ba8ac078dd1610a3fab15442b6f12e45069ef85"),
}
OUT=Path("hcii_yambda/results_stage5");OUT.mkdir(parents=True,exist_ok=True)
def dl(key):
 name,expected=FILES[key];p=Path("/tmp/hcii_"+name)
 hash=hashlib.sha256()
 print("FETCH",key,flush=True)
 with requests.get(BASE+name+"?download=true",stream=True,timeout=(25,80)) as res:
  print("HTTP",key,res.status_code,res.headers.get("Content-Length"),flush=True)
  res.raise_for_status()
  with p.open("wb") as f:
   for buf in res.iter_content(4*1024*1024):
    if buf:f.write(buf);hash.update(buf)
 if hash.hexdigest()!=expected:raise ValueError(key+" checksum mismatch "+hash.hexdigest())
 print("VERIFIED",key,p.stat().st_size,hash.hexdigest(),flush=True)
 return str(p)
def run():
 path={key:dl(key) for key in FILES}
 c=duckdb.connect()
 c.execute("SET threads=3");c.execute("SET memory_limit='5GB'");c.execute("SET temp_directory='/tmp/hcii_ducktemp'")
 for key,p in path.items():c.execute(f"CREATE VIEW {key} AS SELECT * FROM read_parquet('{p}')")
 max_t=c.execute("SELECT max(timestamp) FROM listens").fetchone()[0]
 c.execute("""CREATE TEMP TABLE f AS SELECT uid,item_id,timestamp AS t0,played_ratio_pct AS first_ratio,
 track_length_seconds AS sec FROM
 (SELECT *,row_number() OVER(PARTITION BY uid,item_id ORDER BY timestamp,is_organic DESC) AS rn,
 count(*) OVER(PARTITION BY uid,item_id,timestamp) AS ntie FROM listens)
 WHERE rn=1 AND ntie=1 AND is_organic=0 AND played_ratio_pct<25
 AND timestamp>=? AND timestamp+38*86400<=?""",[7*86400,max_t])
 print("ANCHORS",c.execute("SELECT count(*),count(DISTINCT uid),min(t0),max(t0) FROM f").fetchone(),flush=True)
 c.execute("""CREATE TEMP TABLE future_listens AS
 SELECT f.uid,f.item_id,
   count(*) FILTER (WHERE l.timestamp>f.t0 AND l.timestamp<=f.t0+7*86400 AND l.played_ratio_pct<25) AS early_short,
   count(*) FILTER (WHERE l.timestamp>f.t0 AND l.timestamp<=f.t0+7*86400 AND l.played_ratio_pct>=90) AS early_high,
   count(*) FILTER (WHERE l.timestamp>f.t0 AND l.timestamp<=f.t0+7*86400 AND l.is_organic=1) AS early_org,
   count(*) FILTER (WHERE l.timestamp>f.t0+7*86400 AND l.timestamp<=f.t0+38*86400
                  AND l.is_organic=1 AND l.played_ratio_pct>=90) AS future_org90,
   count(*) FILTER (WHERE l.timestamp>f.t0+7*86400 AND l.timestamp<=f.t0+38*86400
                  AND l.played_ratio_pct>=90) AS future_any90
 FROM f LEFT JOIN listens l ON f.uid=l.uid AND f.item_id=l.item_id
 AND l.timestamp>f.t0 AND l.timestamp<=f.t0+38*86400
 GROUP BY f.uid,f.item_id""")
 print("LISTEN_JOIN_DONE",flush=True)
 for kind in ["likes","dislikes","undislikes"]:
  c.execute(f"""CREATE TEMP TABLE {kind}_out AS SELECT f.uid,f.item_id,
  count(*) FILTER(WHERE e.timestamp>=f.t0 AND e.timestamp<=f.t0+7*86400) AS early,
  count(*) FILTER(WHERE e.timestamp>f.t0+7*86400 AND e.timestamp<=f.t0+38*86400) AS later
  FROM f JOIN {kind} e ON f.uid=e.uid AND f.item_id=e.item_id
     AND e.timestamp>=f.t0 AND e.timestamp<=f.t0+38*86400
  GROUP BY f.uid,f.item_id""")
  print("JOIN",kind,c.execute("SELECT count(*) FROM "+kind+"_out").fetchone()[0],flush=True)
 c.execute("""CREATE TEMP TABLE eval AS SELECT f.uid,f.item_id,f.t0,f.first_ratio,f.sec,
   coalesce(l.early_short,0) early_short,coalesce(l.early_high,0) early_high,
   coalesce(l.early_org,0) early_org,
   coalesce(a.early,0) early_like,coalesce(d.early,0) early_dislike,
   coalesce(l.future_org90,0) future_org90,coalesce(l.future_any90,0) future_any90,
   coalesce(a.later,0) future_like,coalesce(d.later,0) future_dislike,
   coalesce(u.later,0) future_undislike,
   CASE WHEN f.t0<120*86400 THEN 'earlier'
        WHEN f.t0>=160*86400 THEN 'later_holdout' ELSE 'buffer_120to159' END AS cohort
  FROM f LEFT JOIN future_listens l USING(uid,item_id)
  LEFT JOIN likes_out a USING(uid,item_id)
  LEFT JOIN dislikes_out d USING(uid,item_id)
  LEFT JOIN undislikes_out u USING(uid,item_id)""")
 # Rules defined solely using first 7 days:
 # Baseline: all short first recommendation => negative
 # Repeat: second short AND no positive early
 # Explicit: explicit dislike in early evidence; known early positive may co-occur
 # Evidence state: explicit like or full replay => positive; explicit dislike => negative unless disputed
 # Otherwise abstain. Measures later actions without assuming missing future=negative.
 c.execute("""CREATE TEMP TABLE decisions AS SELECT *,
   CAST(future_like>0 OR future_org90>0 AS INT) AS later_pos,
   CAST(future_dislike>0 AS INT) AS later_neg,
   CAST(early_like>0 OR early_high>0 AS INT) AS early_positive,
   CAST(early_dislike>0 AS INT) AS early_negative,
   CASE WHEN early_like>0 OR early_high>0 THEN 'positive_evidence'
        WHEN early_dislike>0 THEN 'explicit_negative'
        WHEN early_short>0 THEN 'repeat_short_only'
        ELSE 'single_short_or_no_repeat' END evidence_state
 FROM eval""")
 rules=c.execute("""SELECT cohort,evidence_state,count(*) AS anchors,
   sum(later_pos) AS future_positive,
   sum(CAST(future_like>0 AS INT)) AS later_explicit_like,
   sum(CAST(future_org90>0 AS INT)) AS later_voluntary_full,
   sum(later_neg) AS future_explicit_dislike,
   sum(CAST(future_undislike>0 AS INT)) AS future_revoke_dislike,
   count(DISTINCT uid) AS users,
   avg(first_ratio) AS first_play_pct
 FROM decisions GROUP BY 1,2 ORDER BY 1,2""").fetchall()
 print("POLICY_GROUPS",rules,flush=True)
 firstdepth=c.execute("""SELECT cohort,
    CASE WHEN first_ratio<10 THEN 'lt10' ELSE '10to24' END depth,
    count(*) n,sum(later_pos) future_pos,sum(later_neg) future_dislike,
    count(*) FILTER(WHERE early_dislike>0) early_explicit_dislike,
    count(*) FILTER(WHERE early_short>0) repeated_short
    FROM decisions GROUP BY 1,2 ORDER BY 1,2""").fetchall()
 print("DEPTH_HOLDOUT",firstdepth,flush=True)
 summary=c.execute("""SELECT cohort,count(*) n,count(DISTINCT uid) users,
    sum(later_pos) future_positive,
    sum(later_neg) future_negative,
    sum(CAST(early_short>0 AS INT)) repeated_short,
    sum(CAST(early_dislike>0 AS INT)) explicit_negative_early,
    sum(CAST(early_like>0 OR early_high>0 AS INT)) positive_early,
    sum(CAST(later_pos=1 AND early_dislike>0 AS INT)) future_positive_after_explicit_dislike,
    sum(CAST(later_pos=1 AND early_short>0 AS INT)) future_positive_after_repeat_short,
    sum(CAST(later_pos=1 AND early_like=0 AND early_high=0 AND early_dislike=0 AS INT))
     future_positive_with_no_explicit_evidence
    FROM decisions GROUP BY 1 ORDER BY 1""").fetchall()
 print("SUMMARY",summary,flush=True)
 quality=c.execute("""SELECT count(*) count_pairs,
  count(*) FILTER(WHERE future_like>0 AND future_dislike>0) late_both_like_dislike,
  count(*) FILTER(WHERE early_like>0 AND early_dislike>0) early_both_like_dislike,
  count(*) FILTER(WHERE early_dislike>0 AND future_undislike>0) early_dislike_future_undislike
  FROM decisions""").fetchone()
 print("QUALITY",quality,flush=True)
 out={"dataset_sha":{k:v[1] for k,v in FILES.items()},
  "design":"first observed unique recommendation listening <25%; 7 days of evidence; later 31 days outcomes; enforce >=38d follow-up; no future in policies",
  "timestamp_seconds":True,"max_t":max_t,
  "policy_rows":[dict(zip(["cohort","state","n","future_positive","future_like","future_organic90","future_dislike","future_undislike","users","first_play_mean"],r)) for r in rules],
  "depth_rows":[dict(zip(["cohort","depth","n","future_positive","future_dislike","early_dislike","repeat_short"],r)) for r in firstdepth],
  "cohort_summary":[dict(zip(["cohort","n","users","future_positive","future_dislike","repeat_short","early_dislike","early_positive","later_positive_after_dislike","later_positive_after_repeat","later_positive_without_strong_evidence"],r)) for r in summary],
  "quality":{"pairs":quality[0],"both_later_like_dislike":quality[1],"both_early_like_dislike":quality[2],"early_dislike_later_undislike":quality[3]},
  "limitations":["not skip button events","no proof policies implemented on service","future positive proxy; absence of positive not evidence of dislike",
   "first observed is not first lifetime encounter","no randomized recommendation assignment",
   "user selection based on future activity and data are truncated at observation end",
   "observational policy comparison, not causal intervention"]}
 (OUT/"stage5_prospective.json").write_text(json.dumps(out,ensure_ascii=False,indent=2))
 print("FINAL_JSON",json.dumps(out,ensure_ascii=False),flush=True)
if __name__=="__main__":run()
