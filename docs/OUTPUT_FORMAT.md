# Output format

For users and tool authors. The output folder, file naming, every field of `assembly.json`, and
the history of `schema_version`. A test checks this file against `assembly.schema.json` (from
Phase 9).

## Folder layout

TODO (Phase 9): `parts/`, `dowels/`, `assembly.json`, `assembly.md`, `preview_exploded.glb`.

## File naming

TODO (Phase 9): `parts/{piece}.stl`, `dowels/dowel_d{d:.1f}_l{L:.1f}.stl`.

## Identifiers

Every ID is ASCII and stable: the same model and settings give the same IDs (PLAN.md §4.3).

| Thing | Format | Example | Order |
|---|---|---|---|
| Cell | (i, j, k), 0-based along X, Y, Z of the cutting frame | (1, 0, 2) | i, then j, then k |
| Piece | `X{i}-Y{j}-Z{k}`, plus `-a`, `-b`, … (`-z`, then `-aa`, `-ab`, …) when the cell holds several bodies | `X1-Y0-Z2-b` | Cell order, then suffix; suffixes by (bbox min z, min y, min x, larger volume first) |
| Cut face | `{neg piece}~{pos piece}`, plus `#2`, `#3`, … when the same two pieces share several regions | `X0-Y0-Z0~X1-Y0-Z0#2` | By plane (X planes first), then neg cell, then region (polylabel point u, then v) |

The neg piece is on the low side of the plane, the pos piece on the high side. A small piece
merged into a neighbour disappears: the neighbour keeps its ID and lists the absorbed IDs in
`merged_from` (W005).

TODO (Phase 5): connectors (`{face}/c{n}`). TODO (Phase 8): labels.

## `assembly.json`

TODO (Phase 9): every field.

## `assembly.md`

TODO (Phase 9)

## `schema_version` history

TODO (Phase 9)
