# Requirements — Phase 1: Sequential core

## Context

Phase 0 delivered the scaffolding (package skeleton, quality gates, CI matrix,
SimPy 3 benchmark baselines). Phase 1 builds the **sequential simulation
engine** on top of it: a clean-break, fully typed, `__slots__`-based core that
keeps SimPy's generator-as-process model (mission principle 5, "clean break,
familiar spirit") while dropping the Python-2-era baggage. This core is the
foundation every later parallel capability rests on — the share-nothing
parallelism of Phases 2–4 comes from running many copies of *this* engine, one
per thread, never from locking it. Correctness here is therefore load-bearing:
Phase 3's trace-equivalence tests measure sharded runs against the sequential
reference this phase defines.

The phase is validated the way the mission mandates — by porting SimPy 3's
~150-test behavioral suite as the acceptance gate — and must beat SimPy 3 on a
single thread to justify the clean break.

## Scope

### In

- **1.1 Event system** — `core/events.py`: generic `__slots__`-based `Event[T]`
  with a pending sentinel, callback list, and ok/defused state; `Timeout`;
  events are awaitable (`__await__` yields `self` exactly once).
- **1.2 Event loop** — `core/sim.py`: `Sim` with a `heapq` schedule keyed by
  `(time, priority, eid, event)`; `sim.now`, `sim.delay()`, `run(until=...)`,
  plus `step()`/`peek()`; `core/errors.py` with `Interrupt`, `SimulationError`,
  `EmptySchedule`.
- **1.3 Process driver** — `core/process.py`: a **single unified driver** that
  advances both generator processes and `async def` coroutine processes through
  one `send()`/`throw()` step function; `sim.spawn()`; interrupt semantics.
- **1.4 Condition composition** — `Condition`, `AllOf`, `AnyOf`; multiple
  simultaneous failures aggregate into an `ExceptionGroup`.
- **1.5 Per-Sim RNG** — `sim.rng: random.Random` seeded via the `Sim`
  constructor; this is the hook the Phase 2 seed tree plugs into (no seed-tree
  logic yet).
- **1.6 Thread-ownership debug mode** — `Sim(debug=True)` / `LLMSIM_DEBUG=1`
  asserts owning-thread identity (`threading.get_ident()`) on every `schedule()`.
- **1.7 Resources: base + Resource** — `resources/base.py` request/release
  protocol (context managers, trigger chains); `Resource`, `PriorityResource`,
  `PreemptiveResource`.
- **1.8 Resources: Container + Stores** — `Container`; `Store`, `PriorityStore`,
  `FilterStore`.
- **1.9 Structured tracing** — `trace.py`: canonical event logs (consumed by
  Phase 3 equivalence tests; cheap to add now, opt-in so it stays off the
  zero-overhead default path).
- **1.10 SimPy 3 behavioral suite port** — port the ~150-test suite to the new
  API as the acceptance gate (interrupt edge cases, condition composition,
  preemption, store filtering).
- **1.11 Canonical models on llmsim + perf gate** — reimplement the three
  benchmark models (M/M/1 queue, machine shop, 100×100 grid conveyor) on
  llmsim; wire regression thresholds into CI against the Phase 0 SimPy 3
  baselines.
- **Public API surface** — `src/llmsim/__init__.py` re-exports the Phase 1
  public symbols with an explicit `__all__`: `Sim`, `Event`, `Timeout`,
  `Process`, `Interrupt`, `SimulationError`, `EmptySchedule`, the condition
  constructors (`Condition`, `AllOf`, `AnyOf`), and the resource types
  (`Resource`, `PriorityResource`, `PreemptiveResource`, `Container`, `Store`,
  `PriorityStore`, `FilterStore`). This is the import contract users depend on
  and the concrete instance of the "typed public API" decision below.

### Out

- Any parallelism — seed **trees**, execution backends, `Experiment`, PDES,
  offload, real-time mode (Phases 2–4). Phase 1 provides only the single-`Sim`
  `sim.rng` hook, not the seed tree.
- Optimistic / Time Warp synchronization (rejected permanently — generator
  frames cannot be snapshotted).
- `numpy` RNG adapter and any optional extra (`llmsim[numpy]`, `llmsim[llm]`).
- Docs-site build (Phase 4.4) — Phase 1 ships docstrings and the perf-regime
  note required by the "docs honesty" cross-cutting rule, not the mkdocs site.
- Python < 3.14 compatibility shims.

## Decisions

- **Unified driver (key decision).** One step function drives both generators
  and coroutines via `.send()`/`.throw()`; `Event.__await__` yields `self` once
  so `await event` and `yield event` resolve through the same scheduling path.
  This is the single code path CLAUDE.md's architecture prescribes ("one driver
  runs both"); the two-driver and coroutine-first alternatives were rejected to
  avoid DRY drift and per-event adapter overhead on the hot path.
- **Behavioral contract is SimPy 3's.** The ~150-test suite port (1.10) is the
  definition of correct; where the design doc and SimPy 3 differ on an edge
  case, the suite port records the deliberate divergence rather than silently
  changing behavior.
- **Determinism by construction (normative).** Event ordering uses the
  `(time, priority, eid)` sort key with a monotonic `eid` tie-breaker; no
  ordering may depend on wall-clock time or insertion-hash order. Same
  (seed, model) → identical run on every 3.14/3.14t build.
- **Hot-path discipline (normative).** `__slots__` on every hot-path class
  (`Event`, `Timeout`, `Process`, `Sim` internals); minimal per-event
  temporaries; zero locks in the sequential path on every build. Tracing (1.9)
  must be free when disabled.
- **Typed public API (normative).** Generic `Event[T]`; every public symbol
  annotated; `mypy --strict` and `pyright` strict both clean; PEP 649 deferred
  annotations.
- **Stdlib-only.** `heapq`, `random`, `threading` (debug-mode identity checks
  only) — no third-party runtime dependency.
