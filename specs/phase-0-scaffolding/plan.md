# Plan — Phase 0: Scaffolding

Four task groups, ordered by dependency; each is sized to land as its own PR.
Group 1 is the smallest mergeable slice (an installable, empty package). Later
groups layer gates, CI, and benchmarks on top without reworking earlier ones.

## 1. Package skeleton (roadmap 0.1)

- `pyproject.toml`: PEP 621 metadata, `build-backend = "hatchling.build"`,
  `requires-python = ">=3.14"`, Apache-2.0 license, project name `llmsim`, `src/`
  layout configured for hatchling.
- `src/llmsim/` tree with empty/stub modules matching the tech-stack package
  map: `__init__.py` (public-API re-export stub with `__all__ = []`),
  `core/{__init__,sim,events,process,errors}.py`, `resources/{__init__,base,
  resource,container,store}.py`, `rand/{__init__,streams}.py`,
  `parallel/{__init__,backends,replicate,offload}.py`,
  `parallel/pdes/{__init__,shard,channel,sync}.py`,
  `scenario/{__init__,schema,inject,llm,agent,report}.py`, `rt.py`, `trace.py`.
  Each stub carries a module docstring naming its future responsibility; no
  logic. Add `py.typed` marker for downstream type checkers.
- `README.md` stub (project name, one-line pitch, `pip install llmsim`
  placeholder, link to `specs/`); keep pip-based install examples (per CLAUDE.md,
  don't convert to uv).
- `uv venv` + `uv sync`; commit the generated `uv.lock`. Do **not** declare the
  `numpy` / `llm` extras yet: the tech-stack defines them as real user-facing
  extras (`llmsim[numpy]` pulls the NumPy adapter deps; `llmsim[llm]` pulls the
  Anthropic SDK), so an empty stub would be a misleading packaging contract.
  Each extra is declared — with its real optional dependency — in the phase that
  introduces its adapter code (numpy → Phase 2, llm → Phase 6). *(Finding 5.)*
- Smoke check: `uv run python -c "import llmsim"` succeeds; `pip install -e .`
  builds via hatchling.

## 2. Quality gates + smoke test (roadmap 0.2)

- Configure **ruff** in `pyproject.toml`: enable `E`/`W` (pycodestyle),
  `N` (pep8-naming), `D` (pydocstyle, PEP 257 convention) plus a sensible base
  (`F`, `I`); `ruff format` as the formatter. Document `uv run ruff check` /
  `uv run ruff format` as the canonical commands.
- Configure **mypy** (`--strict`, `python_version = 3.14`) and **pyright**
  (strict mode) — both target `src/`; both must pass clean on the stubs.
- Wire **pytest** (`tests/` dir, `pyproject.toml` config); add one trivial smoke
  test (e.g. `test_import.py` asserting `import llmsim` and `__all__` is a list)
  that proves the gate pipeline runs and is green.
- **pre-commit** config running ruff (lint + format), and a fast type/pytest
  hook; document `uv run pre-commit run --all-files`.
- Dev dependency group in `pyproject.toml`: ruff, mypy, pyright, pytest,
  pre-commit (and hypothesis, pytest-repeat named for later phases). None are
  runtime deps.

## 3. CI matrix (roadmap 0.3)

- GitHub Actions workflow (`.github/workflows/ci.yml`): matrix over
  `python ∈ {3.14, 3.14t, 3.15-dev}` × `os ∈ {ubuntu-latest, macos-latest}`,
  interpreters installed via `uv python install`; jobs run through `uv run`
  against the committed `uv.lock`.
- Add the `PYTHON_GIL ∈ {0, 1}` sub-axis on the `3.14t` job only.
- Per-PR gate job runs: `ruff check`, `ruff format --check`, `mypy --strict`,
  `pyright`, `pytest`. Pin the 3.14 axis to the latest 3.14.x point release;
  mark `3.15-dev` as `continue-on-error` (non-blocking canary).
- Benchmark regression job: **no no-op merge path.** Group 4 (baselines) lands
  before the enforcing benchmark step, so this job either fails on missing
  baselines or enforces thresholds against committed baselines — it is never
  wired-but-inert. Group 3's benchmark job is not considered complete or
  mergeable until it actually enforces. *(Finding 1.)*
- Concurrency soak job stub on `3.14t` (assertions-on debug build) — **scaffold
  only** in Phase 0 (job defined, runs a trivial no-op assertion pass so it is
  visible in CI); the real long randomized soak is Phase 3 (3.5). Called out in
  `requirements.md`/`validation.md` so "Phase 0 done" cannot skip the scaffold.
  *(Finding 4.)*

## 4. Benchmark harness + SimPy 3 baselines (roadmap 0.4)

- `benchmarks/` with **pytest-benchmark** wiring; SimPy 3 added as a
  **dev/benchmark-only** dependency (never runtime).
- Implement the three canonical models as SimPy 3 programs: M/M/1 queue,
  machine shop, 100×100 grid conveyor network — parameterized, deterministic
  (seeded), each with a benchmark entry point.
- Record SimPy 3 baseline numbers per CI machine class; commit the baseline
  artifacts to the repo (e.g. `benchmarks/baselines/<machine-class>.json`).
- Wire pytest-benchmark regression comparison against the committed baselines
  with fail-on-regression thresholds; enable enforcement in the Group 3 CI job.
- Document how to regenerate baselines and the machine-class keying.

## 5. Docs-tooling decision (cross-cutting, small)

- Add **mkdocs-material** as a docs dependency group; `mkdocs.yml` with a
  minimal nav reserving the "Which parallelism do I need?" decision-tree page
  as the parallel landing page (placeholder content only).
- `docs/` skeleton (index + placeholder decision-tree page). Record the
  Sphinx-vs-mkdocs decision in `specs/tech-stack.md`'s open item (or note it as
  resolved). Full docs content is Phase 4.4 — out of scope here.
- Can ride along with Group 1 or land as a tiny standalone PR; no dependency on
  Groups 2–4.
