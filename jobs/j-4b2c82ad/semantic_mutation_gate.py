from pathlib import Path
import sys
p=Path('RelSemantics.lean')
name=sys.argv[1]
M={
 'lt_to_le':('    | .lt a b, e => evalR a e < evalR b e','    | .lt a b, e => evalR a e ≤ evalR b e'),
 'and_to_or':('    | .and a b, e => Sat a e ∧ Sat b e','    | .and a b, e => Sat a e ∨ Sat b e'),
 'imp_reverse':('    | .imp a b, e => Sat a e → Sat b e','    | .imp a b, e => Sat b e → Sat a e'),
}
if name not in M: raise SystemExit('UNKNOWN_MUTATION:'+name)
s=p.read_text(); old,new=M[name]
if s.count(old)!=1: raise SystemExit('MUTATION_SITE_COUNT:'+name+':'+str(s.count(old)))
p.write_text(s.replace(old,new,1))
print('MUTATION_APPLIED:'+name)
