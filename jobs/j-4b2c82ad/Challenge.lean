import Defs

namespace P

universe u

 theorem q0 {α : Type u} (D I S : α → Prop) :
    SubsetOn D S I ↔ ¬ NewlyAdmitted D I S := by sorry

 theorem q1 {α : Type u} (D I S : α → Prop) :
    SubsetOn D I S ↔ ¬ NewlyRejected D I S := by sorry

 theorem q2 {α : Type u} (D I K : α → Prop)
    (hs : Safe D I K) (hc : Covers D I K) :
    ∀ z, D z → (K z ↔ ¬ I z) := by sorry

 theorem q3 {α : Type u} (D I K : α → Prop)
    (hexact : ∀ z, D z → (K z ↔ ¬ I z)) :
    Safe D I K ∧ Covers D I K := by sorry

 theorem q4 {α : Type u} (D I K₁ K₂ : α → Prop)
    (h₁ : Safe D I K₁ ∧ Covers D I K₁)
    (h₂ : Safe D I K₂ ∧ Covers D I K₂) :
    ∀ z, D z → (K₁ z ↔ K₂ z) := by sorry

 theorem q5 {α : Type u} (D I K T S : α → Prop)
    (hhit : Hits D I K T) (hadmit : Admits D T S) :
    ¬ GuardAccepts D K S := by sorry

 theorem q6 {α : Type u} (D I S B : α → Prop)
    (hacc : AcceptsBehavior D B S) (hvio : ViolatesIntent D I B) :
    ReachableLost D I S B := by sorry

 theorem q7 {α : Type u} (D I K S : α → Prop)
    (hs : Safe D I K) (hc : Covers D I K) :
    GuardAccepts D K S ↔ SubsetOn D S I := by sorry

end P
