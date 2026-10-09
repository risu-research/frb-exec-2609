#!/usr/bin/env python3
"""Deezer Ex2Vec external descriptive replication.
y=0 means <=80% playback, not "skip button" or unlike.
Dataset chosen in original paper to study repeat exposure: conditional sample!
"""
import json,hashlib
from pathlib import Path
import duckdb,requests
URL="https://zenodo.org/records/8316236/files/new_release_stream.csv?download=1"
EXPECTED="5e9b3929b3451cbc9b947bcefb8c9020"
P=Path("/tmp/deezer_ex2vec.csv")
OUT=Path("hcii_yambda/results_external");OUT.mkdir(parents=True,exist_ok=True)
def main():
 h=hashlib.md5()
 with requests.get(URL,timeout=(25,90),stream=True) as r:
  print("DOWNLOAD_HTTP",r.status_code,"CONTENT_LENGTH",r.headers.get("Content-Length"),flush=True)
  r.raise_for_status()
  with P.open("wb") as f:
   for buf in r.iter_content(2*1024*1024):
    if buf:f.write(buf);h.update(buf)
 print("DOWNLOAD_MD5",h.hexdigest(),"BYTES",P.stat().st_size,flush=True)
 if h.hexdigest()!=EXPECTED:raise ValueError("Official checksum mismatch")
 c=duckdb.connect()
 c.execute("SET threads=4")
 c.execute(f"CREATE VIEW d AS SELECT * FROM read_csv_auto('{P}',header=True)")
 schema=c.execute("DESCRIBE d").fetchall()
 print("SCHEMA",schema,flush=True)
 assert {"userId","itemId","timestamp","y"}.issubset({x[0] for x in schema})
 shape=c.execute("SELECT count(*),count(DISTINCT userId),count(DISTINCT itemId),min(timestamp),max(timestamp),avg(y) FROM d").fetchone()
 print("DATA_SHAPE",shape,flush=True)
 # Drop tied first-time cases (cannot choose unambiguously).
 c.execute("""CREATE TEMP TABLE first_events AS SELECT userId,itemId,timestamp AS t0,y first_y
 FROM (SELECT *,row_number() OVER(PARTITION BY userId,itemId ORDER BY timestamp,y) rn,
 count(*) OVER(PARTITION BY userId,itemId,timestamp) first_time_ties FROM d)
 WHERE rn=1 AND first_time_ties=1 AND timestamp+30*86400<=?""",[shape[4]])
 c.execute("""CREATE TEMP TABLE repeats AS
 SELECT f.userId,f.itemId,f.first_y,
   count(*) FILTER(WHERE d.timestamp>f.t0 AND d.timestamp<=f.t0+30*86400) future_plays,
   count(*) FILTER(WHERE d.timestamp>=f.t0+86400 AND d.timestamp<=f.t0+30*86400) later_plays,
   count(*) FILTER(WHERE d.timestamp>=f.t0+86400 AND d.timestamp<=f.t0+30*86400 AND d.y=1) later_high,
   count(*) FILTER(WHERE d.timestamp>=f.t0+86400 AND d.timestamp<=f.t0+30*86400 AND d.y=0) later_low
 FROM first_events f LEFT JOIN d ON d.userId=f.userId AND d.itemId=f.itemId
 AND d.timestamp>f.t0 AND d.timestamp<=f.t0+30*86400
 GROUP BY f.userId,f.itemId,f.first_y""")
 rows=c.execute("""SELECT first_y,count(*) n, count(DISTINCT userId) users,
 count(*) FILTER (WHERE later_plays>0) later_any,
 count(*) FILTER (WHERE later_high>0) later_high,
 count(*) FILTER (WHERE later_low>0) later_low,
 count(*) FILTER (WHERE later_high>0 AND later_low>0) later_both
 FROM repeats GROUP BY 1 ORDER BY 1""").fetchall()
 print("REPLICATION_30D",rows,flush=True)
 # Separate repeat-conditioned comparisons from whole cohort.
 rows2=c.execute("""SELECT first_y,
 count(*) FILTER(WHERE future_plays>0) any_repeated,
 count(*) FILTER(WHERE future_plays>0 AND later_high>0) later_high_given_repeated
 FROM repeats GROUP BY 1 ORDER BY 1""").fetchall()
 print("REPEAT_CONDITIONED",rows2,flush=True)
 results={"dataset":"Deezer Ex2Vec new_release_stream.csv","zenodo":"10.5281/zenodo.8316236",
  "md5":EXPECTED,"row_count":shape[0],"users":shape[1],"tracks":shape[2],
  "time_span_seconds":shape[4]-shape[3],"first_pair_30day_outcomes":[dict(zip(["first_over80pct","n","users","later_any","later_over80","later_under80","both_later"],r)) for r in rows],
  "repeat_conditional":[dict(zip(["first_over80pct","any_repeated","later_over80_given_repeated"],r)) for r in rows2],
  "limitations":["Not same skip threshold as Yambda: Deezer <=80%, Yambda <25%","No recommendation vs organic flag","No explicit like/dislike","First observed event not lifetime first","Dataset specifically built for repeat-exposure research; cannot generalize","No proof playback was manual or user disliked content","30-day follow-up restricted"]}
 (OUT/"deezer_replication.json").write_text(json.dumps(results,indent=2))
 print("FINAL_JSON",json.dumps(results),flush=True)
if __name__=="__main__":main()
