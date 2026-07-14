# Tracing and determinism

Determinism is a **correctness requirement** in llmsim, not a convenience:
the same `(master seed, config, replication)` produces identical results on any
backend, worker count, or build. A parallel result that differs from the
sequential reference is the worst bug class the project recognizes. The trace
is how that guarantee is made observable and testable.

## The determinism contract

- No ordering ever depends on completion order or wall-clock time.
- Randomness derives from an explicit seed through a
  [`SeedTree`][llmsim.rand.streams.SeedTree], so every process, replication,
  and shard draws from a stream fixed by its **path**, never by scheduling.
- Every parallel capability ships a *same-seed-same-result* test against the
  sequential oracle in the same change.

See [Randomness](../reference/randomness.md) for the seed-derivation API.

## Recording a trace

[`trace(sim)`][llmsim.trace.trace] attaches a
[`Tracer`][llmsim.trace.Tracer] that records a canonical
[`TraceRecord`][llmsim.trace.TraceRecord] for every processed event:

```python
from llmsim import trace

sim = llmsim.Sim(seed=0)
tracer = trace.trace(sim)
# ...build and run the model...
sim.run(until=100.0)

records = tracer.records         # the deterministic event sequence
```

Because the record payload is *canonical* (order-independent, value-based),
two runs that are supposed to be equivalent produce **byte-identical** traces —
which is exactly the equality the PDES, replication, and offload test suites
assert. Call [`disable_trace(sim)`][llmsim.trace.disable_trace] to detach.

## Why this matters for parallelism

Every parallel backend in llmsim is validated by comparing its trace to the
single-thread reference:

- **Replications** — each replication is its own `Sim`; the study's result set
  is keyed by `(config, replication)`, never by which worker finished first.
- **PDES sharding** — a sharded run's merged trace is asserted **bitwise-equal**
  to the sequential run of the same model, at every shard count, including a
  jittered concurrency soak.
- **Compute offload** — in strict mode a payload's result is delivered at a
  simulated completion slot (`now + delay`), so the trace is identical whether
  the payload took 1 ms or 1 s on the wall clock.

This is why llmsim rejects optimistic (Time Warp) synchronization outright and
why executor work is always submitted as `(importable callable, seed, config)`
rather than live objects: both choices exist to keep the trace reproducible.
