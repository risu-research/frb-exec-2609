from pathlib import Path
import json
R=Path(__file__).resolve().parent
challenge='''import RelSemantics

namespace RB
open IR

theorem eval_equiv : ∀ t e, evalR t e = evalI t e := by
  sorry

theorem sat_equiv : ∀ x e, Sat x e ↔ Holds x e := by
  sorry

end RB
'''
solution='''import RelBridge

namespace RB
open IR

theorem eval_equiv : ∀ t e, evalR t e = evalI t e := by
  intro t e
  exact IR.evalR_eq_evalI t e

theorem sat_equiv : ∀ x e, Sat x e ↔ Holds x e := by
  intro x e
  exact IR.sat_iff_holds x e

end RB
'''
(R/'RelBridgeChallenge.lean').write_text(challenge)
(R/'RelBridgeSolution.lean').write_text(solution)
config={
  'challenge_module':'RelBridgeChallenge',
  'solution_module':'RelBridgeSolution',
  'theorem_names':['RB.eval_equiv','RB.sat_equiv'],
  'permitted_axioms':['propext','Quot.sound','Classical.choice'],
  'enable_nanoda':True,
}
(R/'comparator_bridge.json').write_text(json.dumps(config,indent=2)+'\n')
lake=(R/'lakefile.toml').read_text()
old='"RelSemantics", "GeneratedBank"'
new='"RelSemantics", "RelBridge", "RelBridgeChallenge", "RelBridgeSolution", "GeneratedBank"'
if old not in lake:
    raise SystemExit('BRIDGE_JUDGE_LAKE_SHAPE_MISMATCH')
(R/'lakefile.toml').write_text(lake.replace(old,new,1))
if 'sorry' in solution:
    raise SystemExit('TRUSTED_BRIDGE_SOLUTION_HAS_SORRY')
print('BRIDGE_JUDGE_PREP_PASS')
