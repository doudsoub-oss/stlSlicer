# ADR-0010: Deterministic output

- **Status:** Accepted
- **Date:** 2026-11-17
- **Deciders:** gSbr
- **Related:** PLAN.md §1.3 (N1), §4.4; spike check `determinism.subprocess_bytes`

## Context
Byte-identical output makes regression tests trivial and bug reports reproducible. Sources of non-determinism: randomness, unordered iteration, ties, float formatting, timestamps and paths.

## Decision
Same input, settings and dependency versions give byte-identical output. No randomness (hypothesis derandomized in CI); every collection that affects output is sorted with an explicit key; every tie has a documented tie-break; floats in JSON and Markdown are rounded to 6 decimals; no timestamps, host names, user names or absolute paths in outputs; fixed preview palette and font file. Tested end to end in separate processes.

## Options considered
### Option A — Deterministic by rule
Trivial regression tests. Requires discipline in every change.
### Option B — Best effort
Less discipline, but flaky comparisons and unreproducible bugs.

## Consequences
- Easier: golden-file tests, bisecting, bug reports.
- Harder: every new collection or tie needs an explicit order.
- Revisit when: a dependency becomes non-deterministic (the spike check fails).
