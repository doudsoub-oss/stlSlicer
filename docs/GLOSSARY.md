# Glossary

Terms used in the code and the docs. Symbols refer to PLAN.md §6, where every value is defined.

| Term | Meaning |
|---|---|
| **Assembly step** | One join in the assembly order: a sub-assembly moved along one axis onto another (`assembly.md`). Numbered `stage.join`, e.g. `2.3`. |
| **Axial play** (a) | Extra hole depth beyond each pin end: room for glue, and the pin never bottoms out. |
| **Body** | One connected solid. A grid cell can contain several bodies. |
| **Calibration kit** | Two small bars with holes of increasing clearance, printed once to choose `--clearance`. |
| **Cell** | One box of the grid, indexed (i, j, k) from 0 along X, Y, Z. |
| **Clearance** (c) | Radial gap added to every hole so a pin fits; printer-dependent. |
| **Connector** | A dowel hole pair or a peg and its hole, on a cut face. ID `{face}/c{n}`. |
| **Cut face** | The contact area between two pieces on one cut plane. ID `{neg piece}~{pos piece}`, plus `#2`, `#3`, … for several regions of the same pair. |
| **Cut plane** | An axis-aligned plane where the model is cut, defined by its axis, index and offset. |
| **Cutting frame** | The coordinate frame after auto-orientation and translation to the origin; all pipeline geometry and output files use it. |
| **Diagnostic** | A coded message (`W001`…) with a severity (`info`, `warning`, `partial`) and the IDs it concerns. |
| **Dowel / pin** | A loose cylindrical pin printed separately, lying on its flat. |
| **Even grid** | The grid that splits each axis into equal cells, the fewest that fit the usable volume. |
| **Flat** (f) | A small flat along a pin so it lies on the bed, and air and glue can escape. |
| **Inverted body** | A closed shell whose faces point the wrong way for where it lies (e.g. a body exported inside out); repair turns it the right way out (W011). |
| **Island** | A tiny region of a cut face (area below 4·π·(d/2)²), penalised when nudging planes. |
| **Margin** (m) | Space kept free on each side of every axis of the build volume. |
| **Neg / pos piece** | The piece on the local z < offset side / z > offset side of a cut face. |
| **Nudging** | Moving a cut plane a little from its even-grid position to get better cut faces. |
| **Peg** | A connector printed as part of one piece, sticking out into a hole of the other. |
| **Piece** | One output part: a body in a cell, ID `X{i}-Y{j}-Z{k}` plus `-a`, `-b` for several bodies. |
| **Plane-local frame** | Coordinates attached to a cut plane: (u, v) on the plane, z along its normal. |
| **Polylabel point** | The point of a polygon farthest from its boundary; used to order regions. |
| **Reference volume** | The volume of the solid after repair, shell normalization and `--simplify`; later volume checks compare against it (invariant I3). |
| **Region** | A connected part of a cut face (polygon, possibly with holes), in (u, v). |
| **Safe region** | The region inset by `w + r_h + ch_h`: where a connector's axis may go. |
| **Shell** | One closed, connected surface of a mesh. A solid with a void has two shells: the outer one and the void's. |
| **Shell normalization** | Repair step that decides from containment and orientation which shells are solids and which are voids, unions overlapping solids, keeps voids at any depth of nesting, and turns inverted bodies the right way out. |
| **Small piece** | A piece with volume below V_small, merged into a neighbour when allowed. |
| **Standard length** | One of the allowed pin lengths, L_max − k·Δ ≥ L_min (20, 18, 16 by default). |
| **Usable volume** (U) | The build volume minus twice the margin per axis (minus half a pin in peg mode). |
| **Void** | An empty space enclosed inside a solid, bounded by an inward-facing shell; repair keeps it. |
