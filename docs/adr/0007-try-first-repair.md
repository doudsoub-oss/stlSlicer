# ADR-0007: Try the mesh as-is first; sign-aware shell normalization; never `fix_normals(multibody=True)`

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §5.1, §13; spike check `trimesh.fix_normals_multibody`

## Context
Many input STLs are valid already, and repair can damage them. Hollow models have internal voids that must survive. `trimesh.repair.fix_normals(multibody=True)` flips voids outward and turns a hollow sphere solid (verified). Some models have overlapping shells.

## Decision
Repair first tries to build a Manifold from the mesh as-is. Only if that fails does basic repair run, then optional deep repair (`--deep-repair`). Shells are normalized by sign: overlapping positive shells are unioned, voids are kept. `fix_normals` is only ever called with `multibody=False`, and only when repair is needed.

## Options considered
### Option A — Try-first, sign-aware
Doesn't damage valid models, keeps voids. More logic to test.
### Option B — Always repair
Simple, but can alter valid models.
### Option C — Union every shell
Fixes overlaps, but fills voids.

## Consequences
- Easier: valid models pass through unchanged.
- Harder: shell classification must be tested on hollow and overlapping fixtures.
- Revisit when: a trimesh or manifold3d upgrade changes repair behaviour (spike).
