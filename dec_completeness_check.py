from pathlib import Path
import subprocess, sys
p=Path('quality_check_2025.py')
s=p.read_text()
old='WHERE n.numcon>0 AND c.dec IS NOT NULL AND c.fec IS NOT NULL'
assert s.count(old)==1
Path('_dec_check.py').write_text(s.replace(old,'WHERE n.numcon>0 AND c.dec IS NOT NULL'))
subprocess.run([sys.executable,'-u','_dec_check.py'],check=True)
