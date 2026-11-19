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
| `INPUT model.stl: no such file` | The input path is wrong | Check the path |
| `INPUT model.stl: no triangles found` | The file is empty, isn't an STL, or is an STL without facets | Export the model again as STL |
| `--simplify (model.simplify): a tolerance of 1000 mm removed the whole model` | The `--simplify` tolerance is as large as the model | Use a much smaller tolerance (a few hundredths of a mm is typical), or none |
| `INPUT model.stl: can't read it as an STL file` | The file is damaged, e.g. a binary STL cut short during a download or copy | Export or download it again |
| `output directory out is not empty` | stlsplit refuses to mix its outputs with existing files | Use an empty directory, or add `--force`: it replaces only stlsplit's own outputs and keeps everything else |
| `output directory out exists and is not a directory` | `-o` points to a file | Choose another path |

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

### W001 — Cut face without connector (partial)
TODO (Phase 5)

### W002 — Pin shortened (warning)
TODO (Phase 5)

### W003 — Label skipped (warning)
TODO (Phase 8)

### W004 — Small piece left on its own (warning)
TODO (Phase 4)

### W005 — Small piece merged (info)
TODO (Phase 4)

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
TODO (Phase 4)

### W009 — Single connector on a face (info)
TODO (Phase 5)

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

## Common problems

TODO (Phase 11)
