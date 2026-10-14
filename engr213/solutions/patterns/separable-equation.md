# Separable equation

_Sections: 2.2_

**Spot it:** dy/dx factors as g(x)h(y): you can split x's onto one side and y's onto the other

## Template

The tell: you can write dy/dx = (stuff with only x) · (stuff with only y).

1. Write the equation as dy/dx = g(x)h(y). If it's in differential form (M dx + N dy = 0),
   rearrange to dy/dx = -M/N and try to factor.
2. Divide both sides by h(y): (1/h(y)) dy/dx = g(x). Call p(y) = 1/h(y).   ← slide notation
3. Multiply by dx: p(y) dy = g(x) dx  (all y's left, all x's right).
4. Integrate both sides: ∫ p(y) dy = ∫ g(x) dx  →  H(y) = G(x) + c.
   Use ONE constant only (Zill: "in solving first-order DEs, use only one constant").
   If you get logs, use ln|c| as the constant so you can combine them (Zill Example 1).
5. Solve for y if easy; otherwise leave it implicit (H(y) = G(x) + c is fine).
6. IVP? Plug in x0, y0 to find c. Then state the interval of validity.
7. Lost solutions: check any y-value that made h(y) = 0 (see Traps).

## Variations

- **Plain separable, solve for y.** dy/dx = x²y⁴e^{5x−3y}, dy/dx = sin5x, x dy/dx = 4y.
  Spot: f(x,y) visibly factors into x-only times y-only. Method unchanged.
  Likelihood: High — the standard form in slides + Exercises 2.2 #1–22 (assigned #1,7,9,13,19).

- **Separable IVP (find c, then explicit y + interval).** dy/dx = −x/y, y(4) = −3; dy/dx = 1+y², y(0)=0.
  Spot: an initial condition y(x0)=y0 is given. Extra step: solve for c, pick the right branch,
  report interval of validity (e.g. −5<x<5, or (−π/2, π/2) for y = tan x).
  Likelihood: High — slide Example 2, Exercises 2.2 #23–30 (assigned #25,27).

- **Hidden / scrambled form (must factor first).** dx + e^{3x}dy = 0; (1+y²)¹ᐟ² dx = y(1+x²)¹ᐟ² dy;
  dy/dx = (xy+3x−y−3)/(xy−2x+4y−8) which factors by grouping.
  Spot: it's in M dx + N dy = 0 or the RHS looks messy but groups into (x-terms)(y-terms).
  Changes: do algebra/factoring before cleaning separating. Likelihood: Medium — Exercises 2.2 #13,19,20.

- **Requires a side technique inside the integral.** Partial fractions: dy/dx = y²−4.
  Integration by parts: e^{2y}−y over e^y with sin2x. Trig identities: sin2x = 2 sinx cosx.
  Spot: after separating, the integral isn't elementary-looking. Method unchanged; just name the
  side skill (partial fractions / integration by parts / identities) and show it.
  Likelihood: Medium — Zill Examples 4 and 5.

- **Integral-defined solution (non-elementary integral).** dy/dx = e^{−x²}, y(2)=6 →
  y = 6 + ∫₂ˣ e^{−t²} dt. Spot: you can separate but can't integrate in elementary terms.
  Changes: leave answer as a definite integral with the IC baked in.
  Likelihood: Low — Zill Example 6, Exercises 2.2 #31–34.

- **Losing a solution / equilibrium solution.** dy/dx = y²−4, dy/dx = x√(1−y²), dy/dx = xy^{1/2}.
  Spot: h(y) has a root (y = ±2, y = ±1, y = 0). That constant y is also a solution.
  Likelihood: Medium — Zill Example 4 + the uniqueness discussion (Eq. 9).

## Traps

- Dividing by h(y) that can be zero: if h(r) = 0, then y = r is a constant solution. It may not
  appear in the integrated family (it's a "singular"/lost solution). Check h(y) = 0 and list those
  y-values separately (Zill Example 4: y = −2 is lost even though y = 2 is not).
- ln|y| needs the absolute value bars. Then e^{ln|y|} = |y|, and ±e^{c} collapses into one new
  constant c.
- Only ONE constant. Don't write +c₁ on the left and +c₂ on the right.
- When you have logs on both sides, choose ln|c| as the constant so you can combine with log rules
  and then exponentiate (Zill Example 1 → y = c(1+x)).
- Applying the IVP too early: get the general solution (with c) first, THEN plug in x0, y0.
- Explicit solution branches: y² = 25 − x² gives y = ±√(25−x²). Use the IC to pick the sign
  (y(4) = −3 → the lower branch) and give the interval where it's valid.

## Most likely on the exam

Plain separable and the separable IVP (with interval of validity). Evidence: Lecture 2 slides give
separables a full worked method plus Examples 1–4 (the whole first half of the 2.2–2.4 lecture), and
the outline assigns Exercises 2.2 #1,7,9,13,19,25,27,31 — a mix of plain and IVP. No past exams are
in the course materials, so this is from the slides + outline, not exam files. The lost-solution /
equilibrium twist is the favorite "gotcha" (Zill spends a whole subsection on it) and is worth having
ready.

## Problems solved (9)

- 2.2 #1 — dy/dx = sin 5x
- 2.2 #2 — dy/dx = (x + 1)²
- 2.2 #3 — dx + e^(3x) dy = 0
- 2.2 #4 — dy − (y − 1)² dx = 0
- 2.2 #5 — x dy/dx = 4y
- 2.2 #6 — dy/dx + 2xy² = 0 ✓
- 2.2 #7 — dy/dx = e^(3x+2y) ✓
- 2.2 #8 — e^x·y·dy/dx = e^(-y) + e^(-2x-y) ✓
- 2.2 #9 — y·ln x·dx/dy = ((y+1)/x)² ✓
