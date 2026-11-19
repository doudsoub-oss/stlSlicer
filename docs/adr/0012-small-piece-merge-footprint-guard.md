# ADR-0012: Small pieces are merged only under the footprint guard

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §6.1 (V_small), §4.3 (`merged_from`); ADR-0004

## Context
Grid cuts can leave slivers (volume below V_small = 500 mm³) that are hard to print and handle. Merging them blindly into a neighbour can make a piece that no longer fits U or breaks the staged assembly order.

## Decision
A small piece is merged into a neighbour only when the footprint guard passes. The merged piece must still fit U and keep the staged assembly order valid. The surviving piece keeps its ID and lists the absorbed IDs in `merged_from` (W005). Otherwise the piece stays on its own (W004). `small_piece_volume = 0` disables merging.

Precisely (PLAN.md Phase 4, task 6; restated when Phase 4 landed, r7): a piece S with a volume under V_small, taken in piece order, is merged into its neighbour P when
1. S shares cut faces with exactly one piece P (none: a separate body, W008, no merge);
2. S hasn't absorbed a piece itself;
3. the bounding box of P and S together fits U (peg-adjusted), checked with `grid.fits`;
4. **footprint guard:** no other piece of S's cell overlaps S's projection along the axis of the shared faces, grown by `MERGE_MARGIN` = 0.05 mm, by more than 1e-6 mm²;
5. the merged piece cut from the model (the body holding S) has the volume of P + S within 1e-6.

The merged piece is cut again from the normalized body, by difference (P's cell joined to a prism over S's grown projection, kept within S's cell), never glued as P ∪ S: a union of two split halves keeps a face inside where the plane passes through mesh vertices (docs/LIBRARY_NOTES.md, `manifold.union_of_split_halves`). The proof sketch that the guard keeps every assembly step one straight move is in docs/ALGORITHMS.md, "Small-piece merge".

## Options considered
### Option A — Guarded merge
Avoids slivers without breaking guarantees.
### Option B — Always merge
No slivers, but can break fit or assembly.
### Option C — Never merge
Simplest, but leaves unprintable slivers.

## Consequences
- Easier: fewer tiny parts.
- Harder: the guard needs its own tests (`knob` fixture).
- Revisit when: nudging (ADR-0003) makes slivers rare enough to drop merging.
