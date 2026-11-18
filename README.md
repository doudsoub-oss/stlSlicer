# stlsplit

Split an STL model that is too big for your printer into pieces that each fit the build volume,
with dowel holes on every cut face, an ID engraved on each piece, the dowel pins to print, and an
assembly map telling you which piece goes where.

> **Status:** under development (Phase 1 of PLAN.md). The command line, the configuration and
> the output-directory policy work; the split itself doesn't exist yet, so every mode stops with
> a warning after its checks. Sections marked TODO are filled in as the features land.

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

TODO (Phase 7): `stlsplit --calibrate`, print the kit, pick the clearance that fits.

## The output folder

TODO (Phase 9): `parts/`, `dowels/`, `assembly.json`, `assembly.md`, `preview_exploded.glb`
(docs/OUTPUT_FORMAT.md).

## Printing the dowels

TODO (Phase 7): orientation (on the flat), quantity per file.

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
