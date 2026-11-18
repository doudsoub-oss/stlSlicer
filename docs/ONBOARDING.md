# Onboarding: start here

For whoever takes the project over.

## 1. What stlsplit does

TODO (Phase 11): five lines. Until then, see the README and PLAN.md §1.

## 2. Ten-minute setup

```bash
git clone git@github.com:doudsoub-oss/stlSlicer.git && cd stlSlicer
python3.13 -m venv .venv && source .venv/bin/activate   # Python ≥ 3.12
pip install -e ".[dev]"
python scripts/check.py
```

Then follow the README quick start. TODO (Phase 9).

## 3. Reading order

1. [ARCHITECTURE.md](ARCHITECTURE.md)
2. [The ADR index](adr/README.md)
3. [ALGORITHMS.md](ALGORITHMS.md) (skim)
4. [CONTRIBUTING.md](../CONTRIBUTING.md)

## 4. Trace one model

TODO (Phase 11): run with `-v` on a real fixture and match each log line to its stage.

## 5. I want to…

TODO (Phase 11): table "I want to… → module, doc and test to change", built from the recipes in
CONTRIBUTING.md.

## 6. Working with Claude Code on this repository

`CLAUDE.md` holds the short rules Claude Code loads every session. Work goes one phase per
session, following the protocol in PLAN.md §9.1: plan first, tests first, `scripts/check.py`
output as evidence, an independent review subagent, then commit.

TODO (Phase 11): post-v1 workflow.

## 7. Upgrading dependencies

Run `python scripts/api_spike.py` and update [LIBRARY_NOTES.md](LIBRARY_NOTES.md)
(CONTRIBUTING.md, "Upgrade a dependency").

## 8. History

- Decisions: [docs/adr/](adr/README.md).
- Plan changes: PLAN.md Appendix E. Progress: PLAN.md §0.
- Original author, for questions: gSbr.
