# Requirements — Phase 2: Parallel replications + reproducible randomness

## Context

Phase 1 delivered the fully typed, `__slots__`-based sequential core, including
the per-`Sim` `rng` seam (step 1.5) that this phase plugs into. Phase 2 is the
**flagship**: a first-class Monte Carlo / experiment API that runs N independent
replications across cores and returns **bit-identical results across backends**,
delivering the mission's headline promise — "run your stochastic studies 6–14×
faster on the hardware you already own, with bit-reproducible results, without
leaving pure Python." The 80% use case (a module-level factory plus one
`Experiment(...).run()` call) must be the easy path (mission principle 4); the
reproducibility guarantee is a correctness requirement, not a feature (principle
2). Parallelism comes from **share-nothing architecture** — many independent
`Sim`s, one per worker — never from locking the sequential engine (principle 1).

## Scope

### In

- **2.1 Seed tree** — `rand/streams.py`: a master seed derives statistically
  independent per-`(config index, replication index)` streams by SHA-256 hashing
  a canonical seed path into 128-bit child seeds for `random.Random`. This is
  the determinism backbone (tech-stack constraint 7); unit-tested for
  independence and cross-run stability.
- **2.2 Execution backends** — `parallel/backends.py`: an `ExecutionBackend`
  abstraction over `ThreadPoolExecutor` (free-threaded 3.14t),
  `InterpreterPoolExecutor` (PEP 734), and `ProcessPoolExecutor`; `backend="auto"`
  runtime selection; **factory-importability validation at construction** with
  actionable errors. Work is submitted as *(importable callable, seed spec,
  config)* references, never live objects, so all three backends share one code
  path (tech-stack constraint 5).
- **2.3 Experiment API** — `parallel/replicate.py`: `Experiment`,
  `run_replications()`, and `ReplicationResult`; an **explicit master seed** is a
  first-class parameter of the public API (see Decisions); results keyed by
  `(config index, replication index)`, **never completion order**. Wires the seed
  tree → per-`(config, replication)` stream → user factory. Configs and returned
  results must survive the chosen backend's transport; unpicklable inputs/outputs
  are surfaced as actionable errors, not silent partial runs (see Decisions).
- **2.4 Result streaming + cancellation** — `exp.iter_results()` yielding
  as-completed; **backend-aware cancellation** (thread backend: a shared token
  checked between `step()`s for mid-replication cancel — see the cooperative
  cancellation contract in Decisions; interpreter/process backends:
  replication-granularity cancel — stop dispatching and `Future.cancel()` pending
  work, since isolated workers cannot see a parent token); **opt-in**
  `compression.zstd` spooling for large per-replication traces (a Phase 2
  deliverable whose *use* is optional, not whose *implementation* is); warm-pool
  reuse on the interpreter backend to amortize per-interpreter import cost.
- **2.5 Backend conformance tests** — identical result sets across all three
  backends for fixed seeds (validates the reproducibility guarantee); GIL
  re-enable detection after model import in workers, with a loud warning.
- **2.6 Scaling benchmarks + docs** — replication throughput vs worker count on
  3.14t and GIL builds; published curves; RSS-per-replication guidance; the
  "Which parallelism do I need?" decision-tree docs page.

### Out

- **Single-run PDES** (Phase 3), **compute offload** (4.1), **real-time mode**
  (4.2), **LLM scenario generation** (Phase 6) — later phases.
- **numpy Philox RNG adapter** — the optional `llmsim[numpy]` vectorized-draw
  adapter is deferred to a follow-up; Phase 2's seed tree and engine stay
  stdlib-only (`hashlib` + `random.Random`). The seed-tree design leaves a
  documented seam for it.
- **Interpreter-backed PDES** — permanently out for 1.0 (mission): subinterpreters
  cannot share thread-mode mailboxes or live `Sim`s.
- **Distributed / multi-machine** replication — 1.0 targets single multicore
  machines.
- **Optimistic / Time Warp** synchronization — permanently rejected (generator
  frames cannot be snapshotted).
- **Mid-replication cancellation on the interpreter/process backends** — cannot
  see a parent token; replication-granularity only, documented per backend.

## Decisions

- **GIL-build `backend="auto"` defaults to `ProcessPoolExecutor` (key decision,
  diverges from the design doc).** On the free-threaded build (`3.14t`, GIL
  disabled) `auto` selects `ThreadPoolExecutor`. On a **GIL build**, `auto`
  selects the battle-tested `ProcessPoolExecutor` (forkserver default on Linux);
  `InterpreterPoolExecutor` is **opt-in** via `backend="interpreters"`. This
  **supersedes `docs/part-deux.md` §4.4**, which defaulted GIL builds to
  `InterpreterPoolExecutor`. Rationale: PEP 734 subinterpreters are new in 3.14
  with stricter shareability rules and non-trivial per-interpreter cost;
  defaulting to processes gives predictable, reliable behavior now, and the
  default can flip to interpreters in a later release as PEP 734 matures. Per
  CLAUDE.md, this design change is recorded here in `specs/` (which wins over the
  design doc). An explicit `backend=` argument is always honored verbatim.
- **The master seed is an explicit, required public-API parameter (normative).**
  `Experiment` / `run` / `run_replications` take an explicit `master_seed` (an
  `int`); the reproducibility guarantee is defined only for a caller-supplied
  seed. There is **no ambient/implicit default seed** — omitting it is an error
  (or, if a convenience default is offered, it is a fixed constant that is echoed
  back on the result, never OS entropy), so a study can always be reproduced and
  backends compared from a controlled seed. This is the `master_seed` consumed by
  the seed-tree derivation below.
- **Seed derivation is SHA-256 path hashing (normative).** A child seed is
  `SHA-256(canonical_path(master_seed, config_index, replication_index))`
  truncated to 128 bits, used to construct `random.Random`. The path
  serialization is fixed and documented so the same triple yields the same seed
  on every platform, backend, worker count, and build (determinism constraint 7).
  This is the single seam the Phase 1 `Sim(rng=...)` / `Sim(seed=...)` constructor
  consumes.
- **Cooperative cancellation contract (normative for the thread backend).**
  Mid-replication cancellation requires cooperation, because a factory that owns
  its own `sim.run()` cannot be preempted from outside. The contract: the factory
  receives a cancellation handle (a token/context passed alongside seed + config)
  that a cancellation-aware run consults between `step()`s; a factory that does
  **not** consult it is cancelled at **replication granularity** even on the
  thread backend (documented, not silently broken). Interpreter/process backends
  are always replication-granularity. Acceptance includes a factory that calls
  `sim.run()` internally.
- **Backend transport is validated, not assumed (normative).** Because the GIL
  default backend is processes, configs and returned results cross a pickle
  boundary. Configs are preflight-checked for importability/picklability where
  possible at `Experiment` construction, and a result that fails to serialize in a
  worker is surfaced as an actionable error identifying the offending
  config/replication — never a silent partial result set. Defined behavior for a
  failed replication (surface-and-continue vs fail-fast) is part of the contract.
- **Executor payloads are references, not objects (normative).** Every backend
  receives *(importable callable, seed spec, config)*; the factory must be an
  importable module-level callable (no closures/lambdas), validated at
  `Experiment` construction with an actionable error. This is why switching
  backends is a one-word change.
- **Results are keyed by `(config index, replication index)` (normative).**
  Aggregation is order-insensitive by construction; completion order never
  affects results.
- **Backend-portable determinism guarantee (scoped, from design §4.5).** llmsim
  guarantees the same `(master seed, config, replication)` triple receives the
  same RNG stream and the same deterministic event ordering on any backend,
  worker count, and build. End-to-end identical *results* follow whenever the
  model itself is deterministic and backend-portable — no reliance on wall clock,
  unordered iteration of identity-keyed containers, global mutable module state,
  or native extensions with their own threading/rounding. The known unsupported
  nondeterminism sources are **listed in the docs**, not silently absorbed into
  the guarantee.
- **Stdlib-only (normative).** `hashlib`, `random`, `concurrent.futures`,
  `threading`, `compression.zstd` — no third-party runtime dependency.
- **Cancellation semantics are one API, two granularities.** One
  `Experiment.cancel()` (or context-manager exit) with the thread-vs-isolated
  granularity difference documented per backend, not two APIs.
