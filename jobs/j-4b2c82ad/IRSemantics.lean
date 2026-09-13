import Defs

namespace IR

mutual
  inductive ITerm where
    | lit (n : Int)
    | var (i : Nat)
    | add (a b : ITerm)
    | sub (a b : ITerm)
    | ite (c : BExpr) (t e : ITerm)
    deriving Repr

  inductive BExpr where
    | lit (b : Bool)
    | var (i : Nat)
    | not (a : BExpr)
    | and (a b : BExpr)
    | or (a b : BExpr)
    | imp (a b : BExpr)
    | iff (a b : BExpr)
    | eqi (a b : ITerm)
    | nei (a b : ITerm)
    | eqb (a b : BExpr)
    | neb (a b : BExpr)
    | lt (a b : ITerm)
    | le (a b : ITerm)
    | gt (a b : ITerm)
    | ge (a b : ITerm)
    | ite (c t e : BExpr)
    deriving Repr
end

structure Env where
  iv : Nat → Int
  bv : Nat → Bool

mutual
  def evalI : ITerm → Env → Int
    | .lit n, _ => n
    | .var i, e => e.iv i
    | .add a b, e => evalI a e + evalI b e
    | .sub a b, e => evalI a e - evalI b e
    | .ite c t f, e => if evalB c e then evalI t e else evalI f e

  def evalB : BExpr → Env → Bool
    | .lit b, _ => b
    | .var i, e => e.bv i
    | .not a, e => !(evalB a e)
    | .and a b, e => evalB a e && evalB b e
    | .or a b, e => evalB a e || evalB b e
    | .imp a b, e => !(evalB a e) || evalB b e
    | .iff a b, e => evalB a e == evalB b e
    | .eqi a b, e => decide (evalI a e = evalI b e)
    | .nei a b, e => decide (evalI a e ≠ evalI b e)
    | .eqb a b, e => evalB a e == evalB b e
    | .neb a b, e => evalB a e != evalB b e
    | .lt a b, e => decide (evalI a e < evalI b e)
    | .le a b, e => decide (evalI a e ≤ evalI b e)
    | .gt a b, e => decide (evalI a e > evalI b e)
    | .ge a b, e => decide (evalI a e ≥ evalI b e)
    | .ite c t f, e => if evalB c e then evalB t e else evalB f e
end

-- Generic bridge from executable Bool atoms to relational Prop reasoning.
-- These are contract-independent and kernel checked; they do not alter evalB.
@[simp] theorem decide_true_bridge (p : Prop) [Decidable p] : decide p = true ↔ p := by
  by_cases h : p <;> simp [h]

@[simp] theorem decide_false_bridge (p : Prop) [Decidable p] : decide p = false ↔ ¬ p := by
  by_cases h : p <;> simp [h]

def Holds (x : BExpr) : Env → Prop := fun e => evalB x e = true

structure Contract where
  domain : BExpr
  intent : BExpr
  initial : BExpr
  candidate : BExpr
  seeded : BExpr
  obligations : List BExpr
  currentGuard : BExpr
  threats : List BExpr
  intCount : Nat
  boolCount : Nat

def mkEnv (is : List Int) (bs : List Bool) : Env :=
  { iv := fun n => is.getD n 0
    bv := fun n => bs.getD n false }

end IR
