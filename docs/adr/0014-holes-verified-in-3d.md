# ADR-0014: Every hole is verified in 3D: rays, exact containment and min_gap

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §5.3 (I5, I6), §6.1 (ε_ray); spike checks `manifold.ray_cast`, `manifold.min_gap`

## Context
The 2D safe region (the region inset by `w + r_h + ch_h`) guarantees material around a hole only on the face itself. It misses pieces that narrow behind the face, and holes on perpendicular faces that collide inside a piece near shared edges.

## Decision
Every candidate hole is checked in 3D before it is accepted: rays from the face (starting `RAY_START_OFFSET` inside the piece, depth from `RayHit.position`) check the depth; an exact containment check verifies the hole plus wall lies inside the piece; `min_gap` between holes of the same piece must be ≥ `min_wall`.

## Options considered
### Option A — 2D candidates + 3D checks
Catches narrowing and collisions; costs ray casts and booleans per candidate.
### Option B — 2D inset only
Fast, but produces holes that break through walls.
### Option C — Full boolean then validate
Exact, but much slower and harder to report why a candidate failed.

## Consequences
- Easier: holes never break through (I5, I6).
- Harder: placement is slower; performance must be watched (N2).
- Revisit when: placement dominates run time.
