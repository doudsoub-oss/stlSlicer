# ADR-0008: Auto-orient uses proper rotations only (det = +1)

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §4.2; `geometry.world_to_local`

## Context
Auto-orient tries the 6 axis orders. The permutation matrix of an odd permutation has det = −1 and silently mirrors the model: a left shoe becomes a right shoe.

## Decision
Every orientation and frame change is a proper rotation (det = +1). An odd axis order needs a sign change on one axis to keep det = +1; the exact construction is specified in PLAN.md Phase 3. Plane-local frames are cyclic permutations of the axes (det = +1). Tests assert det = +1.

## Options considered
### Option A — Proper rotations only
Never mirrors. Slightly more care building matrices.
### Option B — Plain permutation matrices
Simple, but mirrors the model for half of the orders.

## Consequences
- Easier: chirality is always preserved (`chiral_l` fixture).
- Harder: nothing significant.
- Revisit when: never, unless mirroring becomes a feature.
