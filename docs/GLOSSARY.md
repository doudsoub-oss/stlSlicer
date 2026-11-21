# Glossary

Terms used in the code and the docs. Symbols refer to PLAN.md §6, where every value is defined.

| Term | Meaning |
|---|---|
| **Assembly step** | One join in the assembly order: a sub-assembly moved along one axis onto another (`assembly.md`). Numbered `stage.join`, e.g. `2.3`. |
| **Clear path** | A straight way out for a sub-assembly, along the join's axis and away from the plane, with nothing on its side in the way. A step without a proven one gets W013. |
| **Axial play** (a) | Extra hole depth beyond each pin end: each hole is h(L) = L/2 + a deep (10.5 mm for a 20 mm pin), so there is room for glue and the pin never bottoms out. |
| **Candidate** | A possible connector axis point on a face: a point of the g = d/4 grid inside the safe region, or a part's polylabel point. Candidates are tried in a fixed order until enough pass the 3D checks. |
| **Body** | One connected solid: an outer shell with the voids it holds. A grid cell can contain several bodies; each becomes a piece. |
| **Calibration kit** | Two small bars with holes of increasing clearance, printed once to choose `--clearance`. |
| **Cell** | One box of the grid, indexed (i, j, k) from 0 along X, Y, Z. Its sides lie between consecutive planes (or 0 and the model's extent), and it fits the usable volume. |
| **Clearance** (c) | Radial gap added to every hole so a pin fits; printer-dependent. |
| **Connector** | A dowel hole pair or a peg and its hole, on a cut face. ID `{face}/c{n}`. |
| **Cut face** | One connected contact region between two pieces on one cut plane, with exactly one piece on each side. ID `{neg piece}~{pos piece}`, plus `#2`, `#3`, … for several regions of the same pair. |
| **Cut plane** | An axis-aligned plane where the model is cut, defined by its axis, index and offset. |
| **Cutting frame** | The coordinate frame after auto-orientation and translation to the origin: x_cut = R · x_in + t, R one of six proper rotations (never a mirror), t putting the model's bounding-box minimum at (0, 0, 0). All pipeline geometry and output files use it. |
| **Diagnostic** | A coded message (`W001`…) with a severity (`info`, `warning`, `partial`) and the IDs it concerns. |
| **Dowel / pin** | A loose cylindrical pin printed separately, lying on its flat. |
| **Even grid** | The grid that splits each axis into equal cells, the fewest that fit the usable volume. |
| **Flat** (f) | A small flat along a pin so it lies on the bed, and air and glue can escape. |
| **Footprint guard** | The condition for merging a small piece: no other piece of its cell lies in its shadow along the axis of its cut faces, so the merged piece can be put in place with one straight move. |
| **Inverted body** | A closed shell whose faces point the wrong way for where it lies (e.g. a body exported inside out); repair turns it the right way out (W011). |
| **Island** | A tiny region of a cut face (area below 4·π·(d/2)²), penalised when nudging planes. |
| **Label region** | Where a piece's label may go on a cut face: the region inset by w, clear of the connectors, with at least `labels.depth` + w of material behind it. |
| **Margin** (m) | Space kept free on each side of every axis of the build volume. |
| **Neg / pos piece** | The piece on the local z < offset side / z > offset side of a cut face. |
| **Nudging** | Moving a cut plane a little from its even-grid position to get better cut faces: fewer faces without room for a connector, then fewer islands. |
| **Peg** | A connector printed as part of one piece, sticking out into a hole of the other. |
| **Piece** | One output part: a body in a cell, ID `X{i}-Y{j}-Z{k}` plus `-a`, `-b` for several bodies. A piece may have absorbed small pieces of neighbouring cells (`merged_from`). |
| **Plane-local frame** | Coordinates attached to a cut plane: (u, v) on the plane, z along its normal. |
| **Polylabel point** | The point of a polygon farthest from its boundary; used to order regions. |
| **Printable volume** | What a final piece must fit, a peg included: bed − 2 × margin per axis, in every connector mode (invariant I2). 210 × 210 × 240 mm by default. |
| **Reference volume** | The volume of the solid after repair, shell normalization and `--simplify`; later volume checks compare against it (invariant I3). |
| **Region** | The area of a cut face: a polygon, possibly with holes, in the plane's (u, v), where the model is solid on both sides of the plane (`slice(o − ε) ∩ slice(o + ε)`), clipped to the two cells. |
| **Safe region** | The region of a cut face inset by `w + r_h + ch_h` (5.1 mm by default): where a connector's axis may go, so the hole and its chamfer keep a wall of w on the face. The 3D checks then make sure the wall also holds behind the face. |
| **Section** | Where a plane cuts the model or a piece: polygons in the plane's (u, v). A single section is one-sided when a model face lies on the plane, so cut faces use two sections at ± ε. |
| **Shell** | One closed, connected surface of a mesh. A solid with a void has two shells: the outer one and the void's. |
| **Shell normalization** | Repair step that decides from containment and orientation which shells are solids and which are voids, unions overlapping solids, keeps voids at any depth of nesting, and turns inverted bodies the right way out. |
| **Slack** (of a plane) | How far a cut plane can move on each side while it stays between its neighbours and both cells it bounds still fit the usable volume. Nudging stays within it. |
| **Small piece** | A piece with volume below V_small, merged into a neighbour when allowed. |
| **Standard length** | One of the allowed pin lengths, L_max − k·Δ ≥ L_min (20, 18, 16 by default). A connector takes the longest one whose holes fit the material behind the face on both sides; shorter than L_max gives W002. |
| **Sub-assembly** | Pieces already joined together; a single piece counts as one. |
| **Usable volume** (U) | The space a grid cell may fill, per axis: bed − 2 × margin, minus L_max/2 in peg mode so that a full cell plus its peg still fits the printable volume. 210 × 210 × 240 mm by default (200 × 200 × 230 with pegs). |
| **Void** | An empty space enclosed inside a solid, bounded by an inward-facing shell; repair keeps it. |
