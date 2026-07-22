# Plan — Phase 5: Domain example gallery

Task groups are ordered by dependency; each is sized to land as its own
commit/PR. Group 1 is the smallest mergeable slice (a runnable, tested core
ride-hailing model). Later groups add the parallelism showcases and integration.
Every group that introduces a stochastic or parallel capability ships its
same-seed test (and, where a parallel tier is showcased, its
trace-equivalence/curve artifacts) **in the same PR**.

## 1. Ride-hailing core model (roadmap 5.1)

- Create `examples/ride_hailing/` as an importable package (`__init__.py`,
  `model.py`, `policies.py`, `kpis.py`) plus a `README.md`.
- `model.py`: discrete **zone graph** (nodes + tabulated inter-zone travel
  times with a strictly positive minimum; intra-zone trip-time distribution);
  vehicle generator process (idle → pickup → drive → drop-off → reposition →
  recharge) with per-vehicle state-of-charge; charging stations as `Resource`s;
  idle fleet held in a `FilterStore`; Poisson request generator with a patience
  window driving abandonment.
- `policies.py`: a `DispatchPolicy` protocol with `closest_available` and
  `power_of_d(d)` implementations; all candidate sampling via `sim.rng`.
- `kpis.py`: accumulate rider wait time, vehicle utilization, abandonment rate
  into a small typed result dataclass.
- Module-level factory `run_ride_hailing(seed_spec, config) -> KPIs` (importable,
  no live objects captured) so Group 3 can submit it to `Experiment`.
- Tests: behavioral tests (a request is served, an over-capacity request
  abandons, recharge blocks on a full station) **and** a same-seed-same-result
  test asserting identical KPIs across two runs with the same seed.

## 2. Agentic-workflow core model (roadmap 5.3)

- Create `examples/agentic_workflow/` (`__init__.py`, `model.py`, `policies.py`,
  `kpis.py`, `README.md`) — parallel structure to Group 1.
- `model.py`: orchestrator receiving Poisson task arrivals; agent generator
  processes alternating **think** steps (inference requests at shared
  LLM-server `Resource`s with token-length-dependent service times and
  deterministic batching) and **act** steps (tool calls with stochastic
  latency, failures, and bounded retries). No real LLM/network — service times
  are drawn from `sim.rng`.
- `kpis.py`: end-to-end task latency, queue depth over time, cost per task.
- Module-level factory `run_agentic_workflow(seed_spec, config) -> KPIs`.
- Tests: behavioral (a task completes; a failing tool call retries then
  surfaces; batching groups concurrent inference requests) **and** a
  same-seed-same-result test.

## 3. Ride-hailing fleet-sizing Monte Carlo (roadmap 5.2a)

- `examples/ride_hailing/study_fleet_sizing.py`: build an `Experiment` over
  (fleet size × demand) configs, run replications via `run_replications`,
  compute per-config confidence intervals on the KPIs from `ReplicationResult`s.
- Test: results are keyed by (config, replication) and identical across two
  backends for a fixed master seed (reproducibility guarantee).

## 4. Zone-sharded ride-hailing PDES variant (roadmap 5.2b)

- `examples/ride_hailing/sharded.py`: a `ShardedSim` topology with one shard per
  zone group; cross-zone vehicle handoffs cross typed channels whose lookahead
  is the **minimum inter-zone travel time**; intra-shard logic reuses Group 1's
  model.
- Test: **bitwise trace-equivalence** of the sharded run vs the sequential
  Group 1 run at 1/2/4 shards for a fixed seed (Phase 3 guarantee).
- Note in the docs page the lookahead → slowdown regime (honest-performance
  rule) and, per roadmap 3.7/3-exit, treat any absolute speedup figure as
  recorded-not-blocking on interpreters that anti-scale.

## 5. Agentic capacity sweep + offload showcase (roadmap 5.4)

- `examples/agentic_workflow/study_capacity.py`: `Experiment` sweep over
  (server count × batch size × agent concurrency) with per-config CIs.
- `examples/agentic_workflow/offload.py`: a CPU-heavy scoring/routing policy
  evaluated via `sim.offload(...)` in **strict mode** on the worker pool.
- Tests: backend-reproducibility for the sweep; **trace-equivalence** of the
  offloaded-policy run vs the same policy computed inline (strict-mode
  determinism).

## 6. Docs pages + measured curves (roadmap 5.2/5.4 docs)

- One worked mkdocs page per example under `docs/`, each linking to the "Which
  parallelism do I need?" decision tree; embed a measured curve for **all four**
  showcases — fleet-sizing (5.2a), sharded ride-hailing (5.2b), agentic
  capacity sweep (5.4a), and offload (5.4b) — each with its honest slowdown
  note (lookahead → 0 for the shard curve; max-vs-sum ceiling for offload).
- Regenerate curves from the study/showcase scripts (small committed
  parameters) so the numbers are reproducible; `mkdocs build --strict` stays
  green (4.4 gate).

## 7. Gallery CI integration + friction review (roadmap 5.5)

- Add a CI smoke-run job that executes every example with small parameters on
  both 3.14 and 3.14t (fast enough for per-PR CI).
- Gallery landing page linking each example to the decision tree.
- Collect the API-friction findings surfaced while building Groups 1–6 into a
  short list; resolve or explicitly waive each, and hand the list to the 4.5
  freeze review. Any finding needing an engine/API change is filed as its own
  follow-up spec, not fixed inline here.
