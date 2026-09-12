import Defs

namespace P

universe u

 theorem q0 {α : Type u} (D I S : α → Prop) :
    SubsetOn D S I ↔ ¬ NewlyAdmitted D I S := by
  constructor
  · intro hsub hbad
    rcases hbad with ⟨z, hD, hS, hNI⟩
    exact hNI (hsub z hD hS)
  · intro hno z hD hS
    by_contra hNI
    exact hno ⟨z, hD, hS, hNI⟩

 theorem q1 {α : Type u} (D I S : α → Prop) :
    SubsetOn D I S ↔ ¬ NewlyRejected D I S := by
  constructor
  · intro hsub hbad
    rcases hbad with ⟨z, hD, hI, hNS⟩
    exact hNS (hsub z hD hI)
  · intro hno z hD hI
    by_contra hNS
    exact hno ⟨z, hD, hI, hNS⟩

 theorem q2 {α : Type u} (D I K : α → Prop)
    (hs : Safe D I K) (hc : Covers D I K) :
    ∀ z, D z → (K z ↔ ¬ I z) := by
  intro z hD
  constructor
  · intro hK hI
    exact (hs z hD hI) hK
  · intro hNI
    exact hc z hD hNI

 theorem q3 {α : Type u} (D I K : α → Prop)
    (hexact : ∀ z, D z → (K z ↔ ¬ I z)) :
    Safe D I K ∧ Covers D I K := by
  constructor
  · intro z hD hI hK
    exact ((hexact z hD).1 hK) hI
  · intro z hD hNI
    exact (hexact z hD).2 hNI

 theorem q4 {α : Type u} (D I K₁ K₂ : α → Prop)
    (h₁ : Safe D I K₁ ∧ Covers D I K₁)
    (h₂ : Safe D I K₂ ∧ Covers D I K₂) :
    ∀ z, D z → (K₁ z ↔ K₂ z) := by
  intro z hD
  have e₁ := q2 D I K₁ h₁.1 h₁.2 z hD
  have e₂ := q2 D I K₂ h₂.1 h₂.2 z hD
  constructor
  · intro hk
    exact e₂.2 (e₁.1 hk)
  · intro hk
    exact e₁.2 (e₂.1 hk)

 theorem q5 {α : Type u} (D I K T S : α → Prop)
    (hhit : Hits D I K T) (hadmit : Admits D T S) :
    ¬ GuardAccepts D K S := by
  intro hguard
  rcases hhit with ⟨z, hD, hT, _hNI, hK⟩
  exact (hguard z hD (hadmit z hD hT)) hK

 theorem q6 {α : Type u} (D I S B : α → Prop)
    (hacc : AcceptsBehavior D B S) (hvio : ViolatesIntent D I B) :
    ReachableLost D I S B := by
  rcases hvio with ⟨z, hD, hB, hNI⟩
  exact ⟨z, hD, hB, hacc z hD hB, hNI⟩

 theorem q7 {α : Type u} (D I K S : α → Prop)
    (hs : Safe D I K) (hc : Covers D I K) :
    GuardAccepts D K S ↔ SubsetOn D S I := by
  constructor
  · intro hguard z hD hS
    by_contra hNI
    exact (hguard z hD hS) (hc z hD hNI)
  · intro hsub z hD hS
    exact hs z hD (hsub z hD hS)

end P
