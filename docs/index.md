# llmsim

Parallel discrete-event simulation for Python 3.14+.

llmsim pairs a fully typed, `__slots__`-based sequential simulation core with
parallelism that comes from a **share-nothing architecture** — independent work
across cores, never locks on the sequential engine.

!!! note "Project status"
    llmsim is in early development. Phase 0 (scaffolding) establishes the
    package, quality gates, CI matrix, and SimPy 3 performance baselines; the
    simulation engine itself lands in later phases. See the
    [roadmap](https://github.com/nobelk/llmsim/blob/main/specs/roadmap.md).

## Where to start

- **[Which parallelism do I need?](parallelism-decision-tree.md)** — the
  decision tree for choosing between replication, offload, and PDES.
- **[Design document](part-deux.md)** — the full design everything derives from.
- **[SimPy 3 comparison](simpy-comparison.md)** — how llmsim relates to SimPy 3.
