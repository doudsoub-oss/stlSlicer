# ADR-0012: Small pieces are merged only under the footprint guard

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §6.1 (V_small), §4.3 (`merged_from`); ADR-0004

## Context
Grid cuts can leave slivers (volume below V_small = 500 mm³) that are hard to print and handle. Merging them blindly into a neighbour can make a piece that no longer fits U or breaks the staged assembly order.

## Decision
A small piece is merged into a neighbour only when the footprint guard passes; the guard is specified in PLAN.md Phase 4 and will be restated here precisely when that phase lands. The merged piece must still fit U and keep the staged assembly order valid. The surviving piece keeps its ID and lists the absorbed IDs in `merged_from` (W005). Otherwise the piece stays on its own (W004). `small_piece_volume = 0` disables merging.

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
