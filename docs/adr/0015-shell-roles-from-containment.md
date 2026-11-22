# ADR-0015: Try the mesh as-is first; shell roles from containment and relative orientation

- **Status:** Accepted
- **Date:** 2026-11-22 (records the behaviour in place since Phase 2, PLAN.md Appendix E, r5)
- **Deciders:** gSbr
- **Supersedes:** ADR-0007
- **Related:** PLAN.md §5.1, §13; docs/ALGORITHMS.md "Repair and shell normalization"; spike checks `trimesh.fix_normals_multibody`, `trimesh.fix_winding_reference_face`, `manifold.signed_shells`

## Context
Many input STLs are valid already, and repair can damage them. Hollow models have internal voids that must survive, and some models hold overlapping shells.

ADR-0007 normalized shells "by sign": positive shells are solids, negative ones are voids. Phase 2 showed that this fills voids. In a model that is inside out as a whole, the outer shell faces in and the void's shell faces out, so by sign the void became a solid (14.06M mm³ instead of 554 829). Subtracting every void from the union of every solid also cut the walls of overlapping hollow parts, and deleted a ball loose inside a void.

## Decision
Repair first tries to build a Manifold from the mesh as-is. Only if that fails does basic repair run, then optional deep repair (`--deep-repair`). `fix_normals` is never called with `multibody=True`, and basic repair keeps each shell's majority orientation.

A shell's role comes from **containment plus its orientation relative to its container**:

1. Each shell's container is the smallest other shell it lies inside.
2. A shell without a container is a solid, turned the right way out if needed, unless it lies inside the union of the outermost solids: it is then a void spanning several solids.
3. A shell facing the same way as its container plays the same role. A shell facing the other way plays the opposite role, at any depth of nesting.
4. Each solid minus the voids it directly contains is one piece. The result is the union of the pieces, minus the spanning voids, plus the pieces inside a spanning void.

## Options considered
### Option A — Containment and relative orientation
Correct for inside-out models, nested bodies and overlapping hollow parts. Costs booleans between shells, limited by bounding-box and volume checks.
### Option B — By sign alone (ADR-0007)
Simple, but fills voids on a model that is inside out as a whole.
### Option C — Union every shell
Fixes overlaps, but fills every void.
### Option D — Always repair
Simple, but can alter valid models.

## Consequences
- Easier: valid models pass through unchanged, and voids survive at any depth.
- Harder: shell classification needs its own fixtures (PLAN.md Appendix D, the hollow-sphere family).
- Code and docs written before this ADR cite ADR-0007 for the same repair stage; read them as pointing here.
- Revisit when: a trimesh or manifold3d upgrade changes repair behaviour (spike).
