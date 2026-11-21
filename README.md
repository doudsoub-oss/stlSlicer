# stlsplit

Split an STL model that is too big for your printer into pieces that each fit the build volume,
with dowel holes on every cut face, an ID engraved on each piece, the dowel pins to print, and an
assembly map telling you which piece goes where.

> **Status:** under development (Phase 5 of PLAN.md). The command line, the configuration, the
> output-directory policy, loading and repairing the input STL, auto-orientation, the grid, the
> cutting into pieces and cut faces, and the placement of the connectors work, and `--dry-run`
> prints the grid, the pieces, the faces, the connectors and the pins to print. The holes and
> output files don't exist yet, so the split and dry run stop with a warning after the
> connector placement, and the calibration after its checks. Sections marked TODO are filled
> in as the features land.

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

TODO (Phase 9): from a model to printed, assembled pieces.

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

TODO (Phase 9): `parts/`, `dowels/`, `assembly.json`, `assembly.md`, `preview_exploded.glb`
(docs/OUTPUT_FORMAT.md).

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

TODO (Phase 9): following `assembly.md`, gluing.

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
