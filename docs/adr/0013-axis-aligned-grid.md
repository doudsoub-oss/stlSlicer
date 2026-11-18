# ADR-0013: The grid model is axis-aligned by design

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §1.4, §1.5, §4.3

## Context
Piece IDs, nudging, the assembly order and the frames all assume planes perpendicular to the cutting-frame axes.

## Decision
Cuts are axis-aligned planes on a grid in the cutting frame. Non-axis-aligned or curved cuts are out of scope for v1 (PLAN.md §11).

## Options considered
### Option A — Axis-aligned grid
Simple IDs, staged assembly, predictable behaviour. Cuts may cross visible details.
### Option B — Arbitrary planes
Better cuts for some models, but breaks IDs, assembly order and nudging.

## Consequences
- Easier: every downstream algorithm stays simple.
- Harder: some models get cuts in awkward places.
- Revisit when: v2 adds arbitrary cut planes.
