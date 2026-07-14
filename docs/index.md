# llmsim

Parallel discrete-event simulation for Python 3.14+.

llmsim pairs a fully typed, `__slots__`-based sequential simulation core with
parallelism that comes from a **share-nothing architecture** — independent work
across cores, never locks on the sequential engine.

!!! note "Project status"
    llmsim is approaching its 1.0 API freeze. The sequential core, parallel
    replications, single-run PDES sharding, compute offload, and real-time mode
    are implemented and gated by same-seed determinism tests; the 1.0 tag and
    PyPI publish follow the Phase 5 example gallery. See the
    [roadmap](https://github.com/nobelk/llmsim/blob/main/specs/roadmap.md).

## Install

llmsim is not on PyPI yet (the 1.0 publish is gated on Phase 5). Install the
current source directly with `pip`:

```bash
pip install git+https://github.com/nobelk/llmsim
```

Once 1.0 is published, installation is simply `pip install llmsim`. Zero required
runtime dependencies; Python 3.14+ on both GIL and free-threaded builds. See
[Getting started](guide/getting-started.md) for your first model.

## Where to start

- **[Getting started](guide/getting-started.md)** — install and run your first
  model in a dozen lines.
- **[Core concepts](guide/core-concepts.md)** — the `Sim`, events, processes,
  and conditions.
- **[Which parallelism do I need?](parallelism-decision-tree.md)** — the
  decision tree for choosing between replications, offload, and PDES.
- **[Migrating from SimPy 3](migration-from-simpy.md)** — the concept-by-concept
  porting guide, with all three canonical models worked side by side.

## Reference and design

- **[API reference](reference/core.md)** — every public symbol, generated from
  docstrings.
- **[Performance](perf-notes.md)** — measured scaling curves with their slowdown
  regimes.
- **[Deprecation policy](deprecation-policy.md)** — what the 1.x series
  promises.
- **[Design document](part-deux.md)** — the full design everything derives from.
- **[SimPy 3 comparison](simpy-comparison.md)** — how llmsim relates to SimPy 3.
