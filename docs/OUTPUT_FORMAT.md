# Output format

For users and tool authors. The output folder, file naming, every field of `assembly.json`, and
the history of `schema_version`. A test checks this file against `assembly.schema.json`.

## Folder layout

A split writes:

```text
out/
├── parts/
│   ├── X0-Y0-Z0.stl             # one file per piece
│   └── X1-Y0-Z0.stl
├── dowels/
│   ├── dowel_d5.0_l20.0.stl     # one file per (diameter, length)
│   └── dowel_d5.0_l18.0.stl
├── assembly.json                # the assembly map, for tools
├── assembly.md                  # the assembly map, for people
└── preview_exploded.glb         # unless --no-preview
```

There is no `dowels/` folder when the run has no loose pins (`--connector peg` or `none`). While
it runs, stlsplit prepares its files in a `.stlsplit-staging/` folder, which is gone at the end.

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
| `parts/{piece}.stl` | One piece, with its holes, pegs and label | Cutting frame, not re-centred: the pieces fit together as written |
| `dowels/dowel_d{d:.1f}_l{L:.1f}.stl` | One loose pin of diameter d and length L, mm. The log and `assembly.md` give the quantity. | Axis along X from x = 0 to L, flat on z = 0, bounding-box minimum at the origin |
| `assembly.json` | UTF-8 (pure ASCII) JSON, two-space indent, LF line ends | Positions in the cutting frame |
| `assembly.md` | UTF-8 Markdown, LF line ends | — |
| `preview_exploded.glb` | Binary glTF, one node per piece, named after it | Each piece moved from the grid's centre by `preview_spread` × the model's size on that axis, per grid step; 12 fixed colours, by piece order |
| `calibration/block.stl` | One calibration bar (PLAN.md §6.3) | Bounding-box minimum at the origin, length along X, holes opening towards +Z, codes on the side face y = 0 |
| `calibration/pin_d{d:.1f}_l{L:.1f}.stl` | The test pin, of length L_max | As a dowel |
| `calibration/README.md` | UTF-8 Markdown, LF line ends, with the table of codes | — |

Names keep one decimal. Two pin lengths that would read the same (15.25 and 15.15 mm) stop the run
with exit 1. STL files are binary with an all-zero header. Nothing in an output depends on the date, the machine
or the path (ADR-0010).

## Identifiers

Every ID is ASCII and stable: the same model and settings give the same IDs (PLAN.md §4.3).

| Thing | Format | Example | Order |
|---|---|---|---|
| Cell | (i, j, k), 0-based along X, Y, Z of the cutting frame | (1, 0, 2) | i, then j, then k |
| Piece | `X{i}-Y{j}-Z{k}`, plus `-a`, `-b`, … (`-z`, then `-aa`, `-ab`, …) when the cell holds several bodies | `X1-Y0-Z2-b` | Cell order, then suffix; suffixes by (bbox min z, min y, min x, larger volume first) |
| Cut face | `{neg piece}~{pos piece}`, plus `#2`, `#3`, … when the same two pieces share several regions | `X0-Y0-Z0~X1-Y0-Z0#2` | By plane (X planes first), then neg cell, then region (polylabel point u, then v) |
| Connector | `{face}/c{n}` | `X0-Y0-Z0~X1-Y0-Z0/c1` | Acceptance order |
| Label text | The piece's grid digits, then its suffix; engraved on one of its cut faces | `1-0-2b` | One per piece, at most |
| Assembly step | `{stage}.{join}`; the stage is 1 for X, 2 for Y, 3 for Z, even if an earlier stage is empty | `2.3` | The order to perform them |

The neg piece is on the low side of the plane, the pos piece on the high side. A small piece
merged into a neighbour disappears: the neighbour keeps its ID and lists the absorbed IDs in
`merged_from` (W005).

## `assembly.json`

Validated by `src/stlsplit/schemas/assembly.schema.json`. Lengths are in mm, areas in mm², volumes
in mm³, and positions in the cutting frame. Floats are rounded to 6 decimals, and there is no
timestamp or absolute path.

| Top-level field | Type | Content |
|---|---|---|
| `schema_version` | integer | `1` |
| `tool` | object | `name` (`stlsplit`), `version` |
| `input` | object | `file_name`: the input's name, without any folder |
| `settings` | object | The effective configuration, by TOML table: `printer`, `model`, `repair`, `connectors`, `labels`, `output`, `advanced`. `advanced.label_font` is a file name only |
| `frame` | object | `rotation` (its name) and `input_to_cutting`: the 4×4 matrix, row by row, with `x_cut = R · x_in + t` |
| `grid` | object | `usable` (U per axis), `counts` (cells per axis), `extent` (model size), `planes`: offsets per axis under `x`, `y`, `z` |
| `pieces` | array | In piece order; fields below |
| `faces` | array | In face order; fields below |
| `connectors` | array | Fields below |
| `pin_groups` | array | The dowels to print, longest first: `file`, `diameter`, `length`, `quantity` |
| `steps` | array | The joins, in the order to perform them; fields below |
| `separate_parts` | array | The final groups, each a list of piece IDs. One group means the model ends up in one part |
| `diagnostics` | array | In the order reported: `code`, `severity`, `message`, `refs` (IDs) |

**`pieces[]`**

| Field | Content |
|---|---|
| `id`, `file` | Piece ID, and its STL relative to the output folder |
| `grid_index` | Its cell [i, j, k] |
| `volume` | Final volume, holes and pegs included |
| `bounding_box` | `min` and `max`, each [x, y, z], pegs included |
| `face_ids` | Its cut faces |
| `merged_from` | IDs of the small pieces it absorbed |
| `label` | `text`, `face_id`, `height`, or `null` |

**`faces[]`**

| Field | Content |
|---|---|
| `id` | Face ID |
| `axis`, `plane_index`, `offset` | The cut plane: axis 0, 1, 2 for X, Y, Z, its index, its position |
| `piece_neg`, `piece_pos` | The pieces on the low and the high side |
| `area` | Contact area |
| `connector_ids` | Its connectors, in acceptance order |

**`connectors[]`**

| Field | Content |
|---|---|
| `id`, `face_id` | Connector and face IDs |
| `kind` | `dowel` or `peg` (a peg stands on the neg piece) |
| `position` | Axis point on the plane, [x, y, z] |
| `position_uv` | The same point in plane-local (u, v) |
| `diameter`, `pin_length` | d and L; for a peg, L is twice its protrusion |
| `hole_depth_neg`, `hole_depth_pos` | Depth from the face on each side; 0 on a peg's side |

**`steps[]`**

| Field | Content |
|---|---|
| `number`, `stage`, `axis` | E.g. `2.3`, stage 2, axis 1 |
| `moving`, `static` | Piece IDs of the two sub-assemblies, in piece order |
| `direction` | The move of `moving`: `+x`, `-x`, `+y`, `-y`, `+z` or `-z` |
| `face_ids` | Every face between the two sub-assemblies |
| `connector_count` | Connectors on those faces |
| `dowels` | Dowels to insert, longest first: `diameter`, `length`, `quantity` |
| `pegs` | Pegs on those faces |
| `glue_only` | `true` when there is no connector |
| `clear_path` | `false` when no clear straight path could be shown (W013) |

## `assembly.md`

In order: a **summary**; the **print list** (parts with label and size, dowels with quantity);
the **assembly steps** by stage, with "Let the glue set before the next stage." between stages;
**separate parts**, when there are several groups; and the **diagnostics**, each naming its
section of `docs/TROUBLESHOOTING.md` in plain text, since a relative link wouldn't resolve from
the output folder.

## `schema_version` history

| Version | Introduced | Change |
|---|---|---|
| 1 | Phase 9 | First version |

An added field keeps the version. A field removed, renamed or given a new meaning increments it
(PLAN.md §8.6).
