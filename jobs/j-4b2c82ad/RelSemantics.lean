import IRSemantics

namespace IR

noncomputable section
local instance propDecidable (p : Prop) : Decidable p := Classical.propDecidable p

mutual
  def evalR : ITerm → Env → Int
    | .lit n, _ => n
    | .var i, e => e.iv i
    | .add a b, e => evalR a e + evalR b e
    | .sub a b, e => evalR a e - evalR b e
    | .ite c t f, e => if Sat c e then evalR t e else evalR f e

  def Sat : BExpr → Env → Prop
    | .lit b, _ => b = true
    | .var i, e => e.bv i = true
    | .not a, e => ¬ Sat a e
    | .and a b, e => Sat a e ∧ Sat b e
    | .or a b, e => Sat a e ∨ Sat b e
    | .imp a b, e => Sat a e → Sat b e
    | .iff a b, e => Sat a e ↔ Sat b e
    | .eqi a b, e => evalR a e = evalR b e
    | .nei a b, e => evalR a e ≠ evalR b e
    | .eqb a b, e => Sat a e ↔ Sat b e
    | .neb a b, e => ¬ (Sat a e ↔ Sat b e)
    | .lt a b, e => evalR a e < evalR b e
    | .le a b, e => evalR a e ≤ evalR b e
    | .gt a b, e => evalR a e > evalR b e
    | .ge a b, e => evalR a e ≥ evalR b e
    | .ite c t f, e => if Sat c e then Sat t e else Sat f e
end

end

end IR
