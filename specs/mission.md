# Mission — llmsim

## Vision

**llmsim** is a parallel discrete-event simulation (DES) library for Python 3.14+
that keeps SimPy's proven generator-as-process model and rebuilds everything else
for the modern CPython concurrency era. One clean, fully typed core; parallelism
that comes from architecture (share-nothing simulations with explicit, narrow
communication points), never from locks bolted onto a sequential engine.

The headline promise: **run your stochastic studies 6–14× faster on the hardware
you already own**, with bit-reproducible results, without leaving pure Python.

## Audience

Primary audiences, in order:

1. **Industrial engineers and practitioners** — people modeling factories, rail
   networks, warehouses, queues, and logistics systems who want faster runs
   (thousands of Monte Carlo replications, parameter sweeps, one enormous model)
   with minimal parallel-programming expertise. The API must make the fast path
   the easy path: `Experiment(...).run(backend="auto")` should be all most users
   ever need.
2. **SimPy 3 users migrating** — the existing DES-in-Python community. llmsim is
   a clean break in API (no compatibility shim), but a familiar one: generators
   remain the process primitive, resources keep their request/release semantics,
   and a concept-mapping migration guide (`env.process` → `sim.spawn`,
   `env.timeout` → `sim.delay`) ships with 1.0.

Secondary: simulation researchers who need the reproducibility guarantees
(seed trees, deterministic event ordering, trace equivalence) for publishable work.

## Scope

### In scope

- **Modern sequential core** — clean-break, fully typed, `__slots__`-based engine;
  generator *and* coroutine (`async def`) processes behind one driver; the full
  SimPy-equivalent resources layer (Resource, PriorityResource, PreemptiveResource,
  Container, Store, PriorityStore, FilterStore).
- **Parallel replications (the flagship)** — first-class Monte Carlo / experiment
  API running N independent simulations across cores, with automatic backend
  selection: free-threaded `ThreadPoolExecutor` on 3.14t,
  `InterpreterPoolExecutor` (PEP 734) or `ProcessPoolExecutor` on GIL builds.
- **Reproducible randomness** — a master-seed tree deriving statistically
  independent per-(config, replication) streams; identical results across
  backends, worker counts, and builds for deterministic models.
- **Single-run conservative PDES** — sharded execution of one large model using
  barrier safe-window (YAWNS-style) synchronization with model-provided lookahead;
  ships with `pdes.analyze()` so users can estimate achievable speedup *before*
  investing in partitioning.
- **In-run compute offload** — `yield sim.offload(fn, ...)` for CPU-heavy event
  handlers, with a deterministic completion-slot mode by default.
- **Real-time mode** — wall-clock-synchronized stepping for
  hardware-in-the-loop use.
- **Structured tracing** — canonical event logs powering both debugging and the
  trace-equivalence test strategy.
- **LLM-powered scenario generation (post-1.0)** — a `ScenarioAgent` that
  reads system documents (hardware specifications, operating procedures,
  failure-mode reports) and generates realistic, targeted simulation
  scenarios — parameter sets and fault-injection event sequences — aimed at
  surfacing emergent behavior. The LLM runs at design time only: it emits
  validated, serialized scenario artifacts that simulations replay
  deterministically, and every generated scenario must cite the source
  passage that grounds it.
- **Domain example gallery** — two runnable, CI-tested, end-to-end examples
  (an autonomous ride-hailing fleet; an LLM agentic workflow pipeline) that
  demonstrate every parallelism tier and double as the pre-1.0 API
  dogfooding pass.

### Out of scope (stated to protect users from disappointment)

- **Optimistic / Time Warp synchronization** — rejected permanently: CPython
  cannot snapshot or pickle a live generator frame, so rollback is infeasible.
- **Automatic parallelization of an unpartitioned model** — sharding is an
  explicit modeling decision; llmsim provides the tools and the honesty, not magic.
- **SimPy 3 API compatibility** — clean break; migration guide instead.
- **Python < 3.14** — the library exists to exploit 3.14's concurrency features.
- **Interpreter-backed PDES for 1.0** — subinterpreters cannot share thread-mode
  mailboxes or live `Sim`s; this needs its own post-1.0 design.
- **Distributed (multi-machine) simulation** — 1.0 targets single multicore
  machines (8–32 cores).
- **A web application / GUI** — llmsim is a library; visualization and dashboards
  are downstream concerns for other tools or future projects.
- **LLM calls inside a running simulation** — rejected permanently: an LLM in
  the event loop would break determinism (principle 2) and add network I/O to
  the hot path. LLM-powered scenario generation happens strictly at design
  time, behind the artifact boundary.

## Guiding principles

1. **Share-nothing by construction.** A `Sim` and every object attached to it
   belongs to exactly one thread at a time. Cross-`Sim` interaction happens only
   through `llmsim.parallel` channels — the only locked structures in the library.
   Zero locks in the sequential hot path, on every build.
2. **Determinism is a correctness requirement, not a feature.** Same
   (master seed, config, replication) → same RNG stream and same deterministic
   event ordering on any backend, any worker count, any build. A parallel result
   that differs from the sequential reference is the worst possible bug class
   (scientific validity); every parallel feature ships with a
   same-seed-same-result test, and PDES ships bitwise trace-equivalence tests.
3. **Honest performance claims only.** Every speedup number is measured, not
   promised; docs lead with a "Which parallelism do I need?" decision tree;
   known slowdown regimes (low lookahead, GIL-build PDES, non-overlapping
   offloads) are documented up front, and the library warns at runtime where
   it can detect them.
4. **The fast path is the easy path.** Parallel replications — the 80% use
   case — must work with a module-level factory function and one `Experiment`
   call. Complexity (sharding, lookahead, offload) is opt-in and clearly priced.
5. **Clean break, familiar spirit.** Drop the Python-2-era baggage
   (`BoundClass`, `StopProcess`, `_compat`) but preserve the generator process
   model, resource semantics, and 15 years of DES behavioral wisdom — validated
   by porting SimPy 3's ~150-test behavioral suite as the Phase 1 gate.
6. **Typed and modern throughout.** Generic `Event[T]`, full static typing under
   mypy and pyright strict, PEP 649 deferred annotations, `__slots__` everywhere
   in the hot path.
7. **Small, verifiable steps.** Every roadmap step is independently shippable,
   has explicit exit criteria, and lands with tests and benchmarks — performance
   regression gates in CI from Phase 0 onward.
