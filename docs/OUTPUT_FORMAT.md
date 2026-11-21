# Output format

For users and tool authors. The output folder, file naming, every field of `assembly.json`, and
the history of `schema_version`. A test checks this file against `assembly.schema.json` (from
Phase 9).

## Folder layout

A split writes:

```text
out/
└── dowels/
    ├── dowel_d5.0_l20.0.stl     # one file per (diameter, length)
    └── dowel_d5.0_l18.0.stl
```

There is no `dowels/` folder when the run has no loose pins (`--connector peg` or `none`).
TODO (Phase 9): `parts/`, `assembly.json`, `assembly.md`, `preview_exploded.glb`.

`stlsplit --calibrate` writes:

```text
out/
└── calibration/
    ├── block.stl                # print 2
    ├── pin_d5.0_l20.0.stl       # print one per hole
    └── README.md                # how to print, test and read the codes
```

## File naming

| File | Content | Geometry |
|---|---|---|
| `dowels/dowel_d{d:.1f}_l{L:.1f}.stl` | One loose pin of diameter d and length L, mm. The log gives the quantity (`pins: print 6 x …`). | Axis along X from x = 0 to L, flat on z = 0, bounding-box minimum at the origin |
| `calibration/block.stl` | One calibration bar (PLAN.md §6.3) | Bounding-box minimum at the origin, length along X, holes opening towards +Z, codes on the side face y = 0 |
| `calibration/pin_d{d:.1f}_l{L:.1f}.stl` | The test pin, of length L_max | As a dowel |
| `calibration/README.md` | UTF-8 Markdown, LF line ends, with the table of codes | — |

Names keep one decimal. Two pin lengths that would read the same (15.25 and 15.15 mm) stop the run
with exit 1. STL files are binary with an all-zero header. Nothing in an output depends on the date, the machine
or the path (ADR-0010).

TODO (Phase 9): `parts/{piece}.stl`.

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
