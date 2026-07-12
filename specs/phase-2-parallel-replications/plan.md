# Plan — Phase 2: Parallel replications + reproducible randomness

Task groups are ordered by dependency; each is sized to land as its own
commit/PR. Group 1 is the smallest mergeable slice (pure, sequential, no
parallelism) and everything downstream builds on it. Every group that introduces
a parallel capability ships a same-seed-same-result test in the same PR, and
Group 6 documents scaling/slowdown regimes in its PR (cross-cutting rules).

## 1. Seed tree (`rand/streams.py`)

- `SeedStream` (or equivalent): given `(master_seed, config_index,
  replication_index)`, derive a child seed via `SHA-256` of a fixed, documented
  canonical path serialization, truncated to 128 bits, and construct a
  `random.Random` from it.
- A `SeedTree(master_seed)` entry point that mints per-`(config, replication)`
  streams and exposes the exact seam the Phase 1 `Sim(rng=...)` constructor
  consumes.
- Tests (testable proxies for "independent, stable streams", not an unprovable
  statistical-independence claim): **known-answer** tests pinning the canonical
  path serialization and the derived child seed for fixed triples;
  **no-collision** over a specified sample of `(config, replication)` triples;
  **stability** — same triple → same pinned first-N draws as literals, across
  runs/platforms/builds; **same-seed-same-result** at the stream level; and a
  **bounded statistical smoke test** (e.g. a chi-square/mean check on sibling
  streams against explicit, generous thresholds) to catch a grossly biased
  derivation. No parallelism, no third-party deps.

## 2. Execution backends (`parallel/backends.py`)

- `ExecutionBackend` abstraction with one `submit`/map interface over
  `ThreadPoolExecutor`, `InterpreterPoolExecutor`, and `ProcessPoolExecutor`;
  payloads are *(importable callable, seed spec, config)* references only.
- `backend="auto"` runtime selection: `sys._is_gil_enabled()` /
  `Py_GIL_DISABLED` → `3.14t` (GIL off) picks threads; GIL build picks
  **processes** (the key decision); explicit `backend=` honored verbatim.
- Factory-importability validation at construction: reject closures/lambdas/local
  functions with an actionable error naming the fix (module-level callable).
  Preflight config picklability where the backend requires it, and wrap a
  worker-side result-serialization failure in an actionable error naming the
  offending `(config, replication)`.
- Tests: each backend runs a trivial importable task to identical results;
  `auto` resolves correctly per build; importability validation raises the
  documented error; an **unpicklable config** and an **unpicklable result** each
  raise the documented actionable error on the process/interpreter backends (not
  a silent partial run); `max_workers=None` defaults sensibly.

## 3. Experiment API (`parallel/replicate.py`)

- `Experiment(factory, configs=[...], master_seed=...)`, `run(replications,
  backend="auto", max_workers=None)` returning a result set keyed by
  `(config index, replication index)`; `ReplicationResult` carrying the
  config/replication identity and the factory's returned (picklable) value; a
  functional `run_replications(...)` wrapper. The **explicit `master_seed`** is
  required (no ambient default; a convenience default, if any, is a fixed
  constant echoed back on the result set — never OS entropy).
- Wire the Group 1 seed tree → per-`(config, replication)` stream → the factory's
  `Sim`; results collected eagerly first (streaming lands in Group 4).
- Tests: N replications × M configs produce M×N correctly-keyed results; **two
  runs with the same explicit `master_seed` and inputs produce identical keyed
  result sets**; results independent of completion order (shuffle-safe); a KPI
  study on a Phase 1 canonical model reproduces the sequential per-replication
  results.

## 4. Result streaming + cancellation (`parallel/replicate.py`, `parallel/backends.py`)

- `exp.iter_results()` yielding `ReplicationResult`s **as they complete** (still
  identity-keyed, so order-insensitive aggregation is unaffected).
- Backend-aware cancellation behind one `Experiment.cancel()` / context-manager
  exit. The **cooperative contract**: the factory receives a cancellation handle
  (token/context alongside seed + config) that a cancellation-aware run consults
  between `step()`s, giving mid-replication cancel on the thread backend; a factory
  that owns its own `sim.run()` without consulting the handle is cancelled at
  replication granularity even on threads (documented). Interpreter/process
  backends stop dispatching queued work and `Future.cancel()` pending submissions
  (always replication-granularity).
- **Opt-in** `compression.zstd` spooling of large per-replication traces/results
  to bound peak memory (the capability is built and tested here; whether a study
  *uses* it is the caller's choice); warm-pool reuse on the interpreter backend
  (import the model module once, run many replications).
- Tests: `iter_results()` yields all results exactly once; cancel stops further
  dispatch and leaves collected results consistent; **a factory that calls
  `sim.run()` internally is cancelled at replication granularity, and a
  cancellation-handle-aware factory is cancelled mid-replication**; when spooling
  is enabled, spooled results round-trip bit-identically; warm-pool reuse runs
  many replications per worker.

## 5. Backend conformance tests (`tests/`)

- **Identical result sets across all three backends** for fixed seeds on the
  Phase 1 canonical models — the concrete proof of the reproducibility guarantee.
- GIL re-enable detection: if importing a model in a worker re-enables the GIL
  (an extension calling `PyGILState`), detect it and emit a loud, actionable
  warning naming the offending import.
- Tests run on 3.14 and 3.14t (`PYTHON_GIL=0/1`); each backend's result set is
  asserted equal to the sequential reference and to the other backends'.

## 6. Scaling benchmarks + docs (`benchmarks/`, `docs/`)

- Replication-throughput-vs-worker-count benchmarks on 3.14t (threads) and the
  GIL build (processes); publish the measured curves. Enforce a parallel-efficiency
  regression gate that is meaningful on the available CI core count (see
  `validation.md`), with the headline ≥6×-on-8-physical-cores number validated in
  an 8+-core environment.
- RSS-per-replication guidance on 3.14t (larger object headers, mimalloc,
  stop-the-world GC), with worker-count recommendations.
- The **"Which parallelism do I need?"** decision-tree docs page (replications vs
  PDES vs offload), wired into the mkdocs nav as the parallel landing page, and a
  documented list of the unsupported nondeterminism sources that fall outside the
  reproducibility guarantee (docs-honesty rule).
