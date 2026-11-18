# Algorithms

For maintainers. One section per algorithm: inputs, outputs, formulas (with the default numbers
filled in), rationale, edge cases, and links to its tests. Numbers are defined in PLAN.md §6 and
`config.py`; this file links to them.

## Radius-compensated cylinders

Holes are modelled with `n_seg` segments and a vertex radius `r_model = r_h / cos(π / n_seg)`, so
the polygon flats sit at r_h (PLAN.md §6.2). With the defaults (r_h = 2.7, n_seg = 64):
r_model = 2.7033. Without compensation and with manifold3d's default 16 segments, the flats would
sit 0.05 mm inside: a quarter of a 0.2 mm clearance.

- Code: `geometry.cylinder_solid(..., compensate=True)`.
- Tests: `tests/unit/test_geometry.py::test_compensated_cylinder_flats_sit_at_requested_radius`.

## Repair and shell normalization
TODO (Phase 2)

## Auto-orientation
TODO (Phase 3)

## Even grid
TODO (Phase 3)

## Cut regions
TODO (Phase 4)

## Splitting, piece IDs and small-piece merge
TODO (Phase 4)

## Connector placement
TODO (Phase 5)

## Plane nudging
TODO (Phase 6)

## Tool solids, pins and the calibration kit
TODO (Phase 7)

## Label layout
TODO (Phase 8)

## Assembly order
TODO (Phase 9)
