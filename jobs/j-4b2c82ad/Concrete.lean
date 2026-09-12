import Solution
import Std.Tactic.Omega

namespace C
open P

structure C0 where r : Int; a : Bool; o : Int
def d0 (z : C0) : Prop := 0 ≤ z.r ∧ z.r ≤ 1 ∧ -1 ≤ z.o ∧ z.o ≤ 1
def i0 (z : C0) : Prop := (z.a = false → z.o = -1) ∧ (z.a = true → z.o = z.r)
def s0 (z : C0) : Prop := (z.a = false → z.o = -1) ∧ (z.a = true → z.o = 0 ∨ z.o = 1)
def b0 (z : C0) : Prop := (z.a = true ∧ z.o = 0) ∨ (z.a = false ∧ z.o = -1)
def qa0 (z : C0) : Prop := z.a = false ∧ z.o ≠ -1
def qb0 (z : C0) : Prop := z.a = true ∧ z.o ≠ z.r
def k0 (z : C0) : Prop := qa0 z ∨ qb0 z

theorem c0_weaker : SubsetOn d0 i0 s0 ∧ NewlyAdmitted d0 i0 s0 := by
  constructor
  · rintro ⟨r,a,o⟩ hd hi
    cases a <;> simp [i0,s0] at hi ⊢ <;> omega
  · refine ⟨⟨1,true,0⟩, ?_⟩
    simp [d0,s0,i0]
theorem c0_channel : AcceptsBehavior d0 b0 s0 ∧ ViolatesIntent d0 i0 b0 := by
  constructor
  · rintro ⟨r,a,o⟩ hd hb
    cases a <;> simp [b0,s0] at hb ⊢ <;> omega
  · refine ⟨⟨1,true,0⟩, ?_⟩
    simp [d0,b0,i0]
theorem c0_qa : Safe d0 i0 qa0 ∧ ¬ Covers d0 i0 qa0 := by
  constructor
  · rintro ⟨r,a,o⟩ hd hi hq
    cases a <;> simp [i0,qa0] at hi hq <;> omega
  · intro hc
    have := hc ⟨1,true,0⟩ (by simp [d0]) (by simp [i0])
    simp [qa0] at this
theorem c0_qb : Safe d0 i0 qb0 ∧ ¬ Covers d0 i0 qb0 := by
  constructor
  · rintro ⟨r,a,o⟩ hd hi hq
    cases a <;> simp [i0,qb0] at hi hq <;> omega
  · intro hc
    have := hc ⟨0,false,0⟩ (by simp [d0]) (by simp [i0])
    simp [qb0] at this
theorem c0_full : Safe d0 i0 k0 ∧ Covers d0 i0 k0 := by
  constructor
  · rintro ⟨r,a,o⟩ hd hi hk
    cases a <;> simp [i0,k0,qa0,qb0] at hi hk <;> omega
  · rintro ⟨r,a,o⟩ hd hni
    cases a <;> simp [i0,k0,qa0,qb0] at hni ⊢ <;> omega

structure C1 where x : Int; l : Int; a : Bool
def d1 (_ : C1) : Prop := True
def i1 (z : C1) : Prop := (z.a = true ↔ z.x < z.l)
def s1 (z : C1) : Prop := (z.x < z.l → z.a = true) ∧ (z.x > z.l → z.a = false)
def b1 (z : C1) : Prop := (z.a = true ↔ z.x ≤ z.l)
def qa1 (z : C1) : Prop := z.a = true ∧ ¬ z.x < z.l
def qb1 (z : C1) : Prop := z.a = false ∧ z.x < z.l
def k1 (z : C1) : Prop := qa1 z ∨ qb1 z

theorem c1_weaker : SubsetOn d1 i1 s1 ∧ NewlyAdmitted d1 i1 s1 := by
  constructor
  · rintro ⟨x,l,a⟩ _ hi
    cases a <;> simp [i1,s1] at hi ⊢ <;> omega
  · refine ⟨⟨0,0,true⟩, ?_⟩
    simp [d1,s1,i1]
theorem c1_channel : AcceptsBehavior d1 b1 s1 ∧ ViolatesIntent d1 i1 b1 := by
  constructor
  · rintro ⟨x,l,a⟩ _ hb
    cases a <;> simp [b1,s1] at hb ⊢ <;> omega
  · refine ⟨⟨0,0,true⟩, ?_⟩
    simp [d1,b1,i1]
theorem c1_qa : Safe d1 i1 qa1 ∧ ¬ Covers d1 i1 qa1 := by
  constructor
  · rintro ⟨x,l,a⟩ _ hi hq
    cases a <;> simp [i1,qa1] at hi hq <;> omega
  · intro hc
    have := hc ⟨0,1,false⟩ trivial (by simp [i1])
    simp [qa1] at this
theorem c1_qb : Safe d1 i1 qb1 ∧ ¬ Covers d1 i1 qb1 := by
  constructor
  · rintro ⟨x,l,a⟩ _ hi hq
    cases a <;> simp [i1,qb1] at hi hq <;> omega
  · intro hc
    have := hc ⟨0,0,true⟩ trivial (by simp [i1])
    simp [qb1] at this
theorem c1_full : Safe d1 i1 k1 ∧ Covers d1 i1 k1 := by
  constructor
  · rintro ⟨x,l,a⟩ _ hi hk
    cases a <;> simp [i1,k1,qa1,qb1] at hi hk <;> omega
  · rintro ⟨x,l,a⟩ _ hni
    cases a <;> simp [i1,k1,qa1,qb1] at hni ⊢ <;> omega

structure C2 where a : Bool; w : Bool; y : Bool
def d2 (_ : C2) : Prop := True
def i2 (z : C2) : Prop := (z.y = true ↔ z.a = true ∧ z.w = true)
def s2 (z : C2) : Prop := (z.a = true ∧ z.w = true → z.y = true) ∧ (z.a = false ∧ z.w = false → z.y = false)
def b2 (z : C2) : Prop := (z.y = true ↔ z.a = true ∨ z.w = true)
def qa2 (z : C2) : Prop := z.y = true ∧ ¬ (z.a = true ∧ z.w = true)
def qb2 (z : C2) : Prop := z.y = false ∧ z.a = true ∧ z.w = true
def k2 (z : C2) : Prop := qa2 z ∨ qb2 z

theorem c2_weaker : SubsetOn d2 i2 s2 ∧ NewlyAdmitted d2 i2 s2 := by
  constructor
  · rintro ⟨a,w,y⟩ _ hi
    cases a <;> cases w <;> cases y <;> simp [i2,s2] at hi ⊢
  · exact ⟨⟨true,false,true⟩, by simp [d2,s2,i2]⟩
theorem c2_channel : AcceptsBehavior d2 b2 s2 ∧ ViolatesIntent d2 i2 b2 := by
  constructor
  · rintro ⟨a,w,y⟩ _ hb
    cases a <;> cases w <;> cases y <;> simp [b2,s2] at hb ⊢
  · exact ⟨⟨true,false,true⟩, by simp [d2,b2,i2]⟩
theorem c2_qa : Safe d2 i2 qa2 ∧ ¬ Covers d2 i2 qa2 := by
  constructor
  · rintro ⟨a,w,y⟩ _ hi hq
    cases a <;> cases w <;> cases y <;> simp [i2,qa2] at hi hq
  · intro hc
    have := hc ⟨true,true,false⟩ trivial (by simp [i2])
    simp [qa2] at this
theorem c2_qb : Safe d2 i2 qb2 ∧ ¬ Covers d2 i2 qb2 := by
  constructor
  · rintro ⟨a,w,y⟩ _ hi hq
    cases a <;> cases w <;> cases y <;> simp [i2,qb2] at hi hq
  · intro hc
    have := hc ⟨true,false,true⟩ trivial (by simp [i2])
    simp [qb2] at this
theorem c2_full : Safe d2 i2 k2 ∧ Covers d2 i2 k2 := by
  constructor
  · rintro ⟨a,w,y⟩ _ hi hk
    cases a <;> cases w <;> cases y <;> simp [i2,k2,qa2,qb2] at hi hk
  · rintro ⟨a,w,y⟩ _ hni
    cases a <;> cases w <;> cases y <;> simp [i2,k2,qa2,qb2] at hni ⊢

structure C3 where s : Int; o : Int
def d3 (z : C3) : Prop := 0 ≤ z.s ∧ z.s ≤ 2 ∧ 0 ≤ z.o ∧ z.o ≤ 2
def i3 (z : C3) : Prop := z.o = if z.s = 1 then 2 else z.s
def s3 (z : C3) : Prop := (z.s = 1 → z.o = 2) ∧ (z.s = 2 → z.o = 2) ∧ (z.s = 0 → z.o = 0 ∨ z.o = 2)
def b3 (z : C3) : Prop := z.o = 2
def qa3 (z : C3) : Prop := z.s = 1 ∧ z.o ≠ 2
def qb3 (z : C3) : Prop := z.s ≠ 1 ∧ z.o ≠ z.s
def k3 (z : C3) : Prop := qa3 z ∨ qb3 z

theorem c3_weaker : SubsetOn d3 i3 s3 ∧ NewlyAdmitted d3 i3 s3 := by
  constructor
  · rintro ⟨s,o⟩ hd hi
    simp [i3,s3] at hi ⊢
    split at hi <;> omega
  · exact ⟨⟨0,2⟩, by simp [d3,s3,i3]⟩
theorem c3_channel : AcceptsBehavior d3 b3 s3 ∧ ViolatesIntent d3 i3 b3 := by
  constructor
  · rintro ⟨s,o⟩ hd hb
    simp [b3,s3] at hb ⊢
    omega
  · exact ⟨⟨0,2⟩, by simp [d3,b3,i3]⟩
theorem c3_qa : Safe d3 i3 qa3 ∧ ¬ Covers d3 i3 qa3 := by
  constructor
  · rintro ⟨s,o⟩ hd hi hq
    simp [i3,qa3] at hi hq
    split at hi <;> omega
  · intro hc
    have := hc ⟨0,2⟩ (by simp [d3]) (by simp [i3])
    simp [qa3] at this
theorem c3_qb : Safe d3 i3 qb3 ∧ ¬ Covers d3 i3 qb3 := by
  constructor
  · rintro ⟨s,o⟩ hd hi hq
    simp [i3,qb3] at hi hq
    split at hi <;> omega
  · intro hc
    have := hc ⟨1,0⟩ (by simp [d3]) (by simp [i3])
    simp [qb3] at this
theorem c3_full : Safe d3 i3 k3 ∧ Covers d3 i3 k3 := by
  constructor
  · rintro ⟨s,o⟩ hd hi hk
    simp [i3,k3,qa3,qb3] at hi hk
    split at hi <;> omega
  · rintro ⟨s,o⟩ hd hni
    simp [i3,k3,qa3,qb3] at hni ⊢
    split at hni <;> omega

structure C4 where x : Int; y : Int; ox : Int; oy : Int
def d4 (_ : C4) : Prop := True
def i4 (z : C4) : Prop := z.ox = z.x + 1 ∧ z.oy = z.y
def s4 (z : C4) : Prop := z.ox = z.x + 1
def b4 (z : C4) : Prop := z.ox = z.x + 1 ∧ z.oy = z.y + 1
def qa4 (z : C4) : Prop := z.ox ≠ z.x + 1
def qb4 (z : C4) : Prop := z.oy ≠ z.y
def k4 (z : C4) : Prop := qa4 z ∨ qb4 z

theorem c4_weaker : SubsetOn d4 i4 s4 ∧ NewlyAdmitted d4 i4 s4 := by
  constructor
  · rintro z _ hi
    exact hi.1
  · exact ⟨⟨0,0,1,1⟩, by simp [d4,s4,i4]⟩
theorem c4_channel : AcceptsBehavior d4 b4 s4 ∧ ViolatesIntent d4 i4 b4 := by
  constructor
  · rintro z _ hb
    exact hb.1
  · exact ⟨⟨0,0,1,1⟩, by simp [d4,b4,i4]⟩
theorem c4_qa : Safe d4 i4 qa4 ∧ ¬ Covers d4 i4 qa4 := by
  constructor
  · rintro z _ hi hq
    exact hq hi.1
  · intro hc
    have := hc ⟨0,0,1,1⟩ trivial (by simp [i4])
    simp [qa4] at this
theorem c4_qb : Safe d4 i4 qb4 ∧ ¬ Covers d4 i4 qb4 := by
  constructor
  · rintro z _ hi hq
    exact hq hi.2
  · intro hc
    have := hc ⟨0,0,0,0⟩ trivial (by simp [i4])
    simp [qb4] at this
theorem c4_full : Safe d4 i4 k4 ∧ Covers d4 i4 k4 := by
  constructor
  · rintro z _ hi hk
    rcases hk with h | h
    · exact h hi.1
    · exact h hi.2
  · rintro z _ hni
    simp [i4,k4,qa4,qb4] at hni ⊢
    omega

structure C5 where n : Int; o : Int
def d5 (z : C5) : Prop := 0 ≤ z.n ∧ 0 ≤ z.o ∧ z.o ≤ 2
def i5 (z : C5) : Prop := (z.n = 0 → z.o = 0) ∧ (z.n ≠ 0 → z.o = 1)
def s5 (z : C5) : Prop := (z.n = 0 → z.o = 0) ∧ (z.n ≠ 0 → z.o = 1 ∨ z.o = 2)
def b5 (z : C5) : Prop := (z.n = 0 → z.o = 0) ∧ (z.n = 1 → z.o = 1) ∧ (2 ≤ z.n → z.o = 2)
def qa5 (z : C5) : Prop := z.n = 0 ∧ z.o ≠ 0
def qb5 (z : C5) : Prop := z.n ≠ 0 ∧ z.o ≠ 1
def k5 (z : C5) : Prop := qa5 z ∨ qb5 z

theorem c5_weaker : SubsetOn d5 i5 s5 ∧ NewlyAdmitted d5 i5 s5 := by
  constructor
  · rintro ⟨n,o⟩ hd hi
    simp [i5,s5] at hi ⊢
    omega
  · exact ⟨⟨2,2⟩, by simp [d5,s5,i5]⟩
theorem c5_channel : AcceptsBehavior d5 b5 s5 ∧ ViolatesIntent d5 i5 b5 := by
  constructor
  · rintro ⟨n,o⟩ hd hb
    simp [b5,s5] at hb ⊢
    omega
  · exact ⟨⟨2,2⟩, by simp [d5,b5,i5]⟩
theorem c5_qa : Safe d5 i5 qa5 ∧ ¬ Covers d5 i5 qa5 := by
  constructor
  · rintro ⟨n,o⟩ hd hi hq
    simp [i5,qa5] at hi hq
    omega
  · intro hc
    have := hc ⟨2,2⟩ (by simp [d5]) (by simp [i5])
    simp [qa5] at this
theorem c5_qb : Safe d5 i5 qb5 ∧ ¬ Covers d5 i5 qb5 := by
  constructor
  · rintro ⟨n,o⟩ hd hi hq
    simp [i5,qb5] at hi hq
    omega
  · intro hc
    have := hc ⟨0,1⟩ (by simp [d5]) (by simp [i5])
    simp [qb5] at this
theorem c5_full : Safe d5 i5 k5 ∧ Covers d5 i5 k5 := by
  constructor
  · rintro ⟨n,o⟩ hd hi hk
    simp [i5,k5,qa5,qb5] at hi hk
    omega
  · rintro ⟨n,o⟩ hd hni
    simp [i5,k5,qa5,qb5] at hni ⊢
    omega

-- Exact characterization instantiated on every complete kernel.
theorem c0_exact : GuardAccepts d0 k0 s0 ↔ SubsetOn d0 s0 i0 := q7 d0 i0 k0 s0 c0_full.1 c0_full.2
theorem c1_exact : GuardAccepts d1 k1 s1 ↔ SubsetOn d1 s1 i1 := q7 d1 i1 k1 s1 c1_full.1 c1_full.2
theorem c2_exact : GuardAccepts d2 k2 s2 ↔ SubsetOn d2 s2 i2 := q7 d2 i2 k2 s2 c2_full.1 c2_full.2
theorem c3_exact : GuardAccepts d3 k3 s3 ↔ SubsetOn d3 s3 i3 := q7 d3 i3 k3 s3 c3_full.1 c3_full.2
theorem c4_exact : GuardAccepts d4 k4 s4 ↔ SubsetOn d4 s4 i4 := q7 d4 i4 k4 s4 c4_full.1 c4_full.2
theorem c5_exact : GuardAccepts d5 k5 s5 ↔ SubsetOn d5 s5 i5 := q7 d5 i5 k5 s5 c5_full.1 c5_full.2

end C
