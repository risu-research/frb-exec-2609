from __future__ import annotations
import hashlib, json, re, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'source_a05.json'
EXPECTED=[f'GV.c{i}_{s}' for i in range(6) for s in ('weaker','channel','qa','qb','full','exact')]

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(cmd): subprocess.run(cmd,cwd=ROOT,check=True)
for d in (ROOT/'pyout',ROOT/'jsout'):
    if d.exists(): shutil.rmtree(d)
# Proof bodies are deliberately stored as six small immutable fragments.
# They are not semantic authority; theorem statements are generated over the JSON-derived bank.
prefix='import GeneratedBank\nimport Solution\nimport Lean.Elab.Tactic.Omega\n\nnamespace GV\nopen P IR G\n\nabbrev H (x : BExpr) : Env → Prop := IR.Holds x\n\n'
parts=[]
for i in range(6):
    q=ROOT/f'proof_c{i}.part'
    if not q.exists(): raise SystemExit(f'MISSING_PROOF_FRAGMENT:{i}')
    parts.append(q.read_text())
(ROOT/'GeneratedProofs.lean').write_text(prefix+''.join(parts)+'\nend GV\n')
run([sys.executable,'compile_py.py',SRC.name,'pyout'])
run(['node','compile_js.mjs',SRC.name,'jsout'])
for fn in ('typed_ir.json','GeneratedBank.lean','manifest.json'):
    a=(ROOT/'pyout'/fn).read_bytes(); b=(ROOT/'jsout'/fn).read_bytes()
    if a!=b: raise SystemExit('DUAL_COMPILER_MISMATCH:'+fn)
shutil.copy2(ROOT/'pyout'/'GeneratedBank.lean',ROOT/'GeneratedBank.lean')
shutil.copy2(ROOT/'pyout'/'typed_ir.json',ROOT/'typed_ir.json')
shutil.copy2(ROOT/'pyout'/'manifest.json',ROOT/'compiler_manifest.json')
for p in (ROOT/'IRSemantics.lean',ROOT/'GeneratedBank.lean',ROOT/'GeneratedProofs.lean'):
    if 'sorry' in p.read_text(): raise SystemExit('UNTRUSTED_SORRY:'+p.name)
text=(ROOT/'GeneratedProofs.lean').read_text()
m=re.search(r'namespace GV\nopen P IR G\n(?P<body>.*)\nend GV\s*$',text,re.S)
if not m: raise SystemExit('PROOF_NAMESPACE_SHAPE')
lines=m.group('body').splitlines(keepends=True)
starts=[]
for i,line in enumerate(lines):
    if re.match(r'^ theorem\s+',line): starts.append(i)
starts.append(len(lines))
blocks=[]
for a,b in zip(starts,starts[1:]):
    block=''.join(lines[a:b]).strip()+'\n'
    if block.startswith('theorem ') or block.startswith(' theorem '): blocks.append(block.lstrip())
names=[]; challenge=[]
for b in blocks:
    first=b.splitlines()[0]
    mm=re.match(r'^theorem\s+([A-Za-z0-9_]+)\s*:\s*(.*?)\s*:=\s*(.*)$',first)
    if not mm: raise SystemExit('UNSUPPORTED_THEOREM_HEADER:'+first)
    nm=mm.group(1); st=mm.group(2); names.append('GV.'+nm)
    challenge.append(f'theorem {nm} : {st} := by\n  sorry\n')
if names!=EXPECTED: raise SystemExit('GENERATED_THEOREM_SET_OR_ORDER_MISMATCH:'+json.dumps(names))
(ROOT/'GeneratedChallenge.lean').write_text('import GeneratedBank\nimport Solution\n\nnamespace GV\nopen P IR G\n\nabbrev H (x : BExpr) : Env → Prop := IR.Holds x\n\n'+'\n'.join(challenge)+'\nend GV\n')
(ROOT/'GeneratedSolution.lean').write_text(text)
config={"challenge_module":"GeneratedChallenge","solution_module":"GeneratedSolution","theorem_names":EXPECTED,"permitted_axioms":["propext","Quot.sound","Classical.choice"],"enable_nanoda":True}
(ROOT/'comparator_generated.json').write_text(json.dumps(config,indent=2)+'\n')
(ROOT/'lakefile.toml').write_text('name = "j4b2c82ad"\nversion = "0.1.0"\ndefaultTargets = ["P"]\n\n[[lean_lib]]\nname = "P"\nroots = ["Defs", "Challenge", "Solution", "IRSemantics", "GeneratedBank", "GeneratedChallenge", "GeneratedSolution"]\n')
man=json.loads((ROOT/'compiler_manifest.json').read_text())
receipt={'schema':'pc.translation-validation.v1','source_sha256':sha(SRC),'typed_ir_sha256':sha(ROOT/'typed_ir.json'),'generated_bank_sha256':sha(ROOT/'GeneratedBank.lean'),'python_compiler_sha256':sha(ROOT/'compile_py.py'),'javascript_compiler_sha256':sha(ROOT/'compile_js.mjs'),'ir_semantics_sha256':sha(ROOT/'IRSemantics.lean'),'generated_proofs_sha256':sha(ROOT/'GeneratedProofs.lean'),'challenge_sha256':sha(ROOT/'GeneratedChallenge.lean'),'solution_sha256':sha(ROOT/'GeneratedSolution.lean'),'comparator_config_sha256':sha(ROOT/'comparator_generated.json'),'compiler_manifest':man,'theorem_count':len(EXPECTED),'theorem_names':EXPECTED,'dual_compiler_byte_identity':True}
(ROOT/'translation_manifest.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps(receipt,sort_keys=True))
