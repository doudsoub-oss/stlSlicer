# ADR-0009: Labels engraved on cut faces, bundled DejaVu Sans Bold, EvenOdd fill

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §4.2, §6.1 (t_lab, H_min, H_max); spike check `matplotlib.font_and_glyph_winding`

## Context
Each piece needs an ID the user can read while assembling, without spoiling the visible surface. Fonts differ between systems. TrueType glyph outer contours are clockwise, so the default Positive fill rule drops them.

## Decision
Each piece's ID is engraved on one of its cut faces (hidden after assembly), using `DejaVuSans-Bold.ttf` bundled with matplotlib. Outlines come from `TextPath` and are filled with `FillRule.EvenOdd`. Text on a pos-piece face is mirrored in u so it reads correctly from outside.

## Options considered
### Option A — Engraved on cut faces
Hidden, no extra parts. Needs room on a face (W003).
### Option B — Embossed or on outer faces
Always room, but visible on the finished model.
### Option C — System fonts
More choice, but breaks determinism across machines.

## Consequences
- Easier: same output everywhere; strokes thick enough to print.
- Harder: small faces get no label.
- Revisit when: users need labels on pieces without cut faces.
