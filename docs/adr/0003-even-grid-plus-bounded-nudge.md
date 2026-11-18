# ADR-0003: Even grid plus a bounded nudge with a lexicographic score

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §5.1, §6.1 (W_n, δ_n), §7.3

## Context
The model must be split into cells that each fit the usable volume U. Plane positions affect face quality (tiny islands, faces too small for connectors). A global optimiser is complex and unpredictable.

## Decision
Each axis gets the fewest equal cells that fit U (the even grid). Each plane may then move within ± `nudge_window` in steps of `nudge_step`, choosing the position with the best lexicographic score. Ties keep the plane at its even-grid position. Every cell still fits U.

## Options considered
### Option A — Even grid + bounded nudge
Predictable, always fits, cheap. Can miss a better global layout.
### Option B — Even grid only
Simplest, but cuts through thin necks and leaves islands.
### Option C — Global optimisation of all planes
Potentially better faces, but slow, hard to test and hard to make deterministic.

## Consequences
- Easier: results are predictable and explainable; ties are stable.
- Harder: some models get worse faces than an optimiser would find.
- Revisit when: users report many W001 faces that a slightly different grid would avoid (v2).
