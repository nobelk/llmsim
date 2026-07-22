# Requirements — Phase 5: Domain example gallery

## Context

This spec covers **all of Phase 5** (steps 5.1–5.5) from `specs/roadmap.md`: two
runnable, CI-tested, end-to-end examples — an autonomous ride-hailing fleet and
an LLM agentic-workflow pipeline — that exercise every parallelism tier the
engine ships (Phase 2 replications, Phase 3 sharded PDES, Phase 4 offload) and
double as the final API dogfooding pass before the 1.0 freeze. Per the roadmap,
**step 4.5 (1.0 API freeze) gates on this phase**: both examples must be green
and the API-friction list resolved or waived before 1.0 is tagged. The examples
live in `examples/`, run in CI on the 3.14 and 3.14t builds, and each gets a
worked docs page. They consume only the existing public API
(`specs/mission.md` §Audience: "the fast path is the easy path") and must not
regress the stdlib-only, determinism, or thread-ownership constraints in
`specs/tech-stack.md`.

## Scope

### In

- **5.1 Ride-hailing core model** (`examples/ride_hailing/`): a robotaxi fleet
  serving Poisson trip requests over a **discrete zone graph** (see Decisions):
  - Vehicle processes with the full lifecycle — idle → pickup → drive →
    drop-off → reposition → recharge — as generator processes on one `Sim`.
  - Charging stations modeled as `Resource`s (finite capacity); vehicle
    state-of-charge tracked per vehicle and depleted by travel.
  - Idle-fleet dispatch via `FilterStore` holding all idle vehicles. The
    candidate set for a request is **not** restricted to the request's origin
    zone: the dispatcher `get`s the vehicle a policy selects from idle vehicles
    across zones, ranked by inter-zone travel time to the request origin.
  - **Pluggable dispatch policies** behind one protocol: `closest_available`
    (nearest idle vehicle by inter-zone travel time) and `power_of_d` (sample d
    idle candidates via `sim.rng`, pick the nearest). Ties are broken
    deterministically by ascending vehicle id, never by store/completion order.
  - Poisson trip arrivals; requests abandon if no vehicle is assigned within a
    configurable patience window.
  - KPI collection: rider wait time, vehicle utilization, abandonment rate.
  - A deterministic same-seed-same-result test and a module-level factory
    function suitable for `Experiment` submission.
- **5.2 Ride-hailing parallelism showcases**:
  - (a) Fleet-sizing Monte Carlo study via `Experiment` — confidence intervals
    over (fleet size × demand) configs (Phase 2 showcase).
  - (b) Zone-sharded `ShardedSim` variant: one shard per zone group, using the
    **minimum inter-zone travel time as channel lookahead**, with a bitwise
    trace-equivalence test against the sequential model (Phase 3 showcase). To
    keep the sharded and sequential models identical: a request is **owned by
    its origin-zone shard**, and cross-zone dispatch is a channel message to the
    candidate vehicle's shard resolved with the same deterministic vehicle-id
    tie-break, so cross-shard assignment cannot reorder against local events.
  - Docs page with measured scaling / CI curves.
- **5.3 Agentic-workflow core model** (`examples/agentic_workflow/`): a
  multi-agent task pipeline (a *simulation of* an LLM-serving system, never a
  real LLM call):
  - Tasks arrive at an orchestrator; agent processes alternate **think** steps
    (inference requests queued at shared LLM-server `Resource`s with
    token-length-dependent service times and deterministic batching) and
    **act** steps (tool calls with stochastic latency, failures, and bounded
    retries).
  - KPIs: end-to-end task latency, queue depth, cost per task.
  - A deterministic same-seed-same-result test and a module-level factory.
- **5.4 Agentic parallelism showcases**:
  - (a) Capacity-planning sweep via `Experiment` — (server count × batch size ×
    agent concurrency).
  - (b) `sim.offload` showcase: a CPU-heavy scoring/routing policy evaluated on
    the worker pool in **strict mode** (default), with a trace-equivalence test
    (Phase 4 showcase).
  - Docs page with measured curves.
- **5.5 Gallery integration**: `examples/` wired into CI on both builds as a
  small-parameter smoke-run; a gallery landing page linking each example to the
  "Which parallelism do I need?" decision tree; API-friction findings filed and
  resolved or explicitly waived before the 4.5 freeze review.

### Out

- Real LLM or network calls anywhere in the agentic example — it *models* an
  LLM server; the LLM-in-the-loop path is permanently out of scope
  (`specs/mission.md` §Out of scope) and Phase 6 owns design-time LLM use.
- New engine features or public-API additions. Genuine gaps become
  **API-friction findings** (5.5), not silent local workarounds; any API change
  is a separate spec that this phase's freeze review consumes.
- Any new required runtime dependency. Examples are stdlib-only; `numpy` may be
  used only under an already-existing optional extra and must not be required to
  run or test an example.
- Continuous-coordinate geometry, real map data, GUI/visualization, and
  large-scale “realistic city” calibration — the models are illustrative and
  deterministic, not validated traffic simulators.
- Tagging 1.0 / publishing to PyPI — that is step 4.5, which this phase unblocks
  but does not perform.

## Decisions

- **Discrete zone graph with fixed inter-zone travel times** (user decision).
  Zones are graph nodes; inter-zone travel times are tabulated with a strictly
  positive minimum; intra-zone trips draw from a distribution. Rationale: the
  positive minimum inter-zone time is exactly the channel lookahead the 5.2
  sharded variant needs — this keeps the core model and the PDES showcase
  consistent, which the continuous-coordinate alternative could not (adjacent
  points → ~0 lookahead → no feasible sharding). This is the single geometry
  representation shared by 5.1 and 5.2.
- **Determinism is inherited, not re-litigated** (`specs/tech-stack.md` §7):
  all stochastic draws go through `sim.rng` / the seed tree; no ordering may
  depend on wall-clock or completion order. Every example ships a
  same-seed-same-result test in this PR set (cross-cutting roadmap rule).
- **Executor payloads are references** (`specs/tech-stack.md` §5): each example
  exposes a module-level, importable factory `(seed_spec, config) → results` so
  the same code path runs on the thread, interpreter, and process backends;
  `Experiment` studies submit that factory, never live `Sim` objects.
- **Dispatch/scoring policies are pluggable** behind a small protocol so 5.1’s
  `closest_available`/`power_of_d` and 5.4’s offloaded scoring policy share one
  seam; policy selection is part of the config, so it flows through the seed
  tree deterministically.
- **`sim.offload` runs in strict mode** for 5.4 (deterministic completion
  slots) so the offloaded scoring policy is trace-equivalent to computing it
  inline (`specs/roadmap.md` 4.1).
- **Public-API only**: examples consume the Phase 1–4 surface already exported
  from `llmsim/__init__.py` (`Sim`, `Resource`, `FilterStore`, `Experiment`,
  `ShardedSim`, `OffloadPool`/`sim.offload`, `SeedTree`, …). No engine edits.
