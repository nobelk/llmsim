# Requirements — Phase 4.4 (docs site) + 4.5 (1.0 API freeze audit)

## Context

Roadmap steps 4.4 and 4.5 close out Phase 4. A mkdocs-material skeleton
already exists (`mkdocs.yml`, six pages under `docs/`, a non-gating
`mkdocs build --strict` CI job); 4.4 turns it into the full documentation
site the mission promises — decision tree as the parallel landing page,
published scaling curves, an API reference — with a real deployment
pipeline. 4.5 performs the public-API audit (typing completeness, naming
consistency, deprecation policy) that precedes the 1.0 freeze. The actual
1.0 tag and PyPI publish remain **gated on Phase 5** (the domain examples
are the API's dogfooding pass) and are explicitly out of scope here.

## Scope

In:

- **API reference** — auto-generated from docstrings via an
  mkdocs-compatible plugin (mkdocstrings, per `specs/tech-stack.md`),
  covering every public symbol re-exported from `llmsim/__init__.py` and
  the public `llmsim.rt` / `llmsim.trace` / `llmsim.parallel` surfaces;
  docstring gaps filled where the generator exposes them.
- **User guide** — task-oriented pages: getting started, core concepts
  (Sim/events/processes/conditions), resources, parallel replications
  (`Experiment`), PDES sharding, compute offload, real-time mode, tracing
  and determinism. The existing "Which parallelism do I need?" decision
  tree becomes the landing page of the parallel section, per the roadmap.
- **Published scaling curves** — the Phase 2 replication-throughput and
  Phase 3 shard-scaling / lookahead-degradation measurements (currently in
  `docs/perf-notes.md`) rendered as committed chart artifacts on dedicated
  docs pages, with their slowdown regimes stated alongside (mission
  principle 3: honest performance claims).
- **Deployment** — GitHub Pages, latest-only: a CI workflow deploys the
  built site on every push to `main`. `mkdocs build --strict` becomes a
  required PR gate.
- **4.5 public-API audit** — a committed audit document walking every
  public symbol: fully annotated (mypy/pyright strict already enforce
  this — the audit confirms *public-surface completeness*, e.g. `__all__`
  consistency, no accidental exports, generics like `Event[T]` surfaced
  correctly), naming consistency in DES domain terms, docstring presence,
  and a written deprecation policy for the 1.x series.
- Roadmap updated: 4.4 ticked when done; 4.5 annotated as
  "audit complete, tag/publish pending Phase 5".

Out:

- Tagging 1.0 and publishing to PyPI — deferred until Phase 5 examples are
  green, per the roadmap gate (user decision).
- Versioned documentation (mike) or Read the Docs — latest-only GitHub
  Pages was chosen; per-version docs can be added post-1.0 if needed.
- Docs pages for the Phase 5 examples — those land with Phase 5 itself.
- Any API *changes* the audit surfaces beyond mechanical fixes (renames,
  deprecations) — findings are filed and resolved in follow-up PRs so the
  audit stays reviewable.

## Decisions

- **Deployment: GitHub Pages, latest-only** (user decision) — CI deploys
  on every push to `main` via GitHub Actions; no external hosting service,
  no versioning tooling until a release cadence exists.
- **API reference: mkdocstrings** — the mkdocs-compatible plugin route
  already named in `specs/tech-stack.md`; added to the `docs` dependency
  group only (the runtime stays stdlib-only, per the normative
  constraints).
- **Validation: CI gates + audit doc** (user decision) — the strict docs
  build becomes a required PR check, the deploy workflow must run green
  end-to-end, and the 4.5 audit ships as a reviewed, committed checklist
  covering every public symbol.
- Inherited constraints: zero required runtime dependencies (docs tooling
  is dev-group only); every performance number shown in the docs is a
  measured one with its slowdown regime documented (tech-stack normative
  rule; mission principle 3); `uv` drives all doc workflows
  (`uv run mkdocs ...`).
