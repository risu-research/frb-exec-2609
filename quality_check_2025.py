YEAR=2025
"""Event-level reliability-tail audit on public regulator records."""
import hashlib, json, math, requests, duckdb
from pathlib import Path
OUT=Path("audit_output"); OUT.mkdir(exist_ok=True)
API="https://dadosabertos.aneel.gov.br/api/3/action/package_show"
S=requests.Session()
S.headers["User-Agent"]="OpenDatasetQualityAudit/1.0"
FILES=[
 ("outages","interrupcoes-de-energia-eletrica-nas-redes-de-distribuicao","interrupcoes-energia-eletrica-2025.parquet"),
 ("indicators","indicadores-coletivos-de-continuidade-dec-e-fec","indicadores-continuidade-coletivos-2020-2029.parquet")
]
manifest={}
for name,dataset,resource_name in FILES:
 r=S.get(API,params={"id":dataset},timeout=45);r.raise_for_status()
 matches=[x for x in r.json()["result"]["resources"] if x.get("name","").lower()==resource_name]
 if len(matches)!=1:raise ValueError("Source name not unique: "+resource_name)
 x=matches[0]; dest=Path(name+".parquet"); digest=hashlib.sha256()
 with S.get(x["url"],stream=True,timeout=(30,240)) as response:
  response.raise_for_status()
  with dest.open("wb") as fh:
   for chunk in response.iter_content(2*1024*1024):
    if chunk:fh.write(chunk);digest.update(chunk)
 manifest[name]={"url":x["url"],"name":x["name"],"bytes":dest.stat().st_size,"sha256":digest.hexdigest()}
 print("DOWNLOAD",name,dest.stat().st_size,flush=True)
db=duckdb.connect()
db.execute("SET memory_limit='3GB'")
db.execute("SET threads=2")
for f in ["outages","indicators"]:
 schema=db.execute(f"DESCRIBE SELECT * FROM read_parquet('{f}.parquet')").fetchall()
 print("SCHEMA",f,json.dumps([x[0] for x in schema]),flush=True)
# The 2025 Parquet uses the 2022 legacy column names; validate rather than silently remap.
required=['IdeConjuntoUnidadeConsumidora','NumCPFCNPJ','DatInicioInterrupcao','DatFimInterrupcao','NumUnidadeConsumidora','NumConsumidorConjunto','IdeMotivoInterrupcao','NumOrdemInterrupcao']
columns={x[0] for x in db.execute("DESCRIBE SELECT * FROM read_parquet('outages.parquet')").fetchall()}
assert all(x in columns for x in required), set(required)-columns
db.execute("""
CREATE TABLE e AS
WITH base AS (
 SELECT LPAD(CAST(NumCPFCNPJ AS VARCHAR),14,'0') AS cnpj,
        CAST(IdeConjuntoUnidadeConsumidora AS VARCHAR) AS area,
        EXTRACT(YEAR FROM DatInicioInterrupcao)::INTEGER AS yr,
        EXTRACT(MONTH FROM DatInicioInterrupcao)::INTEGER AS mo,
        NumOrdemInterrupcao AS event_id,
        TRY_CAST(IdeMotivoInterrupcao AS INTEGER) AS exclusion,
        TRY_CAST(NumUnidadeConsumidora AS DOUBLE) AS affected,
        TRY_CAST(NumConsumidorConjunto AS DOUBLE) AS active,
        DatInicioInterrupcao AS start_time,
        DatFimInterrupcao AS end_time,
        DATE_DIFF('second', DatInicioInterrupcao,DatFimInterrupcao)/3600.0 AS hours
 FROM read_parquet('outages.parquet')
)
SELECT *, (affected*hours) AS customer_hours
FROM base
WHERE yr=2025 AND hours > 0 AND hours <= 744
  AND affected > 0 AND cnpj IS NOT NULL AND area IS NOT NULL
""")
raw=db.execute("""
SELECT COUNT(*) AS raw_rows,
 COUNT(*) FILTER (WHERE DatInicioInterrupcao IS NULL OR DatFimInterrupcao IS NULL) AS null_dates,
 COUNT(*) FILTER (WHERE DatFimInterrupcao<=DatInicioInterrupcao) AS nonpositive_time,
 COUNT(*) FILTER (WHERE DATE_DIFF('second',DatInicioInterrupcao,DatFimInterrupcao)>744*3600) AS gt31d,
 COUNT(*) FILTER (WHERE NumUnidadeConsumidora IS NULL OR NumUnidadeConsumidora<=0) AS invalid_affected,
 COUNT(*) FILTER (WHERE NumUnidadeConsumidora>NumConsumidorConjunto AND NumConsumidorConjunto>0) AS over_active,
 COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM DatInicioInterrupcao)!=2025) AS outside_start_year,
 COUNT(DISTINCT (NumCPFCNPJ, IdeConjuntoUnidadeConsumidora, NumOrdemInterrupcao)) AS distinct_company_area_order
FROM read_parquet('outages.parquet')
""").df().iloc[0].to_dict()
raw={k:int(v) for k,v in raw.items()};print("RAW_DIAGNOSTICS",json.dumps(raw),flush=True)
tot=db.execute("""
SELECT COUNT(*) AS n, COUNT(DISTINCT cnpj) AS utilities,COUNT(DISTINCT (cnpj,area)) AS areas,
 COUNT(DISTINCT (cnpj,area,mo)) AS area_months,
 SUM(affected) AS occurrences,SUM(customer_hours) AS ch,
 MEDIAN(hours) AS median_duration,
 MAX(hours) AS maximum_hours,
 COUNT(*) FILTER(WHERE exclusion=0) AS nonexcluded_rows,
 COUNT(*) FILTER(WHERE exclusion IS NULL) AS null_exclusion
FROM e
""").df().iloc[0].to_dict()
tot={k:(int(v) if k in ("n","utilities","areas","area_months","nonexcluded_rows","null_exclusion") else float(v)) for k,v in tot.items()}
print("VALID_SAMPLE",json.dumps(tot),flush=True)
thresholds=[]
for scope,where in [("all","TRUE"),("nonexcluded","exclusion=0"),("excluded","exclusion<>0")]:
 for h in [8,12,24,48]:
  z=db.execute(f"""
   SELECT COUNT(*) AS n, SUM(customer_hours) AS ch, SUM(affected) AS occ,
     COUNT(*) FILTER(WHERE hours>={h}) AS tail_rows,
     SUM(customer_hours) FILTER(WHERE hours>={h}) AS tail_ch,
     SUM(affected) FILTER(WHERE hours>={h}) AS tail_occ
   FROM e WHERE {where}""").df().iloc[0]
  item={"scope":scope,"threshold_hours":h}
  for k in z.index:item[k]=None if z[k] is None else float(z[k])
  item["tail_record_pct"]=100*item["tail_rows"]/item["n"] if item["n"] else None
  item["tail_customerhours_pct"]=100*item["tail_ch"]/item["ch"] if item["ch"] else None
  item["tail_occurrences_pct"]=100*item["tail_occ"]/item["occ"] if item["occ"] else None
  thresholds.append(item)
print("TAIL_SUMMARY",json.dumps(thresholds),flush=True)
excluded=db.execute("""
SELECT exclusion, COUNT(*) AS n, SUM(customer_hours) AS customer_hours,
  SUM(customer_hours) FILTER (WHERE hours>=24) AS ch24,
  COUNT(*) FILTER(WHERE hours>=24) AS n24
FROM e GROUP BY exclusion ORDER BY customer_hours DESC
""").df().fillna(-1).to_dict(orient="records")
print("EXCLUSION_DISTRIBUTION",json.dumps(excluded,default=str),flush=True)
# Count repeated event IDs; any repetition can represent legitimately affected feeder/area records.
repeats=db.execute("""
SELECT COUNT(*) AS repeated_event_keys, SUM(cnt) AS rows_in_repeated_keys
FROM (SELECT cnpj, event_id, COUNT(*) AS cnt FROM e GROUP BY cnpj,event_id HAVING COUNT(*)>1)
""").df().iloc[0].to_dict()
print("REPEATED_INTERRUPTION_IDS",json.dumps(repeats,default=str),flush=True)
# Summarize by geographic regulatory area-month without collapsing distinct interruption rows.
db.execute("""
CREATE TABLE a AS SELECT cnpj,area,mo,
 COUNT(*) AS record_rows,
 MAX(active) AS max_active,
 MEDIAN(active) AS median_active,
 SUM(customer_hours) AS ch_all,
 SUM(affected) AS occ_all,
 SUM(customer_hours) FILTER(WHERE exclusion=0) AS ch_notexcluded,
 SUM(affected) FILTER(WHERE exclusion=0) AS occ_notexcluded,
 SUM(customer_hours) FILTER(WHERE hours>=8) AS ch8,
 SUM(customer_hours) FILTER(WHERE hours>=12) AS ch12,
 SUM(customer_hours) FILTER(WHERE hours>=24) AS ch24,
 SUM(customer_hours) FILTER(WHERE hours>=24 AND exclusion=0) AS ch24_notexcluded,
 SUM(affected) FILTER(WHERE hours>=24) AS occ24,
 COUNT(*) FILTER(WHERE hours>=24) AS n24
 FROM e GROUP BY cnpj,area,mo
""")
db.execute("""COPY
 (SELECT * FROM a ORDER BY cnpj,area,mo)
 TO 'audit_output/area_months_2025.csv' (HEADER,DELIMITER ',')
""")
# Official series: year, month, company and area, with published indicator type.
fields={x[0] for x in db.execute("DESCRIBE SELECT * FROM read_parquet('indicators.parquet')").fetchall()}
need=['NumCNPJ','IdeConjUndConsumidoras','SigIndicador','AnoIndice','NumPeriodoIndice','VlrIndiceEnviado']
assert all(x in fields for x in need),set(need)-fields
db.execute("""
CREATE TABLE o AS
SELECT LPAD(REGEXP_REPLACE(CAST(NumCNPJ AS VARCHAR),'[^0-9]','','g'),14,'0') AS cnpj,
  CAST(TRY_CAST(IdeConjUndConsumidoras AS BIGINT) AS VARCHAR) AS area,
  TRY_CAST(NumPeriodoIndice AS INTEGER) AS mo,
  UPPER(TRIM(CAST(SigIndicador AS VARCHAR))) AS indicator,
  TRY_CAST(VlrIndiceEnviado AS DOUBLE) AS value
FROM read_parquet('indicators.parquet')
WHERE TRY_CAST(AnoIndice AS INTEGER)=2025
""")
inventory=db.execute("""
 SELECT indicator,COUNT(*) AS n,COUNT(DISTINCT mo) AS n_months,MIN(mo) AS min_mo,MAX(mo) AS max_mo
 FROM o GROUP BY indicator ORDER BY n DESC
""").df().to_dict(orient="records")
print("INDICATOR_INVENTORY",json.dumps(inventory,default=str),flush=True)
official_duplicates=db.execute("""
 SELECT COUNT(*) AS duplicate_keys, SUM(n) AS duplicate_rows
 FROM (SELECT cnpj,area,mo,indicator,COUNT(*) AS n FROM o
       WHERE indicator IN ('DEC','FEC') AND mo BETWEEN 1 AND 12
       GROUP BY 1,2,3,4 HAVING COUNT(*)>1)
""").df().iloc[0].to_dict()
print("OFFICIAL_DUPLICATES",json.dumps(official_duplicates,default=str),flush=True)
# Only unambiguous monthly DEC/FEC indicator values included.
db.execute("""
CREATE TABLE official_area AS
WITH unique_indicator AS (
 SELECT cnpj,area,mo,indicator,MAX(value) AS value
 FROM o WHERE indicator IN ('DEC','FEC') AND mo BETWEEN 1 AND 12
 GROUP BY 1,2,3,4 HAVING COUNT(*)=1
)
SELECT cnpj,area,mo,
 MAX(value) FILTER(WHERE indicator='DEC') AS dec,
 MAX(value) FILTER(WHERE indicator='FEC') AS fec
FROM unique_indicator GROUP BY 1,2,3
""")
db.execute("""
CREATE TABLE combined AS
SELECT a.*, o.dec,o.fec,
 CASE WHEN ch_all>0 THEN ch24/ch_all END AS tail24_share,
 CASE WHEN max_active>0 THEN ch_notexcluded/max_active END AS approx_dec,
 CASE WHEN max_active>0 THEN occ_notexcluded/max_active END AS approx_fec
FROM a JOIN official_area o USING(cnpj,area,mo)
""")
joinstats=db.execute("""
SELECT (SELECT COUNT(*) FROM a) AS event_area_months,
(SELECT COUNT(*) FROM official_area) AS official_area_months,
COUNT(*) AS inner_join_area_months,
COUNT(*) FILTER(WHERE dec IS NOT NULL) AS matched_dec,
COUNT(*) FILTER(WHERE fec IS NOT NULL) AS matched_fec,
COUNT(DISTINCT (cnpj,area)) AS matched_areas,
COUNT(DISTINCT cnpj) AS matched_utilities,
CORR(approx_dec,dec) AS approx_dec_correlation,
CORR(approx_fec,fec) AS approx_fec_correlation
FROM combined
""").df().iloc[0].to_dict()
print("JOIN_COVERAGE",json.dumps(joinstats,default=str),flush=True)
# Monthly scatter: monthly DEC and long-event share might exhibit sharp divergence.
summary=db.execute("""
WITH p AS (
 SELECT *, NTILE(4) OVER (ORDER BY dec) AS dec_quartile FROM combined
 WHERE dec IS NOT NULL AND ch_all>0 AND max_active>=1000
)
SELECT dec_quartile,COUNT(*) AS n,MEDIAN(dec) AS median_dec,
MEDIAN(tail24_share) AS median_ch24_share,
AVG(tail24_share) AS mean_ch24_share,
COUNT(*) FILTER(WHERE tail24_share>=0.5) AS area_months_majority_24h
FROM p GROUP BY 1 ORDER BY 1
""").df().to_dict(orient="records")
print("DEC_QUARTILES_AND_TAIL",json.dumps(summary,default=str),flush=True)
# Annual area aggregates for subsequent official benchmarking.
db.execute("""
COPY (SELECT cnpj,area,COUNT(*) AS observed_months,
  SUM(ch_all) AS ch_all,SUM(ch8) AS ch8,SUM(ch12) AS ch12,SUM(ch24) AS ch24,
  SUM(ch_notexcluded) AS ch_notexcluded,
  SUM(dec) AS summed_monthly_dec,SUM(fec) AS summed_monthly_fec,
  MEDIAN(max_active) AS median_active
 FROM combined GROUP BY cnpj,area)
 TO 'audit_output/matched_area_annual_2025.csv' (HEADER,DELIMITER ',')
""")
report={"manifest":manifest,"raw_diagnostics":raw,"valid_sample":tot,
        "thresholds":thresholds,"excluded":excluded,"repeated":repeats,
        "indicator_inventory":inventory,"official_duplicates":official_duplicates,
        "join":joinstats,"quartiles":summary,
        "methods":{"metric":"affected units * recorded interruption duration, by record",
                   "key":"LPAD(CNPJ,14,0), conjunto numeric ID, calendar month",
                   "validity":"2025 start year, positive affected and duration 0-744 hours",
                   "regulatory":"official DEC/FEC joined only, not reverse engineered from rows"}}
(OUT/"summary_2025.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf8")
print("AUDIT_COMPLETE",flush=True)


# Sensitivity audit of published and all-record burdens using the official NUMCON denominator.
db.execute("""
CREATE TABLE d_numcon AS
SELECT cnpj,area,mo, MAX(value) AS numcon
FROM o WHERE indicator='NUMCON' AND mo BETWEEN 1 AND 12
GROUP BY 1,2,3 HAVING COUNT(*)=1
""")
db.execute("""
CREATE TABLE c2 AS
SELECT c.*, n.numcon
FROM combined c JOIN d_numcon n USING(cnpj,area,mo)
WHERE n.numcon>0 AND c.dec IS NOT NULL AND c.fec IS NOT NULL
""")
quality=db.execute("""
SELECT COUNT(*) AS n,
 CORR(ch_notexcluded/numcon,dec) AS dec_corr_numcon,
 CORR(occ_notexcluded/numcon,fec) AS fec_corr_numcon,
 MEDIAN(ABS(ch_notexcluded/numcon-dec)) AS median_abs_dec_delta,
 MEDIAN(ABS(occ_notexcluded/numcon-fec)) AS median_abs_fec_delta,
 MEDIAN(ABS(max_active-numcon)/numcon) AS median_relative_denominator_difference,
 COUNT(*) FILTER(WHERE max_active!=numcon) AS numcon_not_equal_maxactive
FROM c2
""").df().iloc[0].to_dict()
print("OFFICIAL_DENOMINATOR_CHECK",json.dumps(quality,default=str),flush=True)
db.execute("""
CREATE TABLE annual AS
SELECT cnpj,area,COUNT(*) AS months,
 SUM(dec) AS official_dec,
 SUM(fec) AS official_fec,
 SUM(ch_all/numcon) AS all_customer_hours_per_community_unit,
 SUM(COALESCE(ch_notexcluded,0)/numcon) AS nonexcluded_customer_hours_per_community_unit,
 SUM(ch_all) AS annual_all_ch,
 SUM(COALESCE(ch24,0)) AS annual_24_ch,
 SUM(COALESCE(ch_notexcluded,0)) AS annual_nonexcluded_ch,
 SUM(COALESCE(ch24_notexcluded,0)) AS annual_nonexcluded_24_ch,
 MEDIAN(numcon) AS median_customers
FROM c2
GROUP BY 1,2
HAVING COUNT(*)=12 AND MEDIAN(numcon)>=1000
""")
ann=db.execute("""
SELECT COUNT(*) AS areas,COUNT(DISTINCT cnpj) AS utilities,
 CORR(all_customer_hours_per_community_unit,official_dec) AS corr_all_vs_official,
 CORR(nonexcluded_customer_hours_per_community_unit,official_dec) AS corr_nonexcluded_vs_official,
 MEDIAN(annual_24_ch/NULLIF(annual_all_ch,0)) AS median_area_24h_share,
 QUANTILE_CONT(annual_24_ch/NULLIF(annual_all_ch,0),[0.25,0.50,0.75,0.90,0.95]) AS quantiles_tail24,
 COUNT(*) FILTER(WHERE annual_24_ch/NULLIF(annual_all_ch,0)>=0.2) AS area_tail_ge20pct,
 COUNT(*) FILTER(WHERE annual_24_ch/NULLIF(annual_all_ch,0)>=0.5) AS area_tail_ge50pct,
 COUNT(*) FILTER(WHERE annual_nonexcluded_ch>0 AND annual_nonexcluded_24_ch/annual_nonexcluded_ch>=0.2) AS nonexcluded_area_tail_ge20pct
FROM annual
""").df().iloc[0].to_dict()
print("ANNUAL_AREA_RESULTS",json.dumps(ann,default=str),flush=True)
db.execute("""
CREATE TABLE ranks AS
WITH with_ranks AS (
SELECT *,
 COUNT(*) OVER(PARTITION BY cnpj) AS n_in_utility,
 PERCENT_RANK() OVER(PARTITION BY cnpj ORDER BY official_dec) AS official_percentile,
 PERCENT_RANK() OVER(PARTITION BY cnpj ORDER BY all_customer_hours_per_community_unit) AS all_percentile,
 (annual_24_ch/NULLIF(annual_all_ch,0)) AS tail24_share,
 (annual_nonexcluded_24_ch/NULLIF(annual_nonexcluded_ch,0)) AS retained_tail24_share,
 (annual_all_ch-annual_nonexcluded_ch)/NULLIF(annual_all_ch,0) AS excluded_share
FROM annual)
SELECT * FROM with_ranks WHERE n_in_utility>=8
""")
decision=db.execute("""
SELECT COUNT(*) AS comparable_areas,COUNT(DISTINCT cnpj) AS utilities,
 AVG(ABS(official_percentile-all_percentile)) AS mean_absolute_percentile_shift,
 MEDIAN(ABS(official_percentile-all_percentile)) AS median_absolute_percentile_shift,
 COUNT(*) FILTER (WHERE ABS(official_percentile-all_percentile)>=0.25) AS shifted_at_least_one_quartile,
 COUNT(*) FILTER (WHERE official_percentile<0.25 AND all_percentile>=0.75) AS apparent_best_to_worst,
 COUNT(*) FILTER (WHERE official_percentile>=0.75 AND all_percentile<0.25) AS apparent_worst_to_best,
 COUNT(*) FILTER (WHERE (official_percentile>=0.75)<>(all_percentile>=0.75)) AS discordant_highest_quartile
FROM ranks
""").df().iloc[0].to_dict()
print("WITHIN_UTILITY_RANK_SHIFTS",json.dumps(decision,default=str),flush=True)
quart=db.execute("""
WITH scored AS (
SELECT *, NTILE(4) OVER(ORDER BY dec) AS q FROM c2 WHERE max_active>=1000 AND ch_all>0
)
SELECT q,COUNT(*) AS n, MEDIAN(dec) AS median_official_dec,
 MEDIAN(COALESCE(ch24,0)/ch_all) AS median_allrecord_tail24_share,
 AVG(COALESCE(ch24,0)/ch_all) AS mean_allrecord_tail24_share,
 COUNT(*) FILTER(WHERE COALESCE(ch24,0)/ch_all>=0.5) AS majority24
FROM scored GROUP BY 1 ORDER BY 1
""").df().to_dict(orient="records")
print("MONTHLY_QUARTILES_CORRECTED",json.dumps(quart,default=str),flush=True)
db.execute("""
COPY (SELECT * FROM ranks ORDER BY ABS(official_percentile-all_percentile) DESC)
TO 'audit_output/annual_rank_audit_2025.csv' (HEADER,DELIMITER ',')
""")
report["official_numcon_quality"]=quality
report["annual_area"]=ann
report["rank_shift"]=decision
report["corrected_monthly_quartiles"]=quart
(OUT/"summary_2025.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf8")
print("EXTENDED_AUDIT_COMPLETE",flush=True)


# Frozen-scope sensitivity: isolate reason 3, independently of regulatory code 0.
db.execute("""
CREATE TABLE alt_month AS
SELECT cnpj,area,mo,
 SUM(customer_hours) FILTER (WHERE exclusion<>3) AS no3,
 SUM(customer_hours) FILTER (WHERE exclusion NOT IN (3,6)) AS no36
FROM e GROUP BY cnpj,area,mo
""")
db.execute("""
CREATE TABLE alt_annual AS
SELECT p.cnpj,p.area,COUNT(*) AS months,
 SUM(COALESCE(q.no3,0)/p.numcon) AS no3_rate,
 SUM(COALESCE(q.no36,0)/p.numcon) AS no36_rate
FROM c2 p LEFT JOIN alt_month q USING(cnpj,area,mo)
GROUP BY 1,2 HAVING COUNT(*)=12
""")
db.execute("""
CREATE TABLE alt_rank AS
SELECT r.*, v.no3_rate,v.no36_rate,
 PERCENT_RANK() OVER(PARTITION BY r.cnpj ORDER BY v.no3_rate) AS rank_no3,
 PERCENT_RANK() OVER(PARTITION BY r.cnpj ORDER BY v.no36_rate) AS rank_no36
FROM ranks r JOIN alt_annual v USING(cnpj,area)
""")
z=db.execute("""
SELECT COUNT(*) AS compared,
COUNT(*) FILTER(WHERE ABS(official_percentile-rank_no3)>=0.25) AS shift25_no3,
COUNT(*) FILTER(WHERE ABS(official_percentile-rank_no36)>=0.25) AS shift25_no36,
COUNT(*) FILTER(WHERE official_percentile<0.25 AND rank_no3>=0.75) AS best_to_worst_no3,
COUNT(*) FILTER(WHERE official_percentile<0.25 AND rank_no36>=0.75) AS best_to_worst_no36,
COUNT(*) FILTER(WHERE (official_percentile>=0.75)<>(rank_no3>=0.75)) AS high_quartile_mismatch_no3,
COUNT(*) FILTER(WHERE (official_percentile>=0.75)<>(rank_no36>=0.75)) AS high_quartile_mismatch_no36
FROM alt_rank
""").df().iloc[0].to_dict()
report["reason3_and_6_sensitivity"]=z
print("EXCLUSION_SENSITIVITY",json.dumps(z,default=str),flush=True)
db.execute("""
COPY (SELECT cnpj,area,official_dec,official_fec,tail24_share,excluded_share,official_percentile,all_percentile,rank_no3,rank_no36,annual_24_ch,annual_all_ch FROM alt_rank)
TO 'audit_output/rank_sensitivity_YEAR.csv' (HEADER,DELIMITER ',')
""".replace("YEAR",str(YEAR)))
(OUT/f"summary_{YEAR}.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf8")
print("SENSITIVITY_COMPLETE",YEAR,flush=True)
