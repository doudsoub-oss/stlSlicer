# Contributing to stlsplit

For maintainers. If you are new to the project, start with
[docs/ONBOARDING.md](docs/ONBOARDING.md).

## Development setup

Python ≥ 3.12 is required (numpy 2.5, scipy 1.18 and networkx 3.7 need it).

```bash
git clone git@github.com:doudsoub-oss/stlSlicer.git
cd stlSlicer
python3.13 -m venv .venv          # or: uv venv --python 3.13 .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -e ".[dev]"           # or: uv pip install -e ".[dev]"
python scripts/check.py
```

No Python 3.12+ on your system? [uv](https://docs.astral.sh/uv/) installs one without
touching system packages: `uv python install 3.13`.

The `--deep-repair` tests and the pymeshlab spike check are skipped unless the optional extra
is installed: `pip install -e ".[dev,deep-repair]"` (pymeshlab is GPL-3.0; it is never
imported without `--deep-repair`). On Linux its filter plugins also need the system's
`libOpenGL.so.0` (Debian and Ubuntu: `sudo apt install libopengl0`); without it the spike's
`pymeshlab.repair_filters` check fails. CI installs both in the Linux 3.13 job.

## Commands

```bash
python scripts/check.py                     # ruff, ruff format --check, mypy, all tests except slow
python scripts/check.py --fast              # same, without the e2e tests
pytest -q tests/unit/test_nudge.py -k slack # one test
pytest -m slow                              # performance tests (manual, weekly CI)
ruff format .                               # format the code (Markdown is excluded on purpose)
python scripts/api_spike.py                 # after any dependency upgrade
```

## Code style

- ruff for linting and formatting (configuration in `pyproject.toml`), mypy in strict mode on
  `src/`.
- Every module starts with a docstring: its place in the pipeline, its main inputs and outputs,
  and the invariants it guarantees.
- Every public function has a Google-style docstring with the unit and frame of every geometric
  argument, the ordering of returned collections, the exceptions raised, and references (PLAN.md
  § or ADR) for non-obvious choices. Example in PLAN.md §8.4.
- Comments explain why, not what. Cite ADRs (`# see ADR-0004`) instead of re-arguing them.
- No magic numbers: constants live in `config.py` with a comment pointing to PLAN.md §6.
- Only `io.py` and `cli.py` touch the file system; a module imports only the modules above it in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ("Module map").
- Determinism rules (ADR-0010): no randomness, sort with explicit keys, documented tie-breaks.
- Test names describe behaviour: `test_hollow_sphere_keeps_its_void`, not `test_repair_3`.

## Commit convention

- One branch per phase or change, e.g. `phase-03-grid`, merged into `main` when done.
- Message: `[TAG] summary` (during the plan: `[TAG] Phase N: summary`). Tags:
  - `[INIT]` creating the repository (first commit only);
  - `[FEAT]` a new feature or a phase deliverable;
  - `[ADD]` an addition to existing code (an option, a test, a docs section);
  - `[FIX]` a bug fix;
  - `[DEL]` removing a feature, a function or dead code.
- One logical change per commit, with its code, tests and docs together.

## Definition of done for any change

- [ ] The code is written, typed and documented (see "Code style").
- [ ] Tests cover the change; they were written first where practical, and none was weakened,
      skipped or deleted to make it pass.
- [ ] Every affected document is updated (the map in PLAN.md §8.2); the drift tests pass.
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]` for any user-visible change.
- [ ] An ADR is added or superseded if a decision changed.
- [ ] `python scripts/check.py` is green; paste its output in the pull request.
- [ ] The commit message follows the convention above.

## Recipes

### Add a CLI or TOML option
1. Add the field, with its default and a docstring line, to the table's dataclass in
   `src/stlsplit/config.py`. The field name is the TOML key.
2. Add its rules to `config.validate()`, with a message giving the allowed range.
3. If it has a CLI flag, add it in `cli.build_parser()` with `_option(..., key="table.key")`.
   Don't set a default: every option defaults to `SUPPRESS` (ADR-0011).
4. If it feeds a formula, compute the derived value in `config.derived()`, nowhere else.
5. Tests in `tests/unit/test_config.py`: the default in `PLAN_DEFAULTS`, a non-default value in
   `NON_DEFAULT`, one bad value per rule and one boundary value. For a CLI flag, a precedence
   case in `tests/unit/test_cli.py` if it has a new kind of value.
6. Docs: a row in `docs/CONFIGURATION.md` (the default as a TOML value in backticks; the drift
   test checks it), PLAN.md §6 or §7, and a CHANGELOG entry.

### Add a diagnostic code
1. Append a `DiagnosticCode` with the next free number to `DIAGNOSTIC_CODES` in
   `src/stlsplit/errors.py`. Never reuse or renumber a code; to stop using one, set
   `retired=True` and keep it.
2. Emit it from the stage with `errors.diagnostic(code, message, refs)` and return it with the
   stage's result.
3. Docs: a row in the table and a `### Wnnn — Title (severity)` section in
   `docs/TROUBLESHOOTING.md` (the drift tests check both), PLAN.md §4.5, and a CHANGELOG entry.
4. Test the condition that emits it.

### Add a connector type
1. Add its name to `config.ConnectorType` and `models.ConnectorKind`. If it sticks out of its
   piece, reduce U for it in `config.derived` so a full cell plus the feature still fits
   `printable` (I2, ADR-0005).
2. `connectors._sides`: which sides of a face need a hole. The 3D checks then cover them.
3. `tools.apply`: build its solid in plane-local coordinates, reaching `TOOL_OVERLAP` past the
   face (a tool ending exactly on a cut face can miss it, docs/LIBRARY_NOTES.md), and give
   `check_piece` the volume it should add or remove.
4. Tests in `tests/integration/test_tools.py`: volumes, one shell per body, fit, and no overlap
   between assembled pieces.
5. Docs: `docs/CONFIGURATION.md` (`--connector`), `docs/ALGORITHMS.md`, PLAN.md §6, an ADR, and a
   CHANGELOG entry.

### Add a test fixture
TODO (Phase 2)

### Change an output file or the `assembly.json` schema
TODO (Phase 9)

### Upgrade a dependency
1. Upgrade in a fresh virtual environment: `pip install --upgrade <package>`.
2. Run `python scripts/api_spike.py`. Every check must pass.
3. If a check fails, read its row in [docs/LIBRARY_NOTES.md](docs/LIBRARY_NOTES.md) to find the
   code that depends on it; fix that code, update the spike and the notes, or keep the old
   version.
4. Update the version in the notes and, if it is a new minimum, in `pyproject.toml`.
5. Run `python scripts/check.py`.

### Record or change a decision (ADR)
1. Copy [docs/adr/0000-template.md](docs/adr/0000-template.md) to the next free number.
2. Fill it in; status `Accepted` once agreed.
3. To change a decision, write a new ADR and set the old one's status to
   "Superseded by ADR-XXXX". Never edit or renumber an accepted ADR's decision.
4. Add it to [docs/adr/README.md](docs/adr/README.md).

### Release a version
TODO (Phase 11)
