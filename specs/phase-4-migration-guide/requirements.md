# Requirements — Phase 4.3: Migration guide from SimPy 3

## Context

Roadmap step 4.3 delivers the migration guide promised to the project's
second-priority audience (`specs/mission.md`): SimPy 3 users moving to
llmsim's clean-break API. The mission explicitly rejects a compatibility
shim in favor of a concept-mapping guide (`env.process` → `sim.spawn`,
`env.timeout` → `sim.delay`) shipping with 1.0. The guide precedes the
docs site (step 4.4), so it lands as a plain Markdown page under `docs/`
that 4.4 later folds into the mkdocs-material build. The three canonical
models already exist as tested SimPy implementations
(`benchmarks/models/`) and llmsim ports (`benchmarks/llmsim_models/`);
this step turns that pair into the guide's worked examples without
duplicating the code as a second source of truth.

## Scope

In:

- A concept-mapping table covering the SimPy 3 concepts a migrating user
  hits: `Environment` → `Sim(seed=...)`, `env.process()` → `sim.spawn()`,
  `env.timeout()` → `sim.delay()`, `env.now` → `sim.now`,
  `env.run(until=...)` → `sim.run(until=...)`, `env.event()` →
  `Event`, condition composition (`&`/`|`, `AllOf`/`AnyOf`, multi-failure
  aggregation into `ExceptionGroup`), `simpy.Interrupt` →
  `llmsim.Interrupt`, the full resource family (`Resource`,
  `PriorityResource`, `PreemptiveResource`, `Container`, `Store`,
  `PriorityStore`, `FilterStore`), and RNG (module-level `random` →
  per-`Sim` `sim.rng`).
- A "what has no equivalent" section: SimPy names that intentionally do
  not map (`BoundClass`, `StopProcess`/`exit()`, `RealtimeEnvironment` →
  `llmsim.rt`, callback-style `defused` differences), stated per the
  mission's clean-break decision.
- Worked example ports of **all three canonical models** (M/M/1 queue,
  machine shop, 100×100 grid conveyor), each shown as side-by-side
  SimPy-vs-llmsim excerpts with prose walking through the deltas.
- Excerpts are **derived from the existing benchmark pairs**
  (`benchmarks/models/` and `benchmarks/llmsim_models/`) — the guide
  contains no third copy of any model; a snippet-sync test keeps guide
  excerpts textually identical to the referenced source regions.
- A snippet-sync test plus an API-coverage audit test (see
  `validation.md`).

Out:

- A "now go parallel" upsell section (`Experiment`, `sim.offload`,
  `ShardedSim` for migrated models) — deferred to the 4.4 docs site,
  which owns the parallelism decision-tree landing page.
- Docs-site integration, navigation, and theming — step 4.4.
- Any SimPy compatibility layer or adapter code — permanently out of
  scope per `specs/mission.md`.
- Migration tooling (automated codemods) — not on the roadmap.
- New runnable example directories — the existing benchmark models are
  the runnable artifacts.

## Decisions

- **Scope = roadmap scope** (user decision): concept table + all three
  canonical model ports; no parallel-upsell section in this step.
- **Single source of truth = benchmarks** (user decision): the guide's
  side-by-side code derives from `benchmarks/models/` (SimPy) and
  `benchmarks/llmsim_models/` (llmsim), both already run in CI. Guide
  excerpts carry machine-readable region markers and a test asserts
  each excerpt matches its source region byte-for-byte, so the guide
  cannot silently drift from tested code.
- **Validation = snippet tests + API audit** (user decision): every code
  excerpt in the guide is covered by the sync test, and a completeness
  test asserts the concept table covers the SimPy 3 public-API names
  exercised by the ported behavioral suite (Phase 1.10 tests).
- Inherited constraints: the guide is documentation plus stdlib-only
  test code — no new runtime dependencies (`specs/tech-stack.md`).
  SimPy is already a benchmark/dev dependency and is used only by
  tests/benchmarks, never by `src/llmsim/`.
- Guide file location: `docs/migration-from-simpy.md`, alongside the
  existing `docs/simpy-comparison.md` (which argues *why* to migrate;
  the new guide covers *how* — the two link to each other but do not
  merge).
