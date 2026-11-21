# ADR-0006: Standard pin lengths, symmetric pins, explicit axial play

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §6.1, §6.2; ADR-0005

## Context
Pins must fit pieces of varying depth behind each face. Arbitrary lengths would create many pin files, asymmetric pins can be inserted the wrong way, and a pin that bottoms out prevents the joint from closing.

## Decision
`--dowel-length` is the exact length of a full pin (L_max). Shorter pins use standard lengths `L_max − k·Δ ≥ L_min` (20, 18, 16 by default). Each hole is `h(L) = L/2 + a` deep on both sides (axial play a = 0.5 mm). Pins have an end chamfer and a flat of depth f to lie on the bed.

## Options considered
### Option A — Standard lengths, symmetric
Few pin files, no orientation, glue room. Some depth is unused.
### Option B — Per-connector optimal lengths
Uses depth best, but many pin files.
### Option C — Asymmetric pins
More flexible, but users can insert them the wrong way.

## Consequences
- Easier: one definition of length; few pin files with counts.
- Harder: shallow faces lose connectors below L_min (W001).
- As built (Phase 7): identical pins share one file, `dowels/dowel_d{d:.1f}_l{L:.1f}.stl`, printed the number of times the log gives. A pin lies along X on its flat (z = 0), 2.71 mm wide at d = 5. The end chamfer must be smaller than the pin's radius (PLAN.md §7.5, r10).
- Revisit when: users need pins shorter than 3·d.
