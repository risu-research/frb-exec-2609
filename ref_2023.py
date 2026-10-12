from pathlib import Path
import subprocess,sys
script=Path('quality_check_2024.py').read_text()
assert script.count('2024')>=8
old='WHERE n.numcon>0 AND c.dec IS NOT NULL AND c.fec IS NOT NULL'
assert script.count(old)==1
script=script.replace(old,'WHERE n.numcon>0 AND c.dec IS NOT NULL')
script=script.replace('2024','2023')
Path('_ref_2023.py').write_text(script)
subprocess.run([sys.executable,'-u','_ref_2023.py'],check=True)
