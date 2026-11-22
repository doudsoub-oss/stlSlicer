# Onboarding: start here

For whoever takes the project over.

## 1. What stlsplit does

stlsplit is a command-line tool that cuts an STL too big for a 3D printer into pieces that fit.
Each piece is a closed solid, with dowel holes (or pegs) on its cut faces and its ID engraved on
one of them. It also writes the loose dowels to print and an assembly map in a followable order.
Output is byte-identical for the same input, settings and dependency versions.
For users: the [README](../README.md), [CONFIGURATION](CONFIGURATION.md) and
[TROUBLESHOOTING](TROUBLESHOOTING.md).

## 2. Ten-minute setup

```bash
git clone git@github.com:doudsoub-oss/stlSlicer.git && cd stlSlicer
python3.13 -m venv .venv && source .venv/bin/activate   # Python ≥ 3.12
pip install -e ".[dev]"
python scripts/check.py
```

Then follow the [README quick start](../README.md#quick-start-5-minutes).

## 3. Reading order

1. [ARCHITECTURE.md](ARCHITECTURE.md)
2. [The ADR index](adr/README.md)
3. [ALGORITHMS.md](ALGORITHMS.md) (skim)
4. [CONTRIBUTING.md](../CONTRIBUTING.md)

## 4. Trace one model

Run a real fixture with `-v` (the output folder must not exist yet):

```bash
stlsplit tests/fixtures/real/memnon.stl -o /tmp/memnon --scale 3 -v
```

Each stage logs its time (`debug: stage …`), then its result. The lines below are from that run,
shortened:

| Log line | Stage | Code |
|---|---|---|
| `configuration: built-in defaults <- 1 command-line option` | Merge defaults, TOML and options | `config`, `cli` |
| `model: 11924 triangles, 1 body, 6 voids; … volume 5163435.079 mm^3; repair: none` | Load, then repair. This volume is the reference of I3 | `io.load_stl`, `repair.prepare` |
| `grid: 1 x 1 x 2 = 2 cells; rotation identity` | Orientation and even grid | `grid.orient`, `grid.even_grid` |
| `nudging: 0 of 1 plane moved` | Plane nudging | `grid.nudge` |
| `cutting: 2 pieces, 1 cut face` | Split, IDs, faces, small-piece merge | `cutting.cut` |
| `connectors: 4 on 1 of 1 cut face` | Placement and its 3D checks | `connectors.place` |
| `warning: W002 face …: 4 pins shortened …` | A diagnostic from that stage | `errors`, [TROUBLESHOOTING](TROUBLESHOOTING.md) |
| `labels: 2 of 2 pieces` | Label layout | `labels.layout` |
| `debug: stage assembly order`, `tools`, `export`, `write` | Order, booleans, encoding, publishing | `assembly`, `tools`, `io` |
| `pins: print 3 x dowels/dowel_d5.0_l16.0.stl` | What to print | `tools.pin_groups` |
| `exit code: 0` | 0 despite W002, which is only a warning | `errors.exit_code_for` |

Then open `/tmp/memnon/assembly.md`, and `preview_exploded.glb` in any glTF viewer.

## 5. I want to…

The steps are in the [CONTRIBUTING recipes](../CONTRIBUTING.md#recipes).

| I want to… | Module | Docs | Tests |
|---|---|---|---|
| Add a CLI or TOML option | `config`, `cli` | CONFIGURATION, PLAN.md §6–7 | `tests/unit/test_config.py`, `test_cli.py` |
| Add a diagnostic code | `errors`, the stage that emits it | TROUBLESHOOTING, PLAN.md §4.5 | The stage's tests, `test_docs_drift.py` |
| Add a connector type | `config`, `models`, `connectors`, `tools` | CONFIGURATION, ALGORITHMS, an ADR | `tests/integration/test_tools.py` |
| Add a test fixture | `tests/conftest.py`, `tests/e2e/cases.py` | PLAN.md Appendix D, `tests/fixtures/README.md` for a real model | `tests/e2e/test_properties.py` |
| Change an output or the schema | `assembly`, `io`, `schemas/assembly.schema.json` | OUTPUT_FORMAT | `tests/integration/test_export.py` |
| Change where cuts go | `grid` | ALGORITHMS, ADR-0003 | `tests/unit/test_grid.py`, `test_nudge.py` |
| Fix a mesh that won't load | `io`, `repair`, `geometry` | ALGORITHMS, ADR-0015 | `tests/integration/test_repair.py` |
| Upgrade a dependency | `pyproject.toml` | LIBRARY_NOTES | `scripts/api_spike.py` |
| Record or change a decision | — | `docs/adr/` and its index | `test_docs_drift.py` |
| Release a version | `pyproject.toml` | CHANGELOG | `scripts/check.py` |

## 6. Working with Claude Code on this repository

`CLAUDE.md` holds the short rules Claude Code loads every session. Up to v1.0, work went one phase
per session, following the protocol in PLAN.md §9.1: plan first, tests first, `scripts/check.py`
output as evidence, an independent review subagent, then commit.

After v1.0, keep the same protocol for each change, with one branch per change:

1. Start from a clean session and describe the change. Skip the planning step only if the change
   fits in one sentence.
2. Follow the CONTRIBUTING recipe and its definition of done.
3. Ask for a review of the diff by a subagent, and fix what affects correctness.
4. Commit as `[TAG] summary`. PLAN.md stays as the roadmap (§11) and history (Appendix E).

## 7. Upgrading dependencies

Run `python scripts/api_spike.py` and update [LIBRARY_NOTES.md](LIBRARY_NOTES.md)
(CONTRIBUTING.md, "Upgrade a dependency").

## 8. History

- Decisions: [docs/adr/](adr/README.md).
- Plan changes: PLAN.md Appendix E. Progress: PLAN.md §0.
- Original author, for questions: gSbr.

## 9. Handover checklist

Someone other than the author follows this from a fresh clone, then notes any step that was
unclear or failed, so it can be fixed in this file.

- [ ] Fresh clone of the repository.
- [ ] `pip install -e ".[dev]"` in a new virtual environment.
- [ ] `python scripts/check.py` passes.
- [ ] `python scripts/api_spike.py` passes.
- [ ] The [README quick start](../README.md#quick-start-5-minutes) works.
- [ ] [ARCHITECTURE](ARCHITECTURE.md) and the [ADR index](adr/README.md) have been read.

Done by: _name_, on _date_, at commit _hash_.
