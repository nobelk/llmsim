# Validation — Phase 0: Scaffolding

## Success criteria

Phase 0 is done when the roadmap's stated exit criteria hold: **green CI across
the required matrix** with every gate enforced, **and SimPy 3 baselines recorded
and stored with the repo**. Concretely:

- The package installs and imports on both a GIL 3.14 build and a free-threaded
  3.14t build.
- **Required jobs** — every quality gate (ruff lint, ruff format check, mypy
  `--strict`, pyright strict, pytest) passes green across
  `{3.14, 3.14t} × {Linux, macOS}` plus the `PYTHON_GIL=0/1` axis on 3.14t.
  These are the jobs whose green status gates "Phase 0 done." *(Finding 2.)*
- **Canary job** — `3.15-dev × {Linux, macOS}` runs the same gates and reports
  results, but is `continue-on-error` and excluded from the required green
  status; its failure does **not** block Phase 0. It exists to surface upcoming
  free-threaded regressions early. *(Finding 2.)*
- Benchmark regression thresholds are wired into CI and **enforced** against
  committed SimPy 3 baselines (keyed per CI machine class). Enforcement is live
  wherever a baseline is committed (`Darwin-arm64` ships in-repo and enforces on
  `macos-latest` immediately); the first run for a machine class that has no
  committed baseline yet records one, uploads it as a CI artifact, and warns, so
  the recorded baseline can be committed to activate enforcement (the
  `Linux-x86_64` bootstrap — see `benchmarks/README.md`). *(Finding 1; the
  record-then-commit bootstrap resolves the fact that a valid timing baseline
  can only be recorded on its own CI runner class.)*
- The docs tool is committed (mkdocs-material) with a buildable skeleton.

## Checklist

**Package skeleton (Group 1)**
- [ ] `pyproject.toml` present: PEP 621, hatchling backend, `requires-python =
  ">=3.14"`, Apache-2.0, `src/` layout.
- [ ] All package-map modules exist as importable stubs with docstrings;
  `py.typed` present.
- [ ] `uv run python -c "import llmsim"` exits 0; `pip install -e .` builds.
- [ ] `uv.lock` committed; `numpy` / `llm` extras are **not** declared in Phase 0
  (deferred to their adapter phase — Finding 5).

**Quality gates (Group 2)**
- [ ] `uv run ruff check` and `uv run ruff format --check` clean (E/W/N/D rules
  active).
- [ ] `uv run mypy --strict` clean on `src/`.
- [ ] `uv run pyright` clean on `src/`.
- [ ] `uv run pytest` passes; smoke test (`import llmsim`, `__all__` is a list)
  present and green.
- [ ] `uv run pre-commit run --all-files` green.

**CI matrix (Group 3)**
- [ ] Workflow runs the full `{3.14, 3.14t, 3.15-dev} × {Linux, macOS}` matrix
  via `uv python install` against committed `uv.lock`.
- [ ] `PYTHON_GIL=0` and `PYTHON_GIL=1` sub-axis present on the 3.14t job.
- [ ] All gates run per PR; 3.14 pinned to latest 3.14.x; `3.15-dev` set
  `continue-on-error` and excluded from required status (Finding 2).
- [ ] Benchmark regression job present and **enforcing** where a baseline is
  committed — fails on KPI drift or timing-threshold breach; records-and-uploads
  (warns, does not fail) the first time a machine class has no committed baseline
  yet, so it can be committed to activate enforcement (Finding 1).
- [ ] 3.14t assertions-on concurrency soak job **scaffolded** (defined, runs a
  trivial no-op pass so it is visible in CI); real soak deferred to Phase 3
  (Finding 4).

**Benchmark harness + baselines (Group 4)**
- [ ] `benchmarks/` runs under pytest-benchmark; SimPy 3 is a dev-only
  dependency, absent from runtime deps.
- [ ] All **three** SimPy 3 models (M/M/1 queue, machine shop, 100×100 grid
  conveyor) are collected as named benchmark entries; CI **fails if any of the
  three is missing** (no silent partial harness). (Finding 3.)
- [ ] Each model has a fixed-seed determinism/KPI check: the same seed produces
  the same recorded KPI (e.g. mean wait / utilization / throughput) on repeated
  runs, asserting the model is deterministic before its timing is trusted.
  (Finding 3.)
- [ ] A baseline artifact committed for at least one required CI machine class
  (`Darwin-arm64`), enforcing immediately there; other machine classes
  (`Linux-x86_64`) record-and-upload on first CI run for later commit;
  regeneration, machine-class keying, and the bootstrap documented in
  `benchmarks/README.md`. (Finding 3.)
- [ ] Regression comparison fails the build on threshold breach.

**Docs tooling (Group 5)**
- [ ] `mkdocs.yml` + `docs/` skeleton build locally (`mkdocs build`).
- [ ] Decision-tree landing page reserved in nav.
- [ ] Sphinx-vs-mkdocs open item in `specs/tech-stack.md` marked resolved.

**Constraint audit (cross-cutting)**
- [ ] Runtime dependency set is empty (stdlib-only): SimPy 3, ruff, mypy,
  pyright, pytest, pytest-benchmark, mkdocs-material all appear only in
  dev/docs/benchmark dependency groups.
- [ ] No engine logic in any stub module (Phase 0 ships scaffolding only).

## Done when

The **required** jobs — `{3.14, 3.14t} × {Linux, macOS}` + the `PYTHON_GIL=0/1`
axis on 3.14t — are green with all gates enforced (including the enforcing
benchmark job); the `3.15-dev` canary runs and reports but does not gate; and
the SimPy 3 baseline artifacts are committed to the repo — matching the
roadmap's Phase 0 exit criteria.
