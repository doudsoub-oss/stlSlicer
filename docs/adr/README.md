# Architecture Decision Records

One file per decision, never renumbered. To add or change one, see CONTRIBUTING.md, "Record or
change a decision (ADR)". Template: [0000-template.md](0000-template.md).

| ADR | Title | Status |
|---|---|---|
| [0001](0001-manifold3d-for-solid-geometry.md) | manifold3d for all solid geometry | Accepted |
| [0002](0002-cut-regions-from-two-slices.md) | Cut regions are the intersection of two slices at offset ± ε | Accepted |
| [0003](0003-even-grid-plus-bounded-nudge.md) | Even grid plus a bounded nudge with a lexicographic score | Accepted |
| [0004](0004-staged-assembly-order.md) | Assembly in stages: X rows, then Y layers, then the Z stack | Accepted |
| [0005](0005-dowels-by-default-pegs-optional.md) | Dowels by default; pegs optional, with U reduced by the protrusion | Accepted |
| [0006](0006-standard-symmetric-pins.md) | Standard pin lengths, symmetric pins, explicit axial play | Accepted |
| [0007](0007-try-first-repair.md) | Try the mesh as-is first; sign-aware shell normalization; never `fix_normals(multibody=True)` | Accepted |
| [0008](0008-proper-rotations-only.md) | Auto-orient uses proper rotations only (det = +1) | Accepted |
| [0009](0009-labels-on-cut-faces.md) | Labels engraved on cut faces, bundled DejaVu Sans Bold, EvenOdd fill | Accepted |
| [0010](0010-deterministic-output.md) | Deterministic output | Accepted |
| [0011](0011-argparse-cli-precedence.md) | argparse CLI; defaults < TOML < explicit CLI; a `--calibrate` mode; exit codes 0–4 | Accepted |
| [0012](0012-small-piece-merge-footprint-guard.md) | Small pieces are merged only under the footprint guard | Accepted |
| [0013](0013-axis-aligned-grid.md) | The grid model is axis-aligned by design | Accepted |
| [0014](0014-holes-verified-in-3d.md) | Every hole is verified in 3D: rays, exact containment and min_gap | Accepted |
