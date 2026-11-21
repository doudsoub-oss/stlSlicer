# Troubleshooting

For users. Every exit code and diagnostic code, with its cause and fix. The codes are defined in
`src/stlsplit/errors.py`; a test (`tests/unit/test_docs_drift.py`) keeps the two in sync. Codes
are never reused or renumbered.

Every error is one line on stderr, starting with `stlsplit: error:`. Run the same command with
`-v` to see the traceback as well.

## Exit codes

### 0 — Success
Diagnostics of severity `info` or `warning` may have been printed.

### 1 — Invalid input
Invalid input file, arguments, configuration or output directory. The message names the problem.
Common cases:

| Message starts with | Cause | Fix |
|---|---|---|
| `missing INPUT file`, `give either an INPUT file or --calibrate`, `--print-config takes no INPUT`, `--dry-run needs an INPUT file` | The arguments don't select exactly one mode | Pick one mode ([CONFIGURATION.md](CONFIGURATION.md#modes)) |
| `missing -o/--output DIR` | A split or a calibration needs an output directory | Add `-o DIR`, or use `--dry-run` |
| `argument --margin: invalid float value` (or another `argument ...`) | A value of the wrong type, a missing value, or an unknown option | See `stlsplit --help` |
| `--margin (printer.margin): must be >= 0, got -1.0` | A value outside its allowed range; the message gives the range | Fix the value on the command line or in the `--config` file |
| `connectors.clearence: unknown key in my.toml` | A typo in the TOML file, or a key from another version | Use a key listed in the message ([CONFIGURATION.md](CONFIGURATION.md)) |
| `my.toml: invalid TOML` | The file isn't valid TOML; the message gives the line and column | Fix the syntax, or regenerate the file with `stlsplit --print-config` |
| `--config my.toml: can't read it` | The file doesn't exist or isn't readable | Check the path |
| `--config my.toml: not valid UTF-8 text` | The file was saved in another encoding | Save it as UTF-8 (or UTF-16 with a byte order mark) |
| `advanced.label_font: no such font file` | The font is neither a font bundled with matplotlib nor an existing absolute path | Use the default `DejaVuSans-Bold.ttf` or an absolute path |
| `advanced.label_font: can't read FILE as a font` | The file exists but isn't a font | Use the default `DejaVuSans-Bold.ttf` or a real TrueType font |
| `advanced.label_font: FONT has no glyph for these characters`, or `draws several of these characters with the same glyph` | A symbol or placeholder font: its labels would be unreadable | Use a text font with digits, `-`, `.` and a to z |
| `INPUT model.stl: no such file` | The input path is wrong | Check the path |
| `can't write FILE`, or `can't replace the outputs in DIR ...; the previous outputs were kept` | A full disk, missing permissions, or (on Windows) an output file open in another program, such as a slicer | Free some space or close the program, then run again. Your previous outputs are unchanged |
| `DIR/.stlsplit-staging/old holds outputs of an earlier run that didn't finish` | A run was killed during the final swap, or couldn't undo it | Move what you need out of that folder, delete `.stlsplit-staging`, then run again |
| `INPUT model.stl: no triangles found` | The file is empty, isn't an STL, or is an STL without facets | Export the model again as STL |
| `--simplify (model.simplify): a tolerance of 1000 mm removed the whole model` | The `--simplify` tolerance is as large as the model | Use a much smaller tolerance (a few hundredths of a mm is typical), or none |
| `INPUT model.stl: can't read it as an STL file` | The file is damaged, e.g. a binary STL cut short during a download or copy | Export or download it again |
| `output directory out is not empty` | stlsplit refuses to mix its outputs with existing files | Use an empty directory, or add `--force`: it replaces only stlsplit's own outputs and keeps everything else |
| `--force would delete FILE, which this run reads` | The input, the `--config` file or the label font lies inside one of stlsplit's own outputs (`parts/`, `dowels/`, `calibration/`, …), which `--force` deletes | Move the file out of it, or choose another `-o DIR` |
| `output directory out exists and is not a directory` | `-o` points to a file | Choose another path |
| `the model needs N cells (… ) on this bed, over the limit of 1000` | The model would be cut into more than 1000 cells, usually because of a wrong unit | Check the size in the `model:` line and fix `--scale`, or use a larger `--bed` |
| `--scale (model.scale): … puts the model's coordinates at … mm, over the limit of 5e+09 mm` | The scale is far too large for the model | Use a smaller `--scale` |
| `piece … is … mm^3, too small to record or print` | A piece is under 5e-7 mm³, usually because of a wrong unit | Check the size in the `model:` line and fix `--scale` |
| `out of memory on this model` | The model doesn't fit in this machine's memory. Dense meshes and very large cut faces (a bed of several metres) use the most | Close other programs, use `--simplify` with a small tolerance for a dense mesh, or a smaller `--bed` for very large faces. The system or a library can also end the process without this message |
| `can't write to standard output` | The program reading the plan stopped early, for example a `--dry-run` piped into `head` | Nothing is wrong with the model. Send the plan to a file to read all of it |

### 2 — Mesh can't be repaired
The mesh isn't a closed solid, and the repairs stlsplit is allowed to make didn't fix it.
Example:

```
stlsplit: error: the mesh isn't a closed solid after basic repair: 37 open edges,
0 non-manifold edges, 1 body. Try --deep-repair (needs pip install "stlsplit[deep-repair]"),
or repair the model in MeshLab or with your slicer's "fix model", then run stlsplit again
```

- **Open edges** are the rims of holes. Basic repair only closes holes of one triangle or one
  quad; a missing cap or a cut-open model needs more.
- **Non-manifold edges** are shared by three or more triangles: stray faces, internal walls,
  fins left by a bad export.
- **Bodies** is the number of separate connected parts.

Fixes, in order:

1. Add `--deep-repair` (install the extra first: `pip install "stlsplit[deep-repair]"`; it
   uses pymeshlab, GPL-3.0). It removes non-manifold edges and vertices and closes holes. If
   the message says `pymeshlab didn't load the filters …`, pymeshlab is installed but its
   plugins need the system's OpenGL library: on Debian or Ubuntu,
   `sudo apt install libopengl0`.
2. Repair the model in MeshLab, or with your slicer's "fix model" or "repair" function, export
   it as STL again, and rerun stlsplit.

`the mesh encloses no volume` means the file is a closed but flat surface (a single sheet,
faces facing both ways): there is no solid to split. Give the surface a thickness first.

stlsplit never modifies a valid model: repair runs only when the mesh is not already a closed
solid ([ALGORITHMS.md](ALGORITHMS.md#repair-and-shell-normalization)).

### 3 — Partial success
At least one diagnostic of severity `partial` (for example W001). The files are written; read
the diagnostics before printing.

### 4 — Internal error
A bug. Please report it with the full output of the same command run with `-v`.

### 130 — Interrupted
You stopped the run with Ctrl-C, and your previous outputs are kept. Ctrl-C has no effect during
the final swap, which takes a moment: the run then finishes normally with the new outputs.

## Diagnostic codes

Diagnostics report something worth knowing without stopping the run. They are printed on stderr
as `CODE message [IDs]`; `info` ones are hidden by `-q`. Any `partial` diagnostic makes the run
exit with 3.

| Code | Severity | Meaning |
|---|---|---|
| W001 | partial | A cut face got no connector |
| W002 | warning | A pin was shortened to a standard length below `--dowel-length` |
| W003 | warning | A label was skipped: no room for the minimum text height |
| W004 | warning | A small piece was left on its own |
| W005 | info | A small piece was merged into a neighbour |
| W006 | warning | Suspicious scale: model smaller than 1 mm or larger than 5 m |
| W007 | info | The mesh was repaired |
| W008 | info | A piece has no cut face (a separate body): no connector, no label |
| W009 | info | A face has a single connector: the pieces can rotate around it until glued |
| W010 | info | Overlapping shells were merged |
| W011 | warning | An inside-out body was flipped |
| W012 | info | The model already fits: nothing to cut |
| W013 | partial | No clear straight path could be shown for an assembly step |

### W001 — Cut face without connector (partial)
A cut face got no dowel hole (or peg), so the two pieces meet there without anything to align
them; the run exits 3. The message gives the face and the reason:
- `no room`: once inset by `min_wall + d/2 + clearance + hole_chamfer` (5.1 mm by default)
  nothing of the face is left. Typical for thin walls: a hollow model's 2 mm shell, a plate
  thinner than about 10 mm cut across.
- `all N candidate points failed the 3D checks` (or `the first 256 of N`): there is room on
  the face, but every position tried is too shallow behind the face (shorter than the
  shortest pin's hole plus `min_wall` on a side), has a wall too close to the hole further in,
  or comes closer than `min_wall` to a hole of another face of the same piece.

Fix: glue the face without a pin, or give the connectors more room: a smaller
`--dowel-diameter` (also shortens the shortest pin, 3 × d), a smaller `--min-wall`, or a
different `--bed` / `--margin` so the planes fall elsewhere. Plane nudging already moves each
plane up to `nudge_window` (5 mm) to a position whose faces have room; a larger
`advanced.nudge_window` lets it look further. Nudging sees only the face, not the material
behind it, so a plane moved just off a thin neck can still give this warning.
[Details](ALGORITHMS.md#connector-placement), [nudging](ALGORITHMS.md#plane-nudging).

### W002 — Pin shortened (warning)
Some pins of a face are shorter than `--dowel-length`, because a piece is too shallow behind
the face for a full pin's hole: the message lists the connectors and their lengths. Each hole
is `L/2 + axial_play` deep and needs `min_wall` beyond its bottom, so 12 mm of material behind
a face takes an 18 mm pin, not a 20 mm one. Only the standard lengths are used (20, 18 and
16 mm by default: steps of `pin_length_step` down to 3 × d), so the pins come in few sizes.
Nothing to do: print the pins the output lists. In peg mode, the peg itself is shorter.

### W003 — Label skipped (warning)
None of the piece's cut faces has room for its ID at the minimum text height (4 mm by default).
The piece is still valid and connects as usual: only its engraved ID is missing, so note which
piece it is from the message. A label needs, on one face:
- room for the text, at least `min_wall` from the face's edge and clear of the connectors (a
  `1-0-2b` label at 4 mm is about 18 × 4 mm);
- `labels.depth + min_wall` of material behind it (2.6 mm by default), so thin plates, surfaces
  sloping close to the face and voids just behind it don't count.

To get a label, lower `advanced.label_min_height` or `--min-wall`, or use fewer connectors with
`--max-connectors-per-face`.

### W004 — Small piece left on its own (warning)
A piece smaller than `small_piece_volume` (500 mm³ by default) couldn't be merged into a
neighbour, so it is printed on its own. The message gives the reason:
- `it touches 2 pieces`: it sits between several pieces, and merging it into one of them
  would make the assembly ambiguous;
- `merged with X0-Y0-Z0 it would be 105 mm along X, over U = 102 mm`: the merged piece
  wouldn't fit the usable volume;
- `X1-Y0-Z0-a of its cell lies in its footprint along X`: another piece is in the way of the
  straight move that would bring the merged piece into place;
- `it already absorbed …`: it took in a small piece itself and now spans two cells;
- `it couldn't be cut cleanly from the model`: something else would have been cut with it.

Fix: usually nothing. The piece prints on its own; glue it in place when assembling (it has
connectors only if its face has room for one). Plane nudging moves planes off thin features
(cut regions under 4 · π · (d/2)²) within `advanced.nudge_window`, which avoids some slivers.
[Details](ALGORITHMS.md#small-piece-merge).

### W005 — Small piece merged (info)
A piece smaller than `small_piece_volume` crossed a cut plane by a little, and was merged into
the piece it touches, which keeps its ID and lists the small piece in `merged_from`. That
piece now sticks out of its cell slightly but still fits the usable volume. Nothing to do.
`small_piece_volume = 0` in `[advanced]` turns merging off.

### W006 — Suspicious scale (warning)
The model's largest dimension is under 1 mm or over 5000 mm after `--scale`. STL files have no
units and stlsplit reads them as millimetres, so the model was probably exported in another
unit: metres (too small) or micrometres (too big). Check the size printed in the `model:` line.
Fix: `--scale 1000` for metres, `--scale 25.4` for inches, `--scale 0.001` for micrometres.

### W007 — Mesh repaired (info)
The mesh wasn't a closed solid as loaded, and basic repair (or `--deep-repair`) fixed it. The
message lists each step that changed something, e.g. `triangles added to close holes: 2`.
Nothing to do, but check the parts in your slicer: a hole closed by repair is flat.

### W008 — Piece without cut face (info)
A piece touches no other piece across a cut plane: it is a separate body of the model (for
example a loose part, or a small piece that absorbed the rest of a tiny body). It gets no
connector and no label. Nothing to do; place it by hand when assembling. Not reported when
the model fits in one cell (W012).

### W009 — Single connector on a face (info)
A face has room for only one connector (no two positions 15 mm apart, i.e. 3 × d, or only one
passed the checks). A single round pin aligns the two pieces but lets them turn around it, so
hold them in the right position until the glue sets. stlsplit always places two connectors
when two fit.

### W010 — Overlapping shells merged (info)
The file holds several closed shells that overlap, as models assembled from separate meshes
often do. They were unioned into one solid, so the overlap is no longer counted twice; the
message gives the volume before and after. Nothing to do.

### W011 — Inside-out body flipped (warning)
Some closed shells had their faces pointing the wrong way for where they are, and stlsplit
turned them the right way out; the message gives how many. Typical causes: a whole model
exported inside out (its outer shell faces inwards and its hollows face outwards), or a body
next to the model exported with reversed faces. A shell is read as a hollow (a void) when it
lies entirely inside another shell and faces the other way. Check that the model looks as
expected, especially its hollows.

### W012 — Model already fits (info)
The model fits the usable volume U in one piece (after auto-orient, if it is on), so there is
nothing to cut. The message gives U. stlsplit continues with that single piece, without
connectors or labels, and exits 0. If you expected a split, check `--bed`, `--margin` and
`--scale`: a model exported in centimetres or inches looks 10 or 25.4 times too small (see also
W006).

### W013 — Assembly step without a proven clear path (partial)
Two bodies on the same side of a cut plane may be in each other's way, so stlsplit couldn't show
that one step of `assembly.md` is a clear straight move. The message gives the step and the
pieces. The check is cautious, so the move may well work: **try it dry before gluing**. If it
is really blocked, change the cut with `--bed`, `--margin` or `--no-auto-orient`, or adjust the
model so those bodies don't interlock along that axis. The pieces themselves are valid. The
run exits 3.

## Common problems

**The model comes out far too big or too small.** STL has no units and stlsplit reads it as
millimetres. Check the size in the `model:` line, then use `--scale 25.4` for inches or
`--scale 1000` for metres. `--dry-run` shows the grid without writing anything.

**A run takes a long time.** With many pieces, time grows with the number of cut faces: about
0.4 s per large face on a laptop, so a 2 m cube cut into 900 pieces (2420 faces) takes 15 minutes.
Add `-v` to see the time of each stage. A larger `--bed`, or fewer pieces, helps most. For a very
dense mesh, `--simplify` with a small tolerance shortens the stages that depend on triangles.

**Every face reports W001 on a hollow or thin model.** A face needs about 10 mm of width for a
5 mm pin. Thin shells can't hold one, so the pieces are written without connectors and the run
exits 3: glue them, or use a smaller `--dowel-diameter` and `--min-wall`.

**Small blocks report W001 where three cuts meet.** A block about 15 mm wide has no room for
holes from three perpendicular faces. The other faces keep their connectors; glue this one.

**A pipe cuts the output short.** `stlsplit … --dry-run | head` exits 1, because the plan couldn't
be written in full. Logs piped away (`2>&1 | head`) don't affect a split, which still writes its
files and keeps its exit code.
