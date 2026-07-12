# Plan — Phase 1: Sequential core

Task groups are ordered by dependency; each is sized to land as its own
commit/PR. Group 1 is the smallest mergeable slice. Every group ships its own
tests in the same PR (project workflow rule); the determinism-sensitive groups
ship a same-seed-same-result test, and Group 11 documents perf/slowdown regimes
in its PR (cross-cutting rules).

## 1. Event system (`core/events.py`, `core/errors.py`)

- Generic `Event[T]` with `__slots__`: pending sentinel, value, `callbacks`
  list, `ok`/`defused` flags; `succeed(value)`, `fail(exception)`,
  `trigger(event)`; idempotency guard (re-triggering a resolved event raises).
- `Event.__await__` yields `self` exactly once, then returns the value — the
  single hook that makes `await event` and `yield event` interchangeable.
- `Timeout(delay, value=...)` subclass.
- `core/errors.py`: `SimulationError` base, `Interrupt`, `EmptySchedule`.
- Tests: event lifecycle, callback firing order, double-trigger guard, await
  protocol yields self once.

## 2. Event loop (`core/sim.py`)

- `Sim` holding a `heapq` of `(time, priority, eid, event)` tuples with a
  monotonic `eid` counter as the deterministic tie-breaker; `sim.now`.
- `sim.delay(delay, value=...)` (returns a `Timeout`), `schedule(event, priority,
  delay)`, `step()` (process one event), `peek()` (next event time),
  `run(until=...)` accepting a time, an event, or `None`.
- Raise `EmptySchedule` when `run()` exhausts the queue before `until`.
- Tests: ordering under equal timestamps (eid tie-break), `peek`/`step`
  semantics, `run(until=time)` vs `run(until=event)`, empty-schedule error.

## 3. Process driver (`core/process.py`)

- `Process` wrapping a generator **or** a coroutine; one `_resume(value)` /
  `_resume_error(exc)` path calling `.send()`/`.throw()` on either object type
  (dispatch on the driver, not on two code paths).
- `sim.spawn(process_fn(...))` accepting both `def ...(): yield` generators and
  `async def` coroutines; process completion resolves its backing `Event`.
- Interrupt: `process.interrupt(cause)` schedules an `Interrupt` to be thrown
  into the target at its next resume.
- Tests: generator process, coroutine process, and a mixed run producing
  identical event logs; interrupt delivery; process return value propagation.

## 4. Condition composition (`core/conditions.py`)

- `Condition` base; `AllOf(*events)` and `AnyOf(*events)` (and the `&` / `|`
  operators on `Event`); result is a value map of the triggered events.
- Failure aggregation: multiple simultaneous member failures surface as a single
  `ExceptionGroup`.
- Tests: `AllOf`/`AnyOf` truth conditions, operator sugar, `ExceptionGroup`
  aggregation on multi-failure.

## 5. Per-Sim RNG (`core/sim.py`)

- `Sim(seed=...)` constructs `sim.rng: random.Random`; documented as the single
  seam the Phase 2 seed tree will inject a derived stream into.
- Test: same seed → identical draw sequence; the same-seed-same-result baseline
  test for the sequential engine.

## 6. Thread-ownership debug mode (`core/sim.py`)

- `Sim(debug=True)` or `LLMSIM_DEBUG=1` records the owning thread ident at
  construction and asserts it on every `schedule()`; a helpful error names the
  violating thread. Zero cost when disabled (guard compiled out of the hot path).
- Tests: cross-thread `schedule()` raises in debug mode; no-op and no overhead
  when disabled.

## 7. Resources: base + Resource (`resources/base.py`, `resources/resource.py`)

- `resources/base.py`: request/release protocol — `Request`/`Release` events,
  context-manager support (`with resource.request() as req: yield req`), and the
  trigger chain that wakes the next waiter on release.
- `Resource` (capacity, FIFO queue), `PriorityResource` (priority queue),
  `PreemptiveResource` (preemption bumps a lower-priority holder via `Interrupt`).
- Stale-waiter cleanup: a blocked `request` interrupted/abandoned before it
  triggers is removed from the wait queue so it cannot later be granted capacity.
- Tests: capacity limits, FIFO vs priority ordering, preemption wakes the
  preempted process, context-manager release on normal and error exit, and
  interrupted-before-trigger request dequeued with no leaked capacity.

## 8. Resources: Container + Stores (`resources/container.py`, `resources/store.py`)

- `Container` (continuous `get`/`put` level with capacity).
- `Store` (FIFO object slots), `PriorityStore` (ordered by item priority),
  `FilterStore` (`get(filter=...)` predicate matching).
- Stale-waiter cleanup: a blocked `get`/`put` interrupted/abandoned before it
  triggers is removed from its queue with no leaked item/level and progress for
  the next eligible waiter.
- Tests: container over/underflow blocking, store ordering, filter matching, the
  fairness of a blocked filtered `get`, and interrupted-before-trigger
  `get`/`put` dequeued cleanly.

## 8b. Public API surface (`src/llmsim/__init__.py`)

- Re-export the Phase 1 public symbols (`Sim`, `Event`, `Timeout`, `Process`,
  `Interrupt`, conditions, resources) with `__all__`; confirm `mypy --strict`
  and `pyright` strict stay clean on the exported surface.
- Test: import-surface test asserting the documented public names resolve.

## 9. Structured tracing (`trace.py`)

- Canonical, opt-in event log: `(time, eid, kind, priority, payload)` records
  emitted through a hookable sink; **off by default** with no hot-path cost when
  disabled. Log format is the one Phase 3 trace-equivalence tests will diff.
- Tests: trace of a fixed model is deterministic and stable across runs; tracing
  disabled adds no records and no measurable overhead.

## 10. SimPy 3 behavioral suite port (`tests/behavioral/`)

- Port the ~150-test SimPy 3 behavioral suite to the llmsim API: interrupt edge
  cases, condition composition, resource preemption, store filtering, process
  return values. Each deliberate divergence from SimPy 3 behavior is annotated
  in the test with a one-line rationale.
- This suite is the phase acceptance gate; it must be green on both 3.14 and
  3.14t.

## 11. Canonical models on llmsim + perf gate (`benchmarks/`)

- Reimplement M/M/1 queue, machine shop, and 100×100 grid conveyor on llmsim,
  mirroring the Phase 0 SimPy 3 implementations.
- Wire pytest-benchmark regression thresholds into CI comparing llmsim against
  the committed Phase 0 SimPy 3 baselines; assert ≥1.2× event throughput on 3.14.
- Ship a short `docs/perf-notes.md` (or benchmarks README section) recording the
  measured single-thread numbers and any regime where llmsim does **not** lead
  (docs-honesty cross-cutting rule).
