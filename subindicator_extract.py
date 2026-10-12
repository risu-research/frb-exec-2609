"""Open power-system reporting sub-indicator extraction and identity checks."""
from pathlib import Path
import requests, duckdb, hashlib, json, pandas as pd, numpy as np
OUT=Path("exported");OUT.mkdir(exist_ok=True)
api="https://dadosabertos.aneel.gov.br/api/3/action/package_show"
s=requests.Session()
meta=s.get(api,params={"id":"indicadores-coletivos-de-continuidade-dec-e-fec"},timeout=45);meta.raise_for_status()
files=[x for x in meta.json()["result"]["resources"] if x.get("name")=="indicadores-continuidade-coletivos-2020-2029.parquet"]
assert len(files)==1,files
url=files[0]["url"]
h=hashlib.sha256()
with s.get(url,stream=True,timeout=(30,240)) as r:
 r.raise_for_status()
 with open("raw_reference.parquet","wb") as fd:
  for chunk in r.iter_content(2**20):
   if chunk:fd.write(chunk);h.update(chunk)
print("SOURCE",json.dumps({"url":url,"bytes":Path("raw_reference.parquet").stat().st_size,"sha256":h.hexdigest()}),flush=True)
db=duckdb.connect()
db.execute("SET threads=2")
db.execute("SET memory_limit='3GB'")
df=db.execute("""
SELECT LPAD(REGEXP_REPLACE(CAST(NumCNPJ AS VARCHAR),'[^0-9]','','g'),14,'0') AS cnpj,
 CAST(TRY_CAST(IdeConjUndConsumidoras AS BIGINT) AS VARCHAR) AS area,
 TRY_CAST(AnoIndice AS INTEGER) AS year,
 TRY_CAST(NumPeriodoIndice AS INTEGER) AS month,
 UPPER(TRIM(CAST(SigIndicador AS VARCHAR))) AS indicator,
 TRY_CAST(VlrIndiceEnviado AS DOUBLE) AS value
FROM read_parquet('raw_reference.parquet')
WHERE TRY_CAST(AnoIndice AS INTEGER) IN (2023,2024)
""").df()
df=df[df.month.between(1,12)&df.value.notna()]
assert not df.duplicated(["cnpj","area","year","month","indicator"]).any(),"Unexpected official repeated keys"
print("INDICATOR_UNIVERSE",json.dumps(df.groupby(["year","indicator"]).size().reset_index().to_dict(orient="records"),default=str),flush=True)
# Sum 12 monthly hours for DEC/FEC categories; median monthly NUMCON is denominator.
cnt=df.groupby(["cnpj","area","year","indicator"],as_index=False).agg(n_months=("month","nunique"),annual_value=("value","sum"),monthly_median=("value","median"))
cnt=cnt[cnt.n_months==12]
cnt["value"]=np.where(cnt.indicator=="NUMCON",cnt.monthly_median,cnt.annual_value)
p=cnt.pivot(index=["cnpj","area","year"],columns="indicator",values="value").reset_index()
p.columns.name=None
# Exact monthly customer-hour reconstruction for each published DEC component.
keys=["cnpj","area","year","month"]
pop=df.loc[df.indicator=="NUMCON",keys+["value"]].rename(columns={"value":"customers"})
part=df.loc[df.indicator.str.startswith("DEC"),keys+["indicator","value"]].merge(
 pop,on=keys,how="left",validate="many_to_one")
part["component_customer_hours"]=part.value*part.customers
wide=part.groupby(["cnpj","area","year","indicator"],as_index=False).agg(
 n_valid=("component_customer_hours","count"),
 component_ch=("component_customer_hours","sum"))
wide=wide[wide.n_valid==12]
wide["indicator"]="CH_"+wide.indicator
ch=wide.pivot(index=["cnpj","area","year"],columns="indicator",values="component_ch").reset_index()
ch.columns.name=None
p=p.merge(ch,on=["cnpj","area","year"],how="left",validate="one_to_one")
p.to_csv(OUT/"annual_official_subindicators.csv",index=False)
fields=["DEC","FEC","NUMCON","DECIND","DECINE","DECINC","DECINO","DECIPC","DECXPC","DECXNC","DECIP","DECXP","DECXN"]
diag={"rows":len(df),"annual_areas":len(p),"official_indicators":sorted(df.indicator.unique().tolist()),"complete":{"total":len(p)}}
for name in fields:diag["complete"][name]=int(p[name].notna().sum()) if name in p else 0
# Identity: DEC approx sum 4 normal categories, with officially published rounded monthly values.
if set(["DEC","DECIND","DECIP","DECXP","DECXN"]).issubset(p.columns):
 g=p.dropna(subset=["DEC","DECIND","DECIP","DECXP","DECXN"])
 difference=g["DEC"]-g[["DECIND","DECIP","DECXP","DECXN"]].sum(axis=1)
 diag["dec_identity"]={"n":len(g),"median_abs_hours":float(difference.abs().median()),
   "p95_abs_hours":float(difference.abs().quantile(.95)),
   "share_within_0_2h":float((difference.abs()<=.2).mean())}
 print("DEC_IDENTITY",json.dumps(diag["dec_identity"]),flush=True)
for y in [2023,2024]:
 g=p[p.year==y]
 diag[str(y)]={"annual_areas":len(g),"companies":int(g.cnpj.nunique())}
print("EXPORT_SUMMARY",json.dumps(diag),flush=True)
(OUT/"extract_metadata.json").write_text(json.dumps({"source":{"url":url,"sha256":h.hexdigest()},
 "quality":diag,"definitions":"DEC subcategories are ANEEL-reported; exploratory sum of standard plus expelled DEC is not an official combined reliability index."},indent=2))
print("EXTRACT_COMPLETE",flush=True)
