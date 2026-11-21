# stlsplit

Split an STL model that is too big for your printer into pieces that each fit the build volume,
with dowel holes on every cut face, an ID engraved on each piece, the dowel pins to print, and an
assembly map telling you which piece goes where.

> **Status:** under development (Phase 9 of PLAN.md). A split writes every output: the pieces,
> the dowels, the assembly map and a 3D preview. Robustness, performance and the final
> documentation come in Phases 10 and 11. Sections marked TODO are filled in as they land.

```bash
stlsplit model.stl -o ./out --bed 220 220 250
```

## Install

Requires Python 3.12 or newer.

```bash
git clone git@github.com:doudsoub-oss/stlSlicer.git
cd stlSlicer
pip install -e .
stlsplit --version
```

Optional, GPL-licensed repair fallback for badly broken meshes: `pip install -e ".[deep-repair]"`.

## Quick start (5 minutes)

```bash
stlsplit --calibrate -o ./calibration                # once per printer: pick your clearance
stlsplit model.stl -o ./out --bed 220 220 250 --clearance 0.2
```

1. Open `out/preview_exploded.glb` in any glTF viewer to check the cuts.
2. Print every file of `out/parts/`, and the dowels of `out/dowels/` in the quantities the log
   and `out/assembly.md` give.
3. Follow the steps in `out/assembly.md`.

## Usage

```bash
stlsplit model.stl -o ./out --bed 220 220 250        # split for a 220 × 220 × 250 mm bed
stlsplit model.stl -o ./out --config my_printer.toml --connector peg --clearance 0.25
stlsplit model.stl --dry-run                         # print the plan, write nothing
stlsplit --calibrate -o ./calibration                # print once, then pick your clearance
stlsplit --print-config --config my_printer.toml     # show the effective settings
stlsplit --help                                      # every option, with its default
```

Settings come from three places, each overriding the one before: the built-in defaults, a TOML
file given with `--config`, then the options you type. A configuration file for a smaller
printer:

```toml
[printer]
bed = [180, 180, 180]
margin = 4                 # mm kept free on each side

[connectors]
diameter = 6.0
length = 24.0              # exact length of a full pin
clearance = 0.25           # measured with --calibrate
```

`stlsplit --print-config > my_printer.toml` writes every setting with its current value, a good
starting point for your own file. The output directory must be empty unless you pass `--force`,
which replaces only stlsplit's own outputs and keeps your other files.

Every option, its default and its allowed values: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).
Exit codes and error messages: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Calibration: choosing your clearance

How tightly a pin fits a hole depends on your printer and filament. Print the test kit once, with
the pin size you will use, to find the right `--clearance`:

```bash
stlsplit --calibrate -o ./calibration-kit --dowel-diameter 5 --dowel-length 20
```

| File in `calibration/` | Print | What it is |
|---|---|---|
| `block.stl` | 2, lying on the large face, holes vertical | A bar with one hole per clearance |
| `pin_d5.0_l20.0.stl` | one per hole (5 by default), flat side down | The test pin |
| `README.md` | — | These instructions, with the table of codes |

1. Push a pin into each hole by hand. The right fit goes in with firm thumb pressure and doesn't
   wobble.
2. To test a full joint, turn the second bar half a turn about its long axis and lay it on the
   first: matching holes face each other.
3. Read the code engraved under the hole you chose. It is the clearance in hundredths of a
   millimetre: `20` means 0.20 mm.
4. Use it: `stlsplit model.stl -o out --clearance 0.2`.

These holes print vertically. Horizontal holes print tighter, so if most holes in your real pieces
will be horizontal, pick one step looser.

## The output folder

```text
out/
├── parts/X0-Y0-Z0.stl ...      # one file per piece, print one of each
├── dowels/dowel_d5.0_l20.0.stl # one file per pin length, print the quantity listed
├── assembly.md                 # print list and assembly steps, for you
├── assembly.json               # the same and more, for other tools
└── preview_exploded.glb        # the pieces moved apart, one colour each
```

Pieces keep their position in the model, so a slicer may place them away from the bed's centre
until you arrange them. Each one fits the bed as loaded. `--no-preview` skips the GLB. Every field
is described in [docs/OUTPUT_FORMAT.md](docs/OUTPUT_FORMAT.md).

## Piece labels

Each piece's ID is engraved on one of its cut faces, so it is hidden once the model is assembled.
The label is the short form of the piece ID: its grid position along X, Y and Z, plus a letter
when a cell holds several bodies. `X1-Y0-Z2-b` is engraved as `1-0-2b`.

Labels read correctly when you look straight at the face, are 4 to 12 mm high depending on the
room, and are 0.6 mm deep (`--label-depth`). A piece with no room for one gets warning W003 and
no label. `--no-label` turns them off.

## Printing the dowels

`dowels/` holds one STL per pin length, and the log says how many copies of each to print:

```text
pins: print 6 x dowels/dowel_d5.0_l20.0.stl
pins: print 2 x dowels/dowel_d5.0_l18.0.stl
```

The files are already oriented: keep the **flat side down**, with the pin lying on the bed. Printed
this way the layers run along the pin, which makes it strong, and the flat lets air and glue escape
from the blind holes. Pins are symmetric, so either end can go in first.

## Assembling

`assembly.md` lists the joins in three stages: X joins build rows, Y joins build layers, and Z
joins stack the layers. Doing them in this order means every join is one straight move along
its pins.

```text
### Stage 1: X joins (rows)

- **1.1** Slide `X1-Y0-Z0` along -x onto `X0-Y0-Z0`. Dowels: 2 x 20 mm.
- **1.2** Slide `X1-Y1-Z0` along -x onto `X0-Y1-Z0`. Dowels: 2 x 20 mm.

Let the glue set before the next stage.
```

1. Dry-fit each join first. Directions are the axes of the part files, and the engraved labels
   tell you which piece is which.
2. Put glue in the holes and on the faces, insert the dowels listed for that step, and slide
   the pieces together.
3. Let the glue set before starting the next stage: the next joins move whole sub-assemblies.

A join marked **glue only** has no connector, so hold it in place while it sets. A move marked
**W013** couldn't be shown to have a clear path: try it dry before gluing
([TROUBLESHOOTING](docs/TROUBLESHOOTING.md)). Groups listed under **Separate parts** never touch
each other in the model.

## Known limits

TODO (Phase 11). By design: axis-aligned cuts only, no hollowing, no dovetails or snap-fits
(PLAN.md §1.5).

## Performance

TODO (Phase 10): measured times.

## Real test print

TODO (Phase 11).

## Licence

MIT, see [LICENSE](LICENSE). The optional `deep-repair` extra installs pymeshlab, which is
GPL-3.0.
