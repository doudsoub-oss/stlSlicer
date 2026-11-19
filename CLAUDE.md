# stlsplit — notes for Claude Code

CLI that splits an oversized STL into printable, connectable parts. Python ≥ 3.12, src layout.

## Commands
- Dev install: `pip install -e ".[dev]"`
- All checks (run before every commit): `python scripts/check.py`
- Without e2e tests: `python scripts/check.py --fast`
- One test: `pytest -q tests/unit/test_nudge.py -k slack`
- After a dependency upgrade: `python scripts/api_spike.py`

## Where to look
- Plan, progress and the phase protocol: PLAN.md (read §0–§9 and the current phase only)
- Module map, frames, invariants: docs/ARCHITECTURE.md
- Why things are the way they are: docs/adr/
- Verified library quirks: docs/LIBRARY_NOTES.md

## Rules
- Solid geometry goes through manifold3d; trimesh only for I/O, repair and the GLB preview.
- Units are mm; pipeline geometry is in the cutting frame.
- Numbers come from config.py / config.derived(); no magic numbers.
- No randomness, timestamps or absolute paths in outputs.
- Code, tests and docs of a change go in the same commit (CONTRIBUTING.md, "Definition of done").
- Commit messages: `[TAG] summary`, TAG one of [INIT] [FEAT] [ADD] [FIX] [DEL].
- IMPORTANT: never weaken, skip or delete a test to make it pass. Ask instead.
- When compacting, keep the list of modified files and the test commands.
