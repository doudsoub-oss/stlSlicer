# ADR-0009: Labels engraved on cut faces, bundled DejaVu Sans Bold, EvenOdd fill

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §4.2, §6.1 (t_lab, H_min, H_max); spike check `matplotlib.font_and_glyph_winding`

## Context
Each piece needs an ID the user can read while assembling, without spoiling the visible surface. Fonts differ between systems. TrueType glyph outer contours are clockwise, so the default Positive fill rule drops them.

## Decision
Each piece's ID is engraved on one of its cut faces (hidden after assembly), using `DejaVuSans-Bold.ttf` bundled with matplotlib. Outlines come from `TextPath` and are filled with `FillRule.EvenOdd`. Text on a pos-piece face is mirrored in u so it reads correctly from outside.

A label needs `labels.depth + min_wall` of material behind it, holes counted, and stays `min_wall` from any spot that lacks it: an engraving through a thin part would detach the counters of `0`, `8` and `b` as loose shells. Faces are tried by decreasing free area until the text fits, and the text is centred on the point with the polylabel clearance nearest the region's centroid, since the polylabel point of a long face can sit near one end. If it doesn't fit there, nearby positions are tried. A custom font must have its own glyph for every label character (PLAN.md Appendix E, r11).

## Options considered
### Option A — Engraved on cut faces
Hidden, no extra parts. Needs room on a face (W003).
### Option B — Embossed or on outer faces
Always room, but visible on the finished model.
### Option C — System fonts
More choice, but breaks determinism across machines.

## Consequences
- Easier: same output everywhere; strokes thick enough to print.
- Harder: small faces, and faces with too little material behind them, get no label (W003).
- Revisit when: users need labels on pieces without cut faces.
