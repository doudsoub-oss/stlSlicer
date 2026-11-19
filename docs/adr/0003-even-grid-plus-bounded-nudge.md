# ADR-0003: Even grid plus a bounded nudge with a lexicographic score

- **Status:** Accepted
- **Date:** 2026-11-17 (details of the nudge added with Phase 6, 2026-11-19)
- **Deciders:** gSbr
- **Related:** PLAN.md §5.1, §6.1 (W_n, δ_n, island), §7.3, Phase 6; docs/ALGORITHMS.md "Plane nudging"

## Context
The model must be split into cells that each fit the usable volume U. Plane positions affect face quality (tiny islands, faces too small for connectors). A global optimiser is complex and unpredictable.

## Decision
Each axis gets the fewest equal cells that fit U (the even grid). Each plane may then move within ± `nudge_window` in steps of `nudge_step`, choosing the position with the best lexicographic score. Ties keep the plane at its even-grid position. Every cell still fits U.

How the nudge works (Phase 6):

- **Moves:** δ = j · `nudge_step` for whole numbers j, with |j| ≤ floor(`nudge_window` / `nudge_step`) (at most 100, a validation rule, so the search stays bounded), the plane strictly between its neighbours, and both cells it bounds still within U (`grid.fits`). That is the window min(W_n, slack), on each side.
- **Score**, lower is better, compared in this order: the number of the plane's cut regions (clipped to cell pairs, as the cutting does) whose safe region is empty; the number of tiny islands (area < 4 · π · (d/2)²); |δ|; δ. The last two make the choice unique and keep a plane where it is when moving gains nothing.
- **Order:** planes one after the other, X, then Y, then Z, each axis by increasing offset; each is scored on the grid the previous moves left, so a move changes its neighbours' slack. No plane is revisited.
- **No coplanar-vertex rule.** manifold3d splits through vertices and the two-slice contact region handles model faces on the plane (ADR-0002). A rule keeping planes away from vertices never terminates on dense meshes.

## Options considered
### Option A — Even grid + bounded nudge
Predictable, always fits, cheap. Can miss a better global layout.
### Option B — Even grid only
Simplest, but cuts through thin necks and leaves islands.
### Option C — Global optimisation of all planes
Potentially better faces, but slow, hard to test and hard to make deterministic.

## Consequences
- Easier: results are predictable and explainable; ties are stable.
- Harder: some models get worse faces than an optimiser would find.
- The score is 2D: it doesn't see the material behind a face. A plane moved just off a neck leaves a thin slab on the neck side, where holes have no depth (W001), though the face is the full section rather than the neck.
- One plane at a time: an X plane is scored before the Y and Z planes move, and isn't revisited after they do.
- Revisit when: users report many W001 faces that a slightly different grid would avoid (v2), or faces that the 2D score accepts but the 3D connector checks reject.
