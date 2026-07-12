# Requirements — Phase 0: Scaffolding

## Context

Phase 0 is the first roadmap step: build a repo where every later step lands
with lint, types, tests, and benchmarks enforced from day one. There is no
`pyproject.toml`, `src/`, or test suite yet — this phase creates all of it.
It derives from `specs/roadmap.md` (Phase 0, steps 0.1–0.4) and must obey the
normative constraints in `specs/tech-stack.md` (stdlib-only runtime, Python
≥ 3.14 both GIL and free-threaded, `uv`/hatchling/ruff/mypy/pyright toolchain)
and the mission principle that *performance regression gates run in CI from
Phase 0 onward*. Nothing here ships engine behavior; the deliverable is the
scaffolding and the enforced quality bar that Phase 1 builds on.

## Scope

### In

- **0.1 Package skeleton** — `pyproject.toml` (PEP 621, hatchling build
  backend, `requires-python = ">=3.14"`, Apache-2.0 metadata), `src/llmsim/` layout
  with empty/stub modules matching the package map in `specs/tech-stack.md`
  (`core/`, `resources/`, `rand/`, `parallel/` incl. `pdes/`, `scenario/`,
  `rt.py`, `trace.py`), `__init__.py` public-API stub, README stub, committed
  `uv.lock`.
- **0.2 Quality gates** — ruff (lint + format, enforcing PEP 8 via `E`/`W`
  pycodestyle + `N` pep8-naming, PEP 257 docstrings), mypy `--strict`, pyright
  strict, pytest wiring, pre-commit config, and one trivial smoke test that
  proves the gate pipeline runs green.
- **0.3 CI matrix** — GitHub Actions running the full matrix
  `{3.14, 3.14t, 3.15-dev} × {Linux, macOS}` plus the `PYTHON_GIL=0/1` axis on
  3.14t, provisioning interpreters via `uv python install`, running every 0.2
  gate per PR against the committed `uv.lock`, and enforcing benchmark
  regression thresholds (from 0.4). Also **scaffolds** (defines, but does not
  yet exercise) the 3.14t assertions-on concurrency soak job that the
  tech-stack CI contract requires; the real randomized soak run is Phase 3
  (3.5). *(Finding 4.)*
- **0.4 Benchmark harness** — pytest-benchmark scaffolding; three canonical
  models implemented as **SimPy 3** programs (M/M/1 queue, machine shop,
  100×100 grid conveyor network); SimPy 3 baseline numbers recorded per CI
  machine class and committed to the repo.
- **Docs-tooling decision** — commit to **mkdocs-material** as the docs
  generator (resolving the tech-stack's open "Sphinx or mkdocs-material —
  decide in Phase 0" item); scaffold a minimal docs skeleton reserving the
  "Which parallelism do I need?" decision-tree landing page. Full docs *content*
  is Phase 4 (4.4); this phase only fixes the tool and the skeleton.

### Out

- Any engine behavior — events, `Sim` loop, processes, resources, RNG, PDES,
  offload (Phases 1–4). Stub modules only; no runnable simulation logic.
- SimPy 3 baselines are recorded from **SimPy 3** implementations only; the
  llmsim reimplementations of the three models are Phase 1 (1.11).
- Full documentation content / published docs site (Phase 4.4). Only the tool
  choice and an empty skeleton land here.
- Optional extras (`numpy`, `anthropic`/`llm`) are **not** declared in Phase 0.
  The tech-stack defines them as real user-facing extras with real dependencies;
  declaring empty stubs now would be a misleading packaging contract, so each is
  declared alongside its adapter code in the phase that introduces it (numpy →
  Phase 2, llm → Phase 6). *(Finding 5.)*
- Publishing to PyPI (Phase 4.5).

## Decisions

- **Docs generator = mkdocs-material** (key decision). Markdown-native, and the
  library leads with a decision-tree landing page over API autodoc; mermaid /
  admonitions / content-tabs support that page directly. Recorded here to close
  the tech-stack open item. *(Consequence: no reStructuredText/autodoc pipeline;
  Python API reference, when needed later, uses an mkdocs-compatible plugin.)*
- **Full Phase 0 in one spec** (0.1–0.4), but `plan.md` orders the four
  sub-steps so each lands as its own independently-mergeable PR, smallest slice
  first.
- **Definition of done = the roadmap's stated exit criteria**: green CI across
  the full matrix with every gate enforced, and SimPy 3 baselines recorded and
  stored with the repo.
- **Inherited from tech-stack (normative, not re-litigated here):** stdlib-only
  runtime with zero required dependencies (SimPy 3, pytest-benchmark, ruff,
  mypy, pyright, mkdocs-material are **dev/docs** dependencies, never runtime);
  `uv` for all dev workflows with committed `uv.lock`; hatchling build backend,
  `src/` layout, single non-namespace package; both mypy strict and pyright
  strict must pass; pure-Python `py3-none-any` wheel, no compiled extensions.
- **Version pinning:** CI pins to the latest 3.14.x point release; 3.15-dev is
  a non-blocking canary axis (free-threaded behavior still evolving).
- **Benchmark thresholds are enforced (fail-on-regression) once baselines
  exist**, per the mission's "regression gates from Phase 0 onward"; baselines
  are keyed per CI machine class so cross-machine variance does not cause false
  failures.
