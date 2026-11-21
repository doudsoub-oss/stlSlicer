# ADR-0005: Dowels by default; pegs optional, with U reduced by the protrusion

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §6.1 (U, p), §7.2 `--connector`; ADR-0006

## Context
Pieces need alignment features. Loose pins printed lying flat are strong; pegs printed as part of a piece either print vertically (weak layers across the peg) or need support.

## Decision
The default connector is a loose dowel with holes on both sides. `--connector peg` is available on any face. In peg mode U is reduced by `L_max/2` per axis so a protruding peg still fits the build volume. `--connector none` disables connectors.

## Options considered
### Option A — Dowels by default, pegs optional
Strongest default, extra pins to print.
### Option B — Pegs by default
No loose parts, but weak or needing support.
### Option C — Dowels only
Simplest, but some users prefer no loose parts.

## Consequences
- Easier: strong joints by default.
- Harder: peg mode makes more pieces because U shrinks.
- What must fit (clarified in Phase 7, PLAN.md Appendix E, r10): **cells** fit the reduced U, and a **final piece, peg included,** fits `bed − 2·margin`. On a 120 mm bed with a 5 mm margin, U is 100 mm and a full cell plus its 10 mm peg is 110 mm. Invariant I2 and `tools.check_piece` use this limit (`derived(cfg).printable`).
- The peg is fused to the neg piece and reaches 0.01 mm into it (`TOOL_OVERLAP`): a cut face's vertices can be off the plane by float noise, and a peg based exactly on the plane can stay a separate shell (docs/LIBRARY_NOTES.md, `manifold.face_float_noise`).
- Revisit when: other connector types (dovetails, snap-fits, v2) are added.
