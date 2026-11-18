# ADR-0004: Assembly in stages: X rows, then Y layers, then the Z stack

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §5.1, §5.3 (I7), §13

## Context
Straight pins need each join to slide along one axis. A piece-by-piece order is impossible on any 2×2 layer: the last piece has to slide in along two axes at once.

## Decision
Assembly is staged. Stage 1 joins pieces along X into rows, stage 2 joins rows along Y into layers, stage 3 stacks layers along Z. Each step joins two different sub-assemblies, and all its faces are perpendicular to its axis (I7).

## Options considered
### Option A — Staged sub-assemblies
Always physically possible with straight pins. Needs glue to cure per stage.
### Option B — Piece-by-piece order
Simpler instructions, but impossible on 2×2 layers.
### Option C — Search for any feasible order
Flexible, but complex and gives no guarantee where staged order already does.

## Consequences
- Easier: the order is always feasible and easy to explain.
- Harder: sub-assemblies may be large and awkward to handle.
- Revisit when: non-axis-aligned cuts or other connector types (v2) are added.
