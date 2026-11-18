# ADR-0001: manifold3d for all solid geometry

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §2, §9.2; docs/LIBRARY_NOTES.md; ADR-0010

## Context
Every output piece must be a closed, valid solid (F2). Booleans, plane splits, sections, ray casts and gap queries all have to agree on the same geometry. Hand-made or fragile booleans are the main source of broken STLs in tools of this kind.

## Decision
All solid geometry (booleans, plane splits, sections, ray casts, `min_gap`, simplification, extrusion) goes through `manifold3d`. `trimesh` is used only for file I/O, basic repair and the GLB preview scene, and only through the wrappers in `geometry.py` and `io.py`.

## Options considered
### Option A — manifold3d as the single kernel
Guaranteed-manifold booleans, fast native `slice`, `ray_cast` and `min_gap`, Apache-2.0. Cost: a native dependency and its own API quirks (recorded in LIBRARY_NOTES).
### Option B — trimesh booleans (via external engines)
Familiar API, but booleans depend on an external backend (Blender, manifold itself, or OpenSCAD) and results are not guaranteed manifold.
### Option C — A CAD kernel (OpenCASCADE)
Exact B-rep geometry, but a heavy dependency, slow on large triangle meshes, and STL input still has to be converted.

## Consequences
- Easier: one geometry model; outputs are manifold by construction; deterministic results (ADR-0010).
- Harder: conversions between trimesh and manifold must be kept in `geometry.py`; library quirks must be tracked by `scripts/api_spike.py`.
- Revisit when: manifold3d stops being maintained, or a required operation (e.g. curved cuts, v2) is not available.
