# Troubleshooting

For users. Every exit code and diagnostic code, with its cause and fix. The codes are defined in
`src/stlsplit/errors.py`; a test keeps the two in sync (from Phase 1). Codes are never reused or
renumbered.

## Exit codes

### 0 — Success
Diagnostics of severity `info` or `warning` may have been printed.

### 1 — Invalid input
Invalid input file, arguments, configuration or output directory. The message names the problem.
TODO (Phase 1): common cases and fixes.

### 2 — Mesh can't be repaired
TODO (Phase 2): cause and fix (`--deep-repair`, repairing in a mesh editor).

### 3 — Partial success
At least one diagnostic of severity `partial` (for example W001). The files are written; read
the diagnostics before printing.

### 4 — Internal error
A bug. Please report it with the full output of the same command run with `-v`.

## Diagnostic codes

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
TODO (Phase 2)

### W007 — Mesh repaired (info)
TODO (Phase 2)

### W008 — Piece without cut face (info)
TODO (Phase 4)

### W009 — Single connector on a face (info)
TODO (Phase 5)

### W010 — Overlapping shells merged (info)
TODO (Phase 2)

### W011 — Inside-out body flipped (warning)
TODO (Phase 2)

### W012 — Model already fits (info)
TODO (Phase 3)

## Common problems

TODO (Phase 11)
