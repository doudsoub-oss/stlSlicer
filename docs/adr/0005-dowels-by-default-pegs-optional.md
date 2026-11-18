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
- Revisit when: other connector types (dovetails, snap-fits, v2) are added.
