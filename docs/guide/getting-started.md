# Getting started

llmsim is a parallel discrete-event simulation (DES) library for Python 3.14+.
Its sequential core follows the SimPy-style *generator-as-process* model; its
parallelism comes from a share-nothing architecture, never from locks on the
engine.

## Install

llmsim has **zero required runtime dependencies** — the engine is stdlib-only.

!!! note "Pre-release install"
    llmsim is approaching its 1.0 release and is **not on PyPI yet** (the publish
    is gated on Phase 5). Until then, install the current source directly with
    `pip`:

    ```bash
    pip install git+https://github.com/nobelk/llmsim
    ```

    Once 1.0 is published, installation is simply `pip install llmsim`.

It targets Python **3.14 and newer**, on both the standard (GIL) and
free-threaded (`3.14t`) builds.

## Your first model

A process is a generator function that receives the `Sim` as its first
argument and `yield`s events. Here is a two-teller bank queue:

```python
import llmsim


def customer(sim, teller, service_time):
    arrived = sim.now
    with teller.request() as slot:      # queue for a free teller
        yield slot                      # ...wait until granted
        waited = sim.now - arrived
        print(f"waited {waited:.1f}, served at {sim.now:.1f}")
        yield sim.delay(service_time)   # hold the teller while served


def arrivals(sim, teller):
    for _ in range(5):
        yield sim.delay(2.0)            # one customer every 2 time units
        sim.spawn(customer, teller, service_time=5.0)


sim = llmsim.Sim(seed=0)
teller = llmsim.Resource(sim, capacity=2)
sim.spawn(arrivals, teller)
sim.run(until=100.0)
```

Three calls carry the model:

- [`sim.spawn(fn, *args, **kwargs)`][llmsim.core.sim.Sim.spawn] starts a
  process; the `Sim` is injected as `fn`'s first argument.
- [`sim.delay(t)`][llmsim.core.sim.Sim.delay] yields a timeout that fires `t`
  time units later.
- [`sim.run(until=...)`][llmsim.core.sim.Sim.run] advances the clock until the
  schedule empties, a time is reached, or a given event fires.

## Determinism

Passing `seed=` makes a run reproducible: the same `(seed, model)` produces an
identical event sequence on every run, build, and backend. This is a
correctness guarantee, not a convenience — see
[Tracing and determinism](tracing.md).

## Where to go next

- [Core concepts](core-concepts.md) — the `Sim`, events, processes, conditions,
  and interrupts in depth.
- [Resources and stores](resources.md) — the shared-capacity primitives.
- [Which parallelism do I need?](../parallelism-decision-tree.md) — choosing
  between replications, sharding, and offload.
- [Migrating from SimPy 3](../migration-from-simpy.md) — a concept-by-concept
  porting guide.
