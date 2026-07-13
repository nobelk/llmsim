# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

llmsim is a parallel discrete-event simulation (DES) library for Python 3.14+.
Implementation is underway — see `specs/roadmap.md` for current phase status.

Document hierarchy (upstream → downstream):

- `docs/part-deux.md` — the full design document everything derives from.
- `specs/mission.md` — vision, audience, in/out of scope, guiding principles.
- `specs/tech-stack.md` — runtime targets, tooling, CI matrix, and the
  **normative technical constraints** (violating one is a bug, not a style issue).
- `specs/roadmap.md` — Phases 0–6 as small, independently shippable steps.
- `docs/simpy-comparison.md` — comparison with SimPy 3.

When these documents conflict, `specs/` wins over `README.md`; changes to design
decisions must be made in `specs/`, not just in code or README.

## Workflow

- Each roadmap step is sized to one feature spec living in `specs/<branch-name>/`
  (`plan.md`, `requirements.md`, `validation.md`), built on a `specs/<name>`
  branch. Steps within a phase are ordered by dependency.
- Every parallel feature ships a same-seed-same-result test in the same PR;
  every step introducing a parallel capability documents its slowdown regimes
  in the same PR.

## Commands (per specs/tech-stack.md)

`uv` is the standard package manager for all dev workflows (`uv run pytest`,
`uv run ruff check`, etc. — see `pyproject.toml`). Non-obvious rules:

- Types: `uv run mypy --strict` **and** `uv run pyright` — both must pass.
- Benchmarks: pytest-benchmark with regression thresholds enforced in CI.
- Build backend is hatchling (PEP 621, pyproject-only, `src/` layout); end
  users install via plain `pip` — don't convert README install examples to uv.

## Coding style

1. **Adhere to PEP 8 guidelines** — the project-wide standard (see
   `specs/tech-stack.md`); ruff enforces it (`E`/`W` pycodestyle + `N`
   pep8-naming), with PEP 257 docstring conventions.
2. **Write descriptive and concise variable names** — no abbreviations that
   need decoding; names should read naturally in DES domain terms
   (`service_time`, `lookahead`, `replication_index`).
3. **Leverage Python's built-in functions and libraries** — the engine is
   stdlib-only by design; reach for `heapq`, `itertools`, `functools`,
   `collections` etc. before writing custom machinery.
4. **Follow the DRY principle (Don't Repeat Yourself)** — factor shared logic
   into one place; the backend abstraction (one code path for threads,
   subinterpreters, and processes) is the model to imitate.

## Architecture (the big picture)

One fully typed, `__slots__`-based sequential core (SimPy-style
generator-as-process model), plus parallelism from **share-nothing
architecture** — never from locks on the sequential engine. Module layout and
per-module roles are in the code and `specs/tech-stack.md`; the design
decision that isn't obvious from reading it: optimistic/Time Warp
synchronization is permanently rejected (generator frames can't be
snapshotted), and executor work is always submitted as (importable callable,
seed spec, config) — never live objects — so all backends share one code path.

## Non-negotiable design rules

The full normative list is in `specs/tech-stack.md`; the ones most likely to
affect day-to-day code:

1. **Determinism is a correctness requirement.** Same (master seed, config,
   replication) → identical results on any backend, worker count, or build.
   A parallel result differing from the sequential reference is the worst bug
   class. No ordering may depend on completion order or wall-clock time.
2. **Thread ownership.** A `Sim` and everything attached to it belong to
   exactly one thread. Zero locks in the sequential hot path; the only locked
   structures are `llmsim.parallel` channels/mailboxes.
3. **Stdlib-only runtime.** The engine has zero required dependencies
   (`heapq`, `random`, `concurrent.futures`, `threading`, `compression.zstd`).
   `numpy` and `anthropic` are optional extras only.
4. **Hot path discipline.** `__slots__` on all hot-path classes; minimal
   per-event garbage; generators pin to their home thread (no work-stealing).
5. **LLM at design time only** (Phase 6). No LLM or network call after
   `run()` starts, on any code path — enforced by test. Tests/CI replay
   recorded fixtures, never the network.
6. **Typed public API.** Every public symbol fully annotated; generic
   `Event[T]`; mypy strict and pyright strict both clean.
7. **Honest performance claims.** Every speedup number is measured; slowdown
   regimes are documented alongside the feature that has them.

## Python version constraints

Targets **only Python ≥ 3.14**, both GIL and free-threaded (`3.14t`) builds —
CI runs `{3.14, 3.14t, 3.15-dev} × {Linux, macOS}` plus `PYTHON_GIL=0/1` on
3.14t. Detection: `sys._is_gil_enabled()` (runtime),
`sysconfig.get_config_var("Py_GIL_DISABLED")` (build). Don't add
compatibility shims for older Pythons.
