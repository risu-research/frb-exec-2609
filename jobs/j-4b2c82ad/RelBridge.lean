import RelSemantics

namespace IR

mutual
  theorem evalR_eq_evalI : (t : ITerm) → (e : Env) → evalR t e = evalI t e
    | .lit n, e => by rfl
    | .var i, e => by rfl
    | .add a b, e => by
        simp [evalR, evalI, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .sub a b, e => by
        simp [evalR, evalI, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .ite c t f, e => by
        by_cases h : Sat c e
        · have hc : evalB c e = true := (sat_iff_evalB_true c e).mp h
          simp [evalR, evalI, h, hc, evalR_eq_evalI t e]
        · have hc : evalB c e = false := by
            cases hbc : evalB c e with
            | false => exact hbc
            | true =>
                exfalso
                exact h ((sat_iff_evalB_true c e).mpr hbc)
          simp [evalR, evalI, h, hc, evalR_eq_evalI f e]

  theorem sat_iff_evalB_true : (x : BExpr) → (e : Env) → Sat x e ↔ evalB x e = true
    | .lit b, e => by cases b <;> simp [Sat, evalB]
    | .var i, e => by simp [Sat, evalB]
    | .not a, e => by
        simp [Sat, evalB, sat_iff_evalB_true a e]
    | .and a b, e => by
        simp [Sat, evalB, sat_iff_evalB_true a e, sat_iff_evalB_true b e]
    | .or a b, e => by
        simp [Sat, evalB, sat_iff_evalB_true a e, sat_iff_evalB_true b e]
    | .imp a b, e => by
        simp [Sat, evalB, sat_iff_evalB_true a e, sat_iff_evalB_true b e]
    | .iff a b, e => by
        simp [Sat, evalB, sat_iff_evalB_true a e, sat_iff_evalB_true b e]
    | .eqi a b, e => by
        simp [Sat, evalB, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .nei a b, e => by
        simp [Sat, evalB, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .eqb a b, e => by
        simp [Sat, evalB, sat_iff_evalB_true a e, sat_iff_evalB_true b e]
    | .neb a b, e => by
        simp [Sat, evalB, sat_iff_evalB_true a e, sat_iff_evalB_true b e]
    | .lt a b, e => by
        simp [Sat, evalB, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .le a b, e => by
        simp [Sat, evalB, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .gt a b, e => by
        simp [Sat, evalB, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .ge a b, e => by
        simp [Sat, evalB, evalR_eq_evalI a e, evalR_eq_evalI b e]
    | .ite c t f, e => by
        by_cases h : Sat c e
        · have hc : evalB c e = true := (sat_iff_evalB_true c e).mp h
          simp [Sat, evalB, h, hc, sat_iff_evalB_true t e]
        · have hc : evalB c e = false := by
            cases hbc : evalB c e with
            | false => exact hbc
            | true =>
                exfalso
                exact h ((sat_iff_evalB_true c e).mpr hbc)
          simp [Sat, evalB, h, hc, sat_iff_evalB_true f e]
end

@[simp] theorem sat_iff_holds (x : BExpr) (e : Env) : Sat x e ↔ Holds x e := by
  simpa [Holds] using sat_iff_evalB_true x e

end IR
