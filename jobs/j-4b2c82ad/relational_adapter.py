from pathlib import Path
import hashlib, json

R=Path(__file__).resolve().parent

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def adapt(s: str, proof: bool) -> str:
    if 'import RelSemantics\n' not in s:
        s=s.replace('import GeneratedBank\n','import GeneratedBank\nimport RelSemantics\n',1)
    s=s.replace('IR.Holds x','IR.Sat x')
    if proof:
        s=s.replace('IR.decide_true_bridge, IR.decide_false_bridge, ','')
        s=s.replace('Holds','Sat').replace('evalB','Sat').replace('evalI','evalR')
    return s

p=R/'GeneratedProofs.lean'
c=R/'GeneratedChallenge.lean'
p.write_text(adapt(p.read_text(),True))
c.write_text(adapt(c.read_text(),False))
(R/'GeneratedSolution.lean').write_text(p.read_text())

lake=(R/'lakefile.toml').read_text()
lake=lake.replace('"IRSemantics", "GeneratedBank"','"IRSemantics", "RelSemantics", "GeneratedBank"')
(R/'lakefile.toml').write_text(lake)

for q in (R/'RelSemantics.lean',p,R/'GeneratedSolution.lean'):
    if 'sorry' in q.read_text(): raise SystemExit('UNTRUSTED_SORRY:'+q.name)

m=json.loads((R/'translation_manifest.json').read_text())
m['schema']='pc.translation-validation.v2'
m['rel_semantics_sha256']=sha(R/'RelSemantics.lean')
m['relational_adapter_sha256']=sha(Path(__file__))
m['generated_proofs_sha256']=sha(p)
m['challenge_sha256']=sha(c)
m['solution_sha256']=sha(R/'GeneratedSolution.lean')
m['proof_semantics_adapter']='generic Holds/evalB/evalI -> Sat/Sat/evalR only'
(R/'translation_manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
print(json.dumps(m,sort_keys=True))
