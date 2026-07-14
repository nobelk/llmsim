# Plan — Phase 4.4 (docs site) + 4.5 (1.0 API freeze audit)

Task groups are ordered so each can land as its own commit/PR. Group 1 is
the smallest mergeable slice.

## 1. Nav completion + strict build as a required gate

- Add the pages missing from `mkdocs.yml` nav (e.g.
  `migration-from-simpy.md` is linked from the index but absent from nav).
- Fix any warnings `uv run mkdocs build --strict` surfaces after the nav
  change.
- Promote the existing `docs` CI job to a required PR gate (remove the
  "not required" caveat; include it in the required-checks set).

## 2. API reference via mkdocstrings

- Add `mkdocstrings[python]` to the `docs` dependency group in
  `pyproject.toml` (dev-only; runtime stays stdlib-only) and configure the
  plugin in `mkdocs.yml`.
- Create `docs/reference/` pages: one page per public module area — core
  (`Sim`, `Event`, `Timeout`, `Process`, conditions, errors), resources,
  randomness (`SeedTree`, `SeedStream`), parallel (backends, `Experiment`,
  offload, PDES), real-time, tracing — sourced from the
  `llmsim/__init__.py` re-export list.
- Fill docstring gaps the generated reference exposes (public classes,
  methods, module docstrings); keep PEP 257 style so ruff's pydocstyle
  rules stay green.

## 3. User guide

- `docs/guide/` pages: getting started (install via `pip`, first model),
  core concepts (Sim/events/processes/conditions/interrupts), resources
  and stores, parallel replications with `Experiment`, PDES sharding,
  compute offload, real-time mode, tracing & determinism guarantees.
- Restructure nav so "Which parallelism do I need?"
  (`parallelism-decision-tree.md`) is the landing page of the parallel
  section, with the replication/PDES/offload guide pages beneath it.
- Cross-link the migration guide and canonical-model examples from
  getting-started.

## 4. Published scaling curves

- Render the measured Phase 2 (replication throughput vs worker count,
  per backend/build) and Phase 3 (shard scaling, lookahead-degradation)
  curves from the recorded benchmark data into committed SVG/PNG chart
  artifacts under `docs/`.
- Dedicated pages (or expanded `perf-notes.md` sections) presenting each
  curve with its measurement setup (machine class, build, seed) and the
  documented slowdown regimes alongside — no unmeasured claims.

## 5. GitHub Pages deployment

- New workflow (or job) deploying the built site to GitHub Pages on every
  push to `main` (`actions/upload-pages-artifact` +
  `actions/deploy-pages`, `pages`/`id-token` permissions).
- Point `pyproject.toml`'s `Documentation` URL and the README docs link at
  the published site.
- Verify the deployed site end-to-end once live (nav, reference pages,
  chart artifacts render).

## 6. Public-API audit + deprecation policy (4.5, audit portion)

- Write `specs/phase-4.4-4.5/api-audit.md`: a table of every public
  symbol (from `llmsim.__all__` and public submodule surfaces) ×
  (annotated / documented / named consistently / in API reference).
- Verify `__all__` consistency: every re-export listed, no accidental
  public names in submodules (script or test that diffs `__all__` against
  the reference pages).
- Naming-consistency review in DES domain terms; file findings as issues —
  renames/deprecations execute in follow-up PRs, not inside the audit PR.
- Write the 1.x deprecation policy (docs page: what SemVer promises, how
  deprecations are announced, minimum deprecation window).
- Update `specs/roadmap.md`: tick 4.4; annotate 4.5 as audit-complete with
  tag/publish pending the Phase 5 gate.
