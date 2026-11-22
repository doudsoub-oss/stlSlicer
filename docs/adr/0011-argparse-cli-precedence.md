# ADR-0011: argparse CLI; defaults < TOML < explicit CLI; a `--calibrate` mode; exit codes 0–4

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §4.5, §7

## Context
The tool needs a CLI and a config file with an unambiguous merge. With ordinary argparse defaults you can't tell "the user typed 220" from "default 220", so TOML values would always lose.

## Decision
The CLI uses stdlib `argparse` with `default=argparse.SUPPRESS` on every option, so only typed options override the TOML file, which overrides built-in defaults. Unknown TOML keys are errors. Modes: split, dry run, `--calibrate`, `--print-config`. Exit codes 0–4 as in PLAN.md §4.5.

## Options considered
### Option A — argparse + SUPPRESS
No dependency, unambiguous merge.
### Option B — click / typer
Nicer API, but a dependency and the same precedence problem to solve.
### Option C — Config file only
Simple, but unfriendly for one-off runs.

## Consequences
- Easier: precedence is testable and documented.
- Harder: option values must be read from the merged config, never from argparse defaults.
- As built (Phase 10, PLAN.md Appendix E, r14): exit code 130 was added for Ctrl-C, alongside codes 0–4.
- Revisit when: a GUI or library API is added (v2).
