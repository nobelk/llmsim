# Validation — Phase 1: Sequential core

## Success criteria

The acceptance gate is the roadmap's Phase 1 exit-criteria bundle:

1. **Ported SimPy 3 behavioral suite green.** The ~150-test suite (Group 10)
   passes on both 3.14 and 3.14t, with every deliberate divergence from SimPy 3
   annotated in the test.
2. **Perf gate: ≥1.2× event throughput vs SimPy 3 on 3.14.** The three canonical
   models on llmsim (Group 11) beat the committed Phase 0 SimPy 3 baselines by
   ≥1.2× event throughput, enforced as a pytest-benchmark regression threshold
   in CI.
3. **Determinism: same-seed-same-result.** For each canonical model, a fixed
   `(seed, config)` produces an identical event log / result on repeated runs
   and across 3.14 and 3.14t builds.
4. **Zero functional regressions on 3.14t.** The full test suite is green on the
   free-threaded build, including under `PYTHON_GIL=0` and `PYTHON_GIL=1`. The
   required exit gates are **3.14 and 3.14t only**; `3.15-dev` runs as a
   non-blocking canary (per tech-stack.md), so dev-interpreter churn cannot
   block Phase 1.
5. **Types clean.** `mypy --strict` and `pyright` strict both pass on the public
   API and internals; `ruff check` and `ruff format --check` pass.

## Checklist

- [ ] `core/events.py`: `Event[T]` lifecycle, callback ordering, double-trigger
      guard, and `__await__`-yields-self-once tests pass.
- [ ] `core/sim.py`: heapq ordering with `eid` tie-break, `peek`/`step`,
      `run(until=time|event|None)`, and `EmptySchedule` tests pass.
- [ ] `core/process.py`: generator, coroutine, and mixed-process runs produce
      identical event logs through the one unified driver; interrupt delivery
      and return-value propagation tested. **White-box:** assert `Process` uses a
      single `.send()`/`.throw()` resume/error-resume implementation for both
      generators and coroutines — no separate driver loop or coroutine adapter
      path (guards the unified-driver key decision against silent drift).
- [ ] `core/conditions.py`: `AllOf`/`AnyOf`, `&`/`|` sugar, and multi-failure
      `ExceptionGroup` aggregation tested.
- [ ] `sim.rng`: same-seed draw-sequence equality test passes (sequential
      same-seed-same-result baseline).
- [ ] Debug mode: cross-thread `schedule()` raises with a thread-naming error
      under `Sim(debug=True)` / `LLMSIM_DEBUG=1`; disabled mode adds no overhead.
- [ ] Resources: capacity, FIFO/priority ordering, preemption-wakes-preempted,
      and context-manager release (normal + error exit) tested for `Resource`,
      `PriorityResource`, `PreemptiveResource`.
- [ ] Resources/stores stale-waiter cleanup: a blocked `request`/`get`/`put`
      interrupted or abandoned **before it triggers** is removed from the queue —
      asserting no leaked capacity/items, no duplicate grant to the gone waiter,
      and progress for the next eligible waiter (interrupts are in Phase 1 scope,
      so Groups 7/8 must handle this without waiting for the suite port).
- [ ] Containers/Stores: over/underflow blocking, `Store`/`PriorityStore`
      ordering, and `FilterStore` predicate matching + blocked-get fairness
      tested.
- [ ] `src/llmsim/__init__.py`: import-surface test confirms the documented
      public names resolve; `__all__` matches.
- [ ] `trace.py`: deterministic, stable trace of a fixed model; disabled tracing
      emits no records and adds no measurable overhead.
- [ ] `tests/behavioral/`: full ~150-test SimPy 3 suite ported and green on 3.14
      and 3.14t.
- [ ] `benchmarks/`: three canonical models on llmsim; CI regression thresholds
      assert ≥1.2× vs the Phase 0 SimPy 3 baselines on 3.14.
- [ ] `docs/perf-notes.md` (or benchmarks README): measured single-thread
      numbers recorded, including any regime where llmsim does not lead.
- [ ] CI green across the full `{3.14, 3.14t, 3.15-dev} × {Linux, macOS}` matrix
      plus the `PYTHON_GIL=0/1` axis on 3.14t.

## Done when

The ported SimPy 3 behavioral suite is green on 3.14 and 3.14t, the CI benchmark
gate confirms ≥1.2× event throughput vs the SimPy 3 baseline on 3.14, the
same-seed determinism tests pass, and all lint/type/format gates are clean across
the full CI matrix.
