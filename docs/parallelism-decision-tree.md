# Which parallelism do I need?

This page is the landing point for choosing a parallel execution strategy in
llmsim. It is reserved here in Phase 0; the full decision tree and guidance are
authored in Phase 4 alongside the parallel APIs they describe.

<!-- Placeholder: the decision tree below is filled in during Phase 4 (docs). -->

At a high level, llmsim offers three share-nothing strategies:

- **Replication** — run many independent replications of one model across
  cores. The flagship path; start here when you need confidence intervals over
  stochastic runs.
- **Offload** — hand a CPU-bound computation from a running process to a worker
  pool without breaking determinism.
- **PDES** — shard a single large model across cores with conservative
  (YAWNS-style) synchronization, when one replication is itself too big.

A full "start here → answer these questions → use this API" decision tree will
replace this placeholder in Phase 4.
