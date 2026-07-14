# Compute offload

Offload runs a **CPU-heavy payload** on a worker pool from inside a running
model — a routing policy, an ML scoring pass, a solver — without breaking
determinism. Unlike replications and sharding, offload keeps the single
sequential timeline; it just moves an expensive computation off the event-loop
thread.

Reach for this when one process step is compute-bound and the rest of the model
is not. See [Which parallelism do I need?](../parallelism-decision-tree.md).

## The completion slot

The mechanism is the **completion slot**. In strict mode (the default), the
result is delivered at the simulated time `now + delay` — a pure function of
model state, exactly like PDES lookahead — never at a time derived from how long
the computation actually took. If the payload has not finished when the loop
reaches the slot, the loop blocks the wall clock there; the simulated event
order is identical either way, so a strict-mode trace is **bitwise-equal** to
the inline sequential reference.

```python
from llmsim import OffloadPool

# score() must be an importable module-level callable, not a closure.
from policies import score

def vehicle(sim, state):
    # runs score(state) on the pool; result arrives at now + 2.0
    ranking = yield sim.offload(score, state, delay=2.0)
    # ...act on ranking...

sim = llmsim.Sim(seed=0)
with OffloadPool(sim, backend="processes") as pool:
    sim.spawn(vehicle, initial_state)
    sim.run(until=100.0)
```

[`OffloadPool`][llmsim.parallel.offload.OffloadPool] attaches to the `Sim`;
[`sim.offload(fn, *args, delay=..., strict=True, **kwargs)`][llmsim.core.sim.Sim.offload]
submits work and returns an [`OffloadEvent`][llmsim.parallel.offload.OffloadEvent]
you `yield` like any other event.

## Strict vs non-strict

- **`strict=True`** (default) — deterministic completion slot; trace-equivalent
  to inline. Always use this unless you have a specific reason not to.
- **`strict=False`** — the result is delivered as soon as it is observed between
  steps (no earlier than `now + delay`). Delivery order then depends on
  wall-clock completion, so debug mode flags every such call with
  [`NonStrictOffloadWarning`][llmsim.parallel.offload.NonStrictOffloadWarning].

## Payload rules and the speedup ceiling

- **Importable callables only.** Payloads are `(callable, args)` — never live
  model objects. On transport backends (interpreters/processes) arguments are
  pickle-preflighted; on the thread backend they pass by reference, so a payload
  argument must not be `Sim`-owned mutable state.
- **The ceiling is overlap in *simulated* time**, not worker count. A model that
  offloads serially (each submitted after the last resolves) has a ceiling of
  1×; the win comes only from payloads that overlap in simulated time.
- **Payloads must be finite.** `Future.cancel()` cannot stop running work on any
  executor, so a payload that never returns blocks its strict slot (and
  `OffloadPool.close`) forever. There is no offload timeout in 1.0.

The measured max-vs-sum ceiling and its slowdown regimes are in the
[Performance overview](../perf-notes.md#phase-4-compute-offload).
