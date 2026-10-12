import json
from pathlib import Path
import numpy as np
import pandas as pd
P=Path('audit_output')
q={}
data={}
for year in [2024,2025]:
 d=json.loads((P/f'summary_{year}.json').read_text())
 a=pd.read_csv(P/f'annual_rank_audit_{year}.csv',dtype={'cnpj':str,'area':str})
 b=pd.read_csv(P/f'rank_sensitivity_{year}.csv',dtype={'cnpj':str,'area':str})
 d0=a.merge(b[['cnpj','area','rank_no3','rank_no36']],on=['cnpj','area'],validate='one_to_one')
 d0['displaced25']=(d0.official_percentile-d0.all_percentile).abs()>=.25
 d0['from_best_to_worst']=(d0.official_percentile<.25)&(d0.all_percentile>=.75)
 d0['high_q_mismatch']=(d0.official_percentile>=.75)!=(d0.all_percentile>=.75)
 data[year]=d0
 tail={int(x['threshold_hours']):x for x in d['thresholds'] if x['scope']=='all'}
 n0={int(x['threshold_hours']):x for x in d['thresholds'] if x['scope']=='nonexcluded'}
 code3=next((x for x in d['excluded'] if int(x['exclusion'])==3),None)
 q[str(year)]={
  'n_raw':d['raw_diagnostics']['raw_rows'],
  'n_retained':d['valid_sample']['n'],
  'n_utilities':d['valid_sample']['utilities'],
  'n_areas':d['valid_sample']['areas'],
  'n_area_months':d['valid_sample']['area_months'],
  'n_join_area_months':int(d['join']['inner_join_area_months']),
  'n_official_area_months':int(d['join']['official_area_months']),
  'join_fraction':d['join']['inner_join_area_months']/d['join']['event_area_months'],
  'annual_matched_areas':int(d['annual_area']['areas']),
  'annual_compared_areas':int(d['rank_shift']['comparable_areas']),
  'rank_shift25':int(d['rank_shift']['shifted_at_least_one_quartile']),
  'rank_high_quartile_mismatch':int(d['rank_shift']['discordant_highest_quartile']),
  'best_to_worst':int(d['rank_shift']['apparent_best_to_worst']),
  'reverse_worst_to_best':int(d['rank_shift']['apparent_worst_to_best']),
  'rank_shift25_no3':int(d['reason3_and_6_sensitivity']['shift25_no3']),
  'rank_shift25_no3_no6':int(d['reason3_and_6_sensitivity']['shift25_no36']),
  'nonexcluded_corr_dec':d['annual_area']['corr_nonexcluded_vs_official'],
  'allrecord_corr_dec':d['annual_area']['corr_all_vs_official'],
  'recorded_customerhours':d['valid_sample']['ch'],
  'tail8_pct':tail[8]['tail_customerhours_pct'],
  'tail12_pct':tail[12]['tail_customerhours_pct'],
  'tail24_pct':tail[24]['tail_customerhours_pct'],
  'tail48_pct':tail[48]['tail_customerhours_pct'],
  'tail24_nonexcluded_pct':n0[24]['tail_customerhours_pct'],
  'tail24_record_fraction':tail[24]['tail_record_pct'],
  'tail24_excluded_fraction_of_24h':(tail[24]['tail_ch']-n0[24]['tail_ch'])/tail[24]['tail_ch'],
  'tail24_code3_fraction_of_24h':float(code3['ch24'])/tail[24]['tail_ch'] if code3 else None,
  'source_sha256':{k:v['sha256'] for k,v in d['manifest'].items()}
 }
 print('YEARLY_SUMMARY',year,json.dumps(q[str(year)],allow_nan=False),flush=True)
A=data[2024].merge(data[2025],on=['cnpj','area'],suffixes=['_24','_25'],validate='one_to_one')
q['cross_year']={
 'matched_consumer_sets':len(A),
 'same_utility':int((A.cnpj!='').sum()),
 'shift25_2024':int(A.displaced25_24.sum()),
 'shift25_2025':int(A.displaced25_25.sum()),
 'shift25_both_years':int((A.displaced25_24&A.displaced25_25).sum()),
 'best_to_worst_2024':int(A.from_best_to_worst_24.sum()),
 'best_to_worst_2025':int(A.from_best_to_worst_25.sum()),
 'best_to_worst_both_years':int((A.from_best_to_worst_24&A.from_best_to_worst_25).sum()),
 'median_official_annual_dec_change':float(np.median(A.official_dec_25-A.official_dec_24)),
 'median_all_rate_change':float(np.median(A.all_customer_hours_per_community_unit_25-A.all_customer_hours_per_community_unit_24)),
 'median_tail24_share_change':float(np.nanmedian(A.tail24_share_25-A.tail24_share_24)),
 'median_abs_rank_shift_2024':float((A.official_percentile_24-A.all_percentile_24).abs().median()),
 'median_abs_rank_shift_2025':float((A.official_percentile_25-A.all_percentile_25).abs().median()),
}
# Evaluate whether one distributor entirely drives rank mismatch within each year.
for y,d in data.items():
 g=d.groupby('cnpj').agg(n=('displaced25','size'),shifts=('displaced25','sum'),extremes=('from_best_to_worst','sum'))
 g=g.sort_values('shifts',ascending=False)
 q[str(y)]['max_single_utility_shift_count']=int(g.shifts.iloc[0]) if len(g) else 0
 q[str(y)]['shift_count_excluding_largest_contributor']=int(g.shifts.sum()-g.shifts.iloc[0]) if len(g) else 0
 q[str(y)]['utilities_with_shift25']=int((g.shifts>0).sum())
q['cross_year']['paired_utility_n']=int(A.cnpj.nunique())
print('CROSS_YEAR_SUMMARY',json.dumps(q['cross_year']),flush=True)
P.joinpath('comparison_summary.json').write_text(json.dumps(q,indent=2,allow_nan=False))
print('COMPARISON_COMPLETE',flush=True)
