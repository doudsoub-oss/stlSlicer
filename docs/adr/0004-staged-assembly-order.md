# ADR-0004: Assembly in stages: X rows, then Y layers, then the Z stack

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Amended:** 2026-11-21 (PLAN.md Appendix E, r12): the rule within a plane; the stages are unchanged
- **Related:** PLAN.md §5.1, §5.3 (I7), §13; ADR-0012

## Context
Straight pins need each join to slide along one axis. A piece-by-piece order is impossible on any 2×2 layer: the last piece has to slide in along two axes at once.

## Decision
Assembly is staged. Stage 1 joins pieces along X into rows, stage 2 joins rows along Y into layers, stage 3 stacks layers along Z. Each step joins two different sub-assemblies with one straight move, and all its faces are perpendicular to its axis (I7).

**Within a stage (r12).** Planes are taken in increasing order. On one plane, the sub-assemblies its faces connect are taken apart one at a time, each one leaving the others connected and having a clear path away from the plane, and the joins are that sequence reversed. A bounded search with backtracking looks for such an order. Joining in plain face order isn't enough: when a model's loop crosses a plane four times, it can pair two sub-assemblies that each hold pieces on both sides of the plane, and closing their pins would take +X and −X at once. A sub-assembly that hasn't been joined on this plane yet lies entirely on one side of it, so all its faces close in the same direction.

A step with no clear path that can be shown gets **W013** (partial), and stays in the order.

## Options considered
### Option A — Staged sub-assemblies
Every join is one straight move along its pins, with W013 for the rare move that can't be shown clear. Needs glue to cure per stage.
### Option B — Piece-by-piece order
Simpler instructions, but impossible on 2×2 layers.
### Option C — Search for any feasible order
Flexible, but complex and gives no guarantee where staged order already does.

## Consequences
- Easier: the order is easy to explain, and every join has one direction.
- Interlocked bodies can't always be assembled with straight moves; W013 says so instead of giving a step that silently can't be done.
- Harder: sub-assemblies may be large and awkward to handle.
- Revisit when: non-axis-aligned cuts or other connector types (v2) are added.
