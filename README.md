# llmsim

A parallel discrete-event simulation (DES) library for Python 3.14+.

> **Status: planning.** The design and roadmap are complete (see
> [Project documents](#project-documents)); implementation has not started.
> All code samples below show the planned API.

## Overview

llmsim keeps the proven generator-as-process model popularized by SimPy and
rebuilds everything else for the Python 3.14 concurrency era: a clean-break,
fully typed, `__slots__`-based sequential core, plus parallelism that comes
from architecture — share-nothing simulations with explicit, narrow
communication points — never from locks bolted onto a sequential engine.

It offers four tiers of parallelism, in order of how often users need them:

1. **Parallel replications (the flagship).** Run N independent Monte Carlo
   replications across cores with `Experiment.run(backend="auto")` —
   free-threaded threads on `3.14t`, subinterpreters (PEP 734) or processes on
   GIL builds. Expected ~6–7× throughput on 8 cores.
2. **Single-run conservative PDES.** Partition one large model into shards
   (one event loop per core) synchronized by a barrier safe-window protocol
   with model-provided lookahead. Model-dependent 2–8× speedup; honest tooling
   (`pdes.analyze()`) estimates your ceiling before you invest.
3. **In-run compute offload.** `yield sim.offload(fn, ...)` fans CPU-heavy
   event handlers out to a worker pool with deterministic completion slots.
4. **Reproducibility throughout.** A master-seed tree gives every
   (config, replication) pair an independent RNG stream; the same seeds
   produce the same results on any backend, any worker count, any build.

```python
import llmsim

def customer(sim: llmsim.Sim, bank: llmsim.Resource, service_time: float):
    with bank.request() as req:
        yield req
        yield sim.delay(service_time)

sim = llmsim.Sim()
bank = llmsim.Resource(sim, capacity=2)
sim.spawn(customer, bank, service_time=5.0)
sim.run(until=100.0)
```

Explicit non-goals: no optimistic/Time Warp synchronization (CPython cannot
snapshot a live generator frame), no automatic parallelization of
unpartitioned models, no SimPy 3 API compatibility (a migration guide ships
instead), no Python < 3.14.

## Architecture

A `Sim` and everything attached to it belong to exactly one thread; the only
locked structures in the library are the `llmsim.parallel` channels between
them. The sequential hot path has zero locks on every build.

```
                     +----------------- your model ------------------+
                     |  generator and async-def processes, resources |
                     +-----------------------+------------------------+
                                             | yield / await
+--------------------------------------------v---------------------------------------+
|                        llmsim.core  (one Sim = one thread)                          |
|                                                                                     |
|   Sim: heapq event loop (time, priority, eid)   Event[T] / Timeout / Condition      |
|   Process driver (send/throw)                   resources: Resource, Container,     |
|   rand: per-Sim seeded RNG streams                         Store variants           |
|   trace: structured event log                   rt: wall-clock sync mode            |
+------------+---------------------------+----------------------------+---------------+
             | share-nothing: cross-Sim traffic only via locked channels
             |                           |                            |
+------------v-----------+  +------------v------------+  +------------v--------------+
|  parallel.replicate    |  |  parallel.pdes          |  |  parallel.offload         |
|  Experiment: N         |  |  ShardedSim: one Sim    |  |  sim.offload(fn):         |
|  independent Sims,     |  |  per shard; lookahead   |  |  CPU-heavy handlers on    |
|  seed tree, results    |  |  channels; barrier      |  |  a worker pool with       |
|  keyed by (config,     |  |  safe-window sync;      |  |  deterministic            |
|  replication)          |  |  deterministic delivery |  |  completion slots         |
+------------+-----------+  +------------+------------+  +------------+--------------+
             |                           |                            |
+------------v---------------------------v----------------------------v--------------+
|                       parallel.backends  (backend="auto")                          |
|   threads (free-threaded 3.14t)  |  subinterpreters (PEP 734)  |  processes        |
+-------------------------------------------------------------------------------------+
```

## Project documents

- [`specs/mission.md`](specs/mission.md) — vision, audience, scope, guiding
  principles.
- [`specs/tech-stack.md`](specs/tech-stack.md) — runtime targets, tooling, CI
  matrix, normative technical constraints.
- [`specs/roadmap.md`](specs/roadmap.md) — Phases 0–5 in small, independently
  shippable steps (scaffolding → sequential core → parallel replications →
  conservative PDES → offload/RT/1.0 → domain example gallery, including an
  autonomous ride-hailing fleet and an LLM agentic-workflow example).
- [`docs/part-deux.md`](docs/part-deux.md) — the full design document the
  specs derive from.

## References

Discrete-event simulation and PDES literature underpinning the design:

- R. M. Fujimoto, [*Parallel Discrete Event Simulation*](https://dl.acm.org/doi/10.1145/84537.84545),
  Communications of the ACM 33(10), 1990 — the field's canonical survey.
- R. M. Fujimoto, [*Parallel and Distributed Simulation Systems*](https://www.amazon.com/Parallel-Distributed-Simulation-Systems-Fujimoto/dp/0471183830),
  Wiley, 2000 — conservative vs optimistic synchronization, lookahead.
- K. M. Chandy and J. Misra, *Distributed Simulation: A Case Study in Design
  and Verification of Distributed Programs*, IEEE TSE, 1979; R. E. Bryant,
  *Simulation of Packet Communication Architecture Computer Systems*, MIT,
  1977 — the conservative (null-message) family llmsim's synchronizer
  descends from.
- D. R. Jefferson, *Virtual Time*, ACM TOPLAS 7(3), 1985 — optimistic
  synchronization (Time Warp); evaluated and rejected for llmsim because
  generator frames cannot be checkpointed.
- D. M. Nicol, *The Cost of Conservative Synchronization in Parallel Discrete
  Event Simulations*, JACM 40(2), 1993 — synchronous-window (YAWNS-style)
  protocols, the variant llmsim implements.
- J. Banks, J. S. Carson II, B. L. Nelson, D. M. Nicol, *Discrete-Event System
  Simulation*, Pearson — foundational DES textbook.
- A. M. Law, *Simulation Modeling and Analysis*, McGraw-Hill — output
  analysis and experiment design for stochastic studies.
- [SimPy](https://simpy.readthedocs.io/) — the generator-based DES framework
  whose process model llmsim inherits in spirit.
- [Python free-threading HOWTO](https://docs.python.org/3/howto/free-threading-python.html),
  [PEP 703](https://peps.python.org/pep-0703/)/[PEP 779](https://peps.python.org/pep-0779/)
  (free-threaded CPython), and
  [PEP 734](https://peps.python.org/pep-0734/) (`concurrent.interpreters`) —
  the Python 3.14 concurrency features the parallel tiers build on.

## License

[MIT](LICENSE)
