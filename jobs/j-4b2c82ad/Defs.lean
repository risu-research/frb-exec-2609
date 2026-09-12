universe u

namespace P

def SubsetOn {α : Type u} (D A B : α → Prop) : Prop :=
  ∀ z, D z → A z → B z

def NewlyAdmitted {α : Type u} (D I S : α → Prop) : Prop :=
  ∃ z, D z ∧ S z ∧ ¬ I z

def NewlyRejected {α : Type u} (D I S : α → Prop) : Prop :=
  ∃ z, D z ∧ I z ∧ ¬ S z

def Safe {α : Type u} (D I K : α → Prop) : Prop :=
  ∀ z, D z → I z → ¬ K z

def Covers {α : Type u} (D I K : α → Prop) : Prop :=
  ∀ z, D z → ¬ I z → K z

def GuardAccepts {α : Type u} (D K S : α → Prop) : Prop :=
  ∀ z, D z → S z → ¬ K z

def Admits {α : Type u} (D T S : α → Prop) : Prop :=
  ∀ z, D z → T z → S z

def Hits {α : Type u} (D I K T : α → Prop) : Prop :=
  ∃ z, D z ∧ T z ∧ ¬ I z ∧ K z

def AcceptsBehavior {α : Type u} (D B S : α → Prop) : Prop :=
  ∀ z, D z → B z → S z

def ViolatesIntent {α : Type u} (D I B : α → Prop) : Prop :=
  ∃ z, D z ∧ B z ∧ ¬ I z

def ReachableLost {α : Type u} (D I S B : α → Prop) : Prop :=
  ∃ z, D z ∧ B z ∧ S z ∧ ¬ I z

end P
