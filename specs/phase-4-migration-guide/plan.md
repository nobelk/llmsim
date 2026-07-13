# Plan — Phase 4.3: Migration guide from SimPy 3

## 1. Guide skeleton + concept-mapping table

- Create `docs/migration-from-simpy.md` with: intro (who the guide is
  for, clean-break stance, link to `docs/simpy-comparison.md`), the
  concept-mapping table, and the "what has no equivalent" section.
- Table rows grouped by area: environment/loop, processes, events and
  conditions, interrupts and errors, resources, RNG and determinism,
  real-time mode. Each row: SimPy 3 name → llmsim name → one-line note
  on any semantic delta (e.g. `sim.rng` replaces module-level `random`;
  condition failures aggregate into `ExceptionGroup`).
- Cross-link from `README.md` and `docs/index.md`.
- Smallest mergeable slice: the table is useful on its own before any
  worked example lands.

## 2. Snippet-sync test harness

- Define the excerpt marker convention: fenced code blocks in the guide
  are preceded by an HTML comment naming source file and named region,
  e.g. `<!-- snippet: benchmarks/models/mm1.py#customer -->`; regions
  are delimited in source files with `# --8<-- [start:customer]` /
  `# --8<-- [end:customer]` comments (the mkdocs-material
  "snippets" syntax, so step 4.4 can later switch to native includes
  with zero marker churn).
- Add `tests/docs/test_migration_guide_snippets.py`: parse the guide,
  and for every marked fence assert the block equals the referenced
  region byte-for-byte (after dedent). Fail loudly on markers pointing
  at missing files/regions and on marked fences with no marker match.
- The test also scans **all** Python fences in the guide and fails on
  any fence lacking a preceding snippet marker — an unmarked excerpt
  cannot slip in unsynced (finding 1).
- Stdlib-only test code (`pathlib`, `re`); runs in the normal pytest
  gate on every PR, both builds.

## 3. Worked port: M/M/1 queue

- Add region markers to `benchmarks/models/mm1.py` and
  `benchmarks/llmsim_models/mm1.py` around the process functions and
  the setup/run entry points (marker comments only — zero behavior
  change; benchmark regression gate proves it).
- Write the M/M/1 section of the guide: side-by-side excerpts plus
  prose covering the migration deltas this model exercises —
  `Environment` → `Sim(seed=...)`, `env.process` → `sim.spawn`,
  `env.timeout` → `sim.delay`, `Resource` request/release, and moving
  from a hand-seeded `random.Random(seed)` to the built-in `sim.rng`
  (the concept table in §1 additionally covers the module-level
  `random` habit common in SimPy user code) (finding 3).

## 4. Worked ports: machine shop + grid conveyor

- Same marker treatment for `machine_shop.py` and `grid_conveyor.py`
  in both model directories.
- Machine-shop section: interrupts (`simpy.Interrupt` →
  `llmsim.Interrupt`), `PreemptiveResource`, and process-to-process
  interaction.
- Grid-conveyor section: per-cell single-capacity `Resource`
  contention at scale (the `Store` family is covered by the concept
  table, not this example — finding 3) and the determinism payoff
  (`(time, priority, eid)` ordering; same seed → same trace) as the
  bridge the 4.4 docs site will build on.

## 5. API-coverage audit test

- Add `tests/docs/test_migration_guide_coverage.py` with a checked-in
  explicit name list that is the **union** of (a) the required
  inventory from `requirements.md` — including every "no equivalent"
  name (`BoundClass`, `StopProcess`, `RealtimeEnvironment`, …) — and
  (b) the SimPy 3 public-API names exercised by the ported behavioral
  suite, guarded by a test that (b) stays in sync with the suite's
  provenance notes (finding 2). Assert every listed name appears in
  the guide's concept table or its "no equivalent" section.
- The failure message names the missing concepts, so API additions
  that reach the behavioral suite force a guide update in the same PR.
