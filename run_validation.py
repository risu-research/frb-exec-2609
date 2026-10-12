"""Run fixed-source annual snapshots, preserving separation of historic features and heldout outcomes."""
from pathlib import Path
import subprocess, sys
for year in [2024,2025]:
    txt=Path(f"quality_check_{year}.py").read_text()
    original="WHERE n.numcon>0 AND c.dec IS NOT NULL AND c.fec IS NOT NULL"
    assert txt.count(original)==1,"Unsafe unexpected source change"
    txt=txt.replace(original,"WHERE n.numcon>0 AND c.dec IS NOT NULL")
    # Add output for event-level outcome sensitivity; identical SQL both years.
    txt+=f'''
db.execute("""
COPY (
 SELECT cnpj,area,
 SUM(customer_hours) FILTER(WHERE exclusion<>3) AS no3_ch,
 SUM(customer_hours) FILTER(WHERE exclusion NOT IN (3,6)) AS no36_ch,
 SUM(customer_hours) FILTER(WHERE hours>=24 AND exclusion<>3) AS no3_24h_ch,
 SUM(customer_hours) FILTER(WHERE hours>=24 AND exclusion NOT IN (3,6)) AS no36_24h_ch
 FROM e GROUP BY 1,2
) TO 'audit_output/retained_{year}.csv' (HEADER,DELIMITER ',')
""")
print("FROZEN_YEAR_DONE",{year},flush=True)
'''
    temp=Path(f"_frozen_{year}.py")
    temp.write_text(txt)
    subprocess.run([sys.executable,'-u',str(temp)],check=True)
subprocess.run([sys.executable,'-u','validation_decision.py'],check=True)
