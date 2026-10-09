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
OUT=Path("hcii_yambda/results_stage8b");OUT.mkdir(parents=True,exist_ok=True)
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
 AND timestamp>=? AND timestamp+38*86400<=?""",[28*86400,max_t])
 print("ANCHORS",c.execute("SELECT count(*),count(DISTINCT uid),min(t0),max(t0) FROM f").fetchone(),flush=True)
 c.execute("""CREATE TEMP TABLE future_listens AS
 SELECT f.uid,f.item_id,
   count(*) FILTER (WHERE l.timestamp>f.t0 AND l.timestamp<=f.t0+7*86400 AND l.played_ratio_pct<25) AS early_short,
   count(*) FILTER (WHERE l.timestamp>f.t0 AND l.timestamp<=f.t0+7*86400 AND l.played_ratio_pct>=90) AS early_high,
   count(*) FILTER (WHERE l.timestamp>f.t0 AND l.timestamp<=f.t0+7*86400 AND l.is_organic=1) AS early_org,
   count(*) FILTER (WHERE l.timestamp>f.t0+7*86400 AND l.timestamp<=f.t0+38*86400) AS future_replays,
   count(*) FILTER (WHERE l.timestamp>f.t0+7*86400 AND l.timestamp<=f.t0+38*86400 AND l.is_organic=1) AS future_organic_replays,
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
   coalesce(l.future_replays,0) future_replays,
   coalesce(l.future_organic_replays,0) future_organic_replays,
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


 # Data to make opportunity adjustments based only on historical observations BEFORE first exposure.
 # Whole completed calendar-free 7-day bins; current incomplete week is excluded.
 c.execute("CREATE TEMP TABLE user_week AS SELECT uid,CAST(FLOOR(timestamp/604800) AS INTEGER) w,count(*) n FROM listens GROUP BY 1,2")
 c.execute("CREATE TEMP TABLE item_week AS SELECT item_id,CAST(FLOOR(timestamp/604800) AS INTEGER) w,count(*) n FROM listens GROUP BY 1,2")
 c.execute("CREATE TEMP TABLE anchor_week AS SELECT uid,item_id,CAST(FLOOR(t0/604800) AS INTEGER) w FROM f")
 print("HISTORY_TABLES",c.execute("SELECT count(*) FROM user_week").fetchone(),c.execute("SELECT count(*) FROM item_week").fetchone(),flush=True)
 c.execute("""CREATE TEMP TABLE preuser AS SELECT a.uid,a.item_id,
   coalesce(sum(uw.n),0) pre_user_listens FROM anchor_week a
   LEFT JOIN user_week uw ON a.uid=uw.uid AND uw.w BETWEEN a.w-4 AND a.w-1
   GROUP BY a.uid,a.item_id""")
 print("PREUSER_DONE",flush=True)
 c.execute("""CREATE TEMP TABLE preitem AS SELECT a.uid,a.item_id,
   coalesce(sum(iw.n),0) pre_item_listens FROM anchor_week a
   LEFT JOIN item_week iw ON a.item_id=iw.item_id AND iw.w BETWEEN a.w-4 AND a.w-1
   GROUP BY a.uid,a.item_id""")
 print("PREITEM_DONE",flush=True)
 c.execute("""CREATE TEMP TABLE feature_base AS SELECT d.*, 
    coalesce(pu.pre_user_listens,0) pre_user_listens,
    coalesce(pi.pre_item_listens,0) pre_item_listens,
    CAST(FLOOR(d.t0/604800) AS INTEGER) wk,
    CAST(future_like>0 OR future_org90>0 AS INT) pos_later,
    CAST(future_like>0 AS INT) like_later
   FROM decisions d LEFT JOIN preuser pu USING(uid,item_id)
     LEFT JOIN preitem pi USING(uid,item_id)
   WHERE cohort IN ('earlier','later_holdout')""")
 c.execute("""CREATE TEMP TABLE features AS SELECT *,
  NTILE(4) OVER (PARTITION BY cohort ORDER BY pre_user_listens,hash(uid,item_id)) AS user_quartile,
  NTILE(4) OVER (PARTITION BY cohort ORDER BY pre_item_listens,hash(uid,item_id)) AS item_quartile,
  CASE WHEN t0<120*86400 THEN CAST(FLOOR(t0/(30*86400)) AS INTEGER)
   ELSE CAST(FLOOR((t0-160*86400)/(30*86400)) AS INTEGER) END AS month_quart
 FROM feature_base""")
 n=c.execute("""SELECT cohort,count(*) n,count(DISTINCT uid) users,
 avg(pre_user_listens) mean_pre_user,avg(pre_item_listens) mean_pre_item,
 sum(pos_later) positive FROM features GROUP BY 1 ORDER BY 1""").fetchall()
 print("FEATURE_COHORTS",n,flush=True)
 train_state=c.execute("""SELECT evidence_state,count(*) AS n,
    avg(CAST(pos_later AS DOUBLE)) future_positive_rate
    FROM features WHERE cohort='earlier' GROUP BY 1
    ORDER BY future_positive_rate ASC""").fetchall()
 print("LEARNED_STATE_ORDER",train_state,flush=True)
 rank_map={row[0]:i for i,row in enumerate(train_state)}
 rank_case="CASE "+" ".join(f"WHEN evidence_state='{k}' THEN {v}" for k,v in rank_map.items())+" ELSE 99 END"
 select_rows=[]
 for scheme,part in [
   ("unadjusted","cohort"),
   ("within_user","cohort,uid"),
   ("prior_user_and_item_activity","cohort,user_quartile,item_quartile,month_quart"),
   ("within_user_and_item_popularity","cohort,uid,item_quartile")
 ]:
  for policy,order in [
   ("playback","first_ratio ASC,hash(uid,item_id)"),
   ("repeat_penalty","early_short DESC,first_ratio ASC,hash(uid,item_id)"),
   ("explicit_only","CAST(early_dislike>0 AND early_like=0 AND early_high=0 AS INT) DESC,first_ratio ASC,hash(uid,item_id)"),
   ("evidence","("+rank_case+") ASC,first_ratio ASC,hash(uid,item_id)")
  ]:
   sql=f"""WITH ordered AS
     (SELECT *,ROW_NUMBER() OVER(PARTITION BY {part} ORDER BY {order}) rn,
      COUNT(*) OVER(PARTITION BY {part}) group_n
      FROM features WHERE cohort='later_holdout'),
    chosen AS 
     (SELECT * FROM ordered WHERE rn<=GREATEST(1,CAST(FLOOR(group_n*0.20) AS BIGINT)))
    SELECT count(*) n,sum(pos_later) later_positive,
       sum(like_later) later_likes,
       sum(CAST(future_dislike>0 AS INT)) later_dislikes,
       sum(CAST(future_org90>0 AS INT)) later_org90,
       sum(CAST(future_replays>0 AS INT)) with_reexposure,
       sum(CAST(pos_later=1 AND future_replays>0 AS INT)) positives_when_reexposed,
       avg(pre_user_listens) avg_prior_user_listens,
       avg(pre_item_listens) avg_prior_item_listens,
       avg(CAST(early_dislike>0 AS INT)) explicit_dislike_fraction,
       count(DISTINCT uid) selected_users
    FROM chosen"""
   row=c.execute(sql).fetchone()
   d=dict(zip(["selected","later_positive","later_likes","later_dislikes","later_org90","reexposed","positives_reexposed","pre_user_avg","pre_item_avg","explicit_negative_fraction","selected_users"],row))
   d.update({"scheme":scheme,"policy":policy,"coverage":d["selected"]/next(n0[1] for n0 in n if n0[0]=="later_holdout")})
   d["positive_rate"]=d["later_positive"]/d["selected"]
   d["like_rate"]=d["later_likes"]/d["selected"]
   d["dislike_rate"]=d["later_dislikes"]/d["selected"]
   d["like_share_among_explicit"]=d["later_likes"]/(d["later_likes"]+d["later_dislikes"]) if (d["later_likes"]+d["later_dislikes"]) else None
   d["reexposure_rate"]=d["reexposed"]/d["selected"]
   d["positive_among_reexposed"]=d["positives_reexposed"]/d["reexposed"] if d["reexposed"] else None
   select_rows.append(d)
   print("COMPARISON",json.dumps(d,ensure_ascii=False),flush=True)
 
 # Single decisive audit. SAME user and item-popularity cell, same number selected.
 # Study future explicit positive AND negative feedback, not just non-observation.
 c.execute(f"""CREATE TEMP TABLE contrasted AS
    SELECT uid,item_id,pos_later,like_later,
      CAST(future_dislike>0 AS INT) dislike_later,
      CAST(future_replays>0 AS INT) later_replay,
      row_number() OVER (PARTITION BY uid,item_quartile ORDER BY first_ratio ASC,hash(uid,item_id)) play_rank,
      row_number() OVER (PARTITION BY uid,item_quartile ORDER BY {rank_case} ASC,first_ratio ASC,hash(uid,item_id)) evidence_rank,
      row_number() OVER (PARTITION BY uid,item_quartile ORDER BY CAST(early_dislike>0 AND early_like=0 AND early_high=0 AS INT) DESC,first_ratio ASC,hash(uid,item_id)) explicit_rank,
      count(*) OVER (PARTITION BY uid,item_quartile) group_n
      FROM features WHERE cohort='later_holdout'""")
 user_pairs=c.execute("""SELECT uid,
  count(*) FILTER(WHERE play_rank<=GREATEST(1,FLOOR(group_n*0.20))) p_n,
  coalesce(sum(pos_later) FILTER(WHERE play_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) p_pos,
  coalesce(sum(like_later) FILTER(WHERE play_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) p_like,
  coalesce(sum(dislike_later) FILTER(WHERE play_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) p_dislike,
  coalesce(sum(later_replay) FILTER(WHERE play_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) p_replay,
  count(*) FILTER(WHERE evidence_rank<=GREATEST(1,FLOOR(group_n*0.20))) e_n,
  coalesce(sum(pos_later) FILTER(WHERE evidence_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) e_pos,
  coalesce(sum(like_later) FILTER(WHERE evidence_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) e_like,
  coalesce(sum(dislike_later) FILTER(WHERE evidence_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) e_dislike,
  coalesce(sum(later_replay) FILTER(WHERE evidence_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) e_replay,
  count(*) FILTER(WHERE explicit_rank<=GREATEST(1,FLOOR(group_n*0.20))) x_n,
  coalesce(sum(pos_later) FILTER(WHERE explicit_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) x_pos,
  coalesce(sum(like_later) FILTER(WHERE explicit_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) x_like,
  coalesce(sum(dislike_later) FILTER(WHERE explicit_rank<=GREATEST(1,FLOOR(group_n*0.20))),0) x_dislike
  FROM contrasted GROUP BY 1""").fetchall()
 print("USER_CLUSTER_COUNT",len(user_pairs),flush=True)
 import random
 rng=random.Random(20261009)
 recs=[list(map(int, u[1:])) for u in user_pairs]
 samples=[]
 for _ in range(350):
  totals=[0]*len(recs[0])
  for i in range(len(recs)):
   row=recs[rng.randrange(len(recs))]
   for j,val in enumerate(row): totals[j]+=val
  # p_n,p_pos,p_like,p_dislike,p_replay,e_n,e_pos,e_like,e_dislike,e_replay,x_n,x_pos,x_like,x_dislike
  p_pos=totals[1]/totals[0];e_pos=totals[6]/totals[5];x_pos=totals[11]/totals[10]
  p_exp_pos=totals[2]/(totals[2]+totals[3]);e_exp_pos=totals[7]/(totals[7]+totals[8])
  samples.append([p_pos-e_pos,x_pos-e_pos,p_exp_pos-e_exp_pos,p_pos,e_pos,x_pos,
      totals[4]/totals[0]-totals[9]/totals[5]])
 def ci(k):
  a=sorted(x[k] for x in samples)
  return [a[int(0.025*(len(a)-1))],a[int(0.975*(len(a)-1))]]
 ci_data={"bootstrap_reps":len(samples),"user_clusters":len(recs),
    "play_minus_evidence_future_positive":ci(0),
    "explicit_only_minus_evidence_future_positive":ci(1),
    "play_minus_evidence_like_share_among_explicit_feedback":ci(2),
    "play_risk":ci(3),"evidence_risk":ci(4),"explicit_only_risk":ci(5),
    "play_minus_evidence_future_replay_rate":ci(6)}
 print("USER_CLUSTER_BOOTSTRAP",json.dumps(ci_data),flush=True)
 (OUT/"stage8b_cluster_bootstrap.json").write_text(json.dumps(ci_data,indent=2))

 # Directly standardized over matched historical strata using 4x4 historical activity bins;
 # no future re-exposure is used to construct selected candidates or assignment.
 c.execute("CREATE TEMP TABLE full_groups AS SELECT cohort,user_quartile,item_quartile,month_quart,COUNT(*) n FROM features WHERE cohort='later_holdout' GROUP BY 1,2,3,4")
 # Within-user comparison allows algorithm candidates to have same user distribution by construction.
 # Yet opportunity conditional analyses on future replays remain collider-selected.
 result={"dataset":"Yambda 50M, listens/likes/dislikes/undislikes official Sha256",
   "original_sha256":{k:v[1] for k,v in FILES.items()},
   "design":"First unique recommendation listen below 25%, anchor >=28days, 7day input, 31day later evaluation, earlier vs later temporal split",
   "coverage_target":0.20,"history_definition":"user and song total listening across preceding four complete 7-day bins; excludes week of anchor event",
   "later_reexposure_is_postdecision":True,
   "train_evidence_state_order":[{"name":a,"train_n":b,"future_positive_rate":d} for a,b,d in train_state],
   "cohorts":[dict(zip(["cohort","pairs","users","mean_pre_user","mean_pre_item","future_positive"],r)) for r in n],
   "results":select_rows,"user_cluster_bootstrap":ci_data,
   "interpretation_cautions":["Not proof that user disliked song","No causal policy effect","Outcome partly dependent on later opportunity to replay","Conditioning on later replay is a postdecision selection, diagnostic only","A single earlier/late temporal split shares users","No actual recommendation removal or intervention","All policies use 7 days early evidence except initial playback",
     "Explicit-only policy is a strong non-novel baseline"]
   }
 (OUT/"stage8b_signed_feedback_audit.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print("STAGE8B_COMPLETE",json.dumps({"rows":len(select_rows),"cohorts":result["cohorts"],"state_order":result["train_evidence_state_order"]},ensure_ascii=False),flush=True)
if __name__=="__main__":run()
