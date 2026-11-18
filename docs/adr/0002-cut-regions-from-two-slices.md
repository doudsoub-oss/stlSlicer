# ADR-0002: Cut regions are the intersection of two slices at offset ± ε

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §4.2, §6.1 (ε), §13; spike check `manifold.slice_at_step`

## Context
A cut face's region decides where connectors and labels may go, for both pieces. When a model face lies exactly on the cut plane (a step), a single `slice` at the offset is one-sided: for a column under a plate it returns the plate's 1600 mm² instead of the 100 mm² contact.

## Decision
The region of a cut face is computed once from the normalized input body as `slice(offset − ε) ∩ slice(offset + ε)`, with ε = `advanced.section_epsilon` (0.01 mm). Both pieces use this one region.

## Options considered
### Option A — Intersection of slices at ± ε
Correct at steps in both directions (verified), one source of truth. Cost: two slices per plane.
### Option B — A single slice at the offset
Simplest, but wrong whenever a model face lies on the plane.
### Option C — Intersect the two pieces' actual cut faces
Exact, but requires extracting faces from meshes after splitting, which is fragile.

## Consequences
- Easier: both sides of a face agree by construction.
- Harder: features thinner than 2ε at the plane are ignored (acceptable at 0.02 mm).
- Revisit when: models with features near 0.02 mm at cut planes matter.
