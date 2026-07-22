# Roadmap — llmsim

Phases 0–4 follow the delivery plan in `docs/part-deux.md`, broken into small,
independently shippable steps; Phases 5 (domain example gallery) and 6
(LLM-powered scenario generation) extend that plan. Each step is sized to be one feature spec
(`specs/<branch-name>/`) and lands with its own tests; exit criteria are listed
per phase. Steps within a phase are ordered by dependency.

## Phase 0 — Scaffolding

Goal: a repo where every later step lands with lint, types, tests, and
benchmarks enforced from day one.

- [x] **0.1 Package skeleton** — `pyproject.toml` (PEP 621, hatchling,
  `requires-python = ">=3.14"`), `src/llmsim/` layout with empty modules per
  the package map, Apache-2.0 metadata, README stub.
- [x] **0.2 Quality gates** — ruff (lint + format, enforcing PEP 8 per the
  tech stack), mypy strict, pyright
  strict, pytest wiring; pre-commit config; a trivial smoke test proving the
  gates run.
- [x] **0.3 CI matrix** — GitHub Actions: `{3.14, 3.14t, 3.15-dev} ×
  {Linux, macOS}`, plus the `PYTHON_GIL=0/1` axis on 3.14t; all Phase 0.2
  gates enforced per PR.
- [x] **0.4 Benchmark harness** — pytest-benchmark scaffolding; three canonical
  models as *SimPy 3* implementations (M/M/1 queue, machine shop, 100×100 grid
  conveyor); record SimPy 3 baseline numbers per CI machine class.

**Exit criteria:** green CI across the full matrix; SimPy 3 baselines recorded
and stored with the repo.

## Phase 1 — Sequential core

Goal: a clean-break, fully typed engine that beats SimPy 3 on one thread and
passes its ported behavioral suite.

- [x] **1.1 Event system** — `core/events.py`: generic `__slots__`-based
  `Event[T]` (pending sentinel, callbacks, ok/defused), `Timeout`; events are
  awaitable (`__await__` yields self once).
- [x] **1.2 Event loop** — `core/sim.py`: `Sim` with heapq scheduling
  (`(time, priority, eid, event)`), `sim.now`, `sim.delay()`, `run(until=...)`,
  step/peek; `core/errors.py` (`Interrupt`, `SimulationError`, `EmptySchedule`).
- [x] **1.3 Process driver** — `core/process.py`: `Process` driving generators
  *and* coroutines via one `send()`/`throw()` driver; `sim.spawn()`;
  interrupt semantics.
- [x] **1.4 Condition composition** — `Condition`, `AllOf`, `AnyOf`; multiple
  failures aggregate into `ExceptionGroup`.
- [x] **1.5 Per-Sim RNG** — `sim.rng: random.Random` seeded via constructor;
  the hook the Phase 2 seed tree plugs into.
- [x] **1.6 Thread-ownership debug mode** — `Sim(debug=True)` /
  `LLMSIM_DEBUG=1`: assert owning-thread identity on every `schedule()`.
- [x] **1.7 Resources: base + Resource** — `resources/base.py` request/release
  protocol (context managers, trigger chains); `Resource`, `PriorityResource`,
  `PreemptiveResource`.
- [x] **1.8 Resources: Container + Stores** — `Container`; `Store`,
  `PriorityStore`, `FilterStore`.
- [x] **1.9 Structured tracing** — `trace.py`: canonical event logs (needed by
  Phase 3 equivalence tests; cheap to add now).
- [x] **1.10 SimPy 3 behavioral suite port** — port the ~150-test suite to the
  new API as the acceptance gate (interrupt edge cases, condition composition,
  preemption, store filtering).
- [x] **1.11 Canonical models on llmsim + perf gate** — reimplement the three
  benchmark models on llmsim; wire regression thresholds into CI.

**Exit criteria:** ported behavioral suite green; ≥1.2× event throughput vs
SimPy 3 on 3.14; zero functional regressions on 3.14t.

## Phase 2 — Parallel replications + reproducible randomness (the flagship)

Goal: `Experiment.run()` delivering near-linear Monte Carlo scaling with
bit-identical results across backends.

- [x] **2.1 Seed tree** — `rand/streams.py`: master seed →
  (config index, replication index) → 128-bit child seeds via SHA-256 path
  hashing; unit tests for independence and stability.
- [x] **2.2 Execution backends** — `parallel/backends.py`: `ExecutionBackend`
  abstraction over thread / interpreter / process pools; `backend="auto"`
  runtime selection; factory-importability validation at construction with
  actionable errors.
- [x] **2.3 Experiment API** — `parallel/replicate.py`: `Experiment`,
  `run_replications()`, `ReplicationResult`; results keyed by
  (config, replication), never completion order.
- [x] **2.4 Result streaming + cancellation** — `exp.iter_results()` yielding
  as-completed; backend-aware cancellation (thread backend: shared token
  checked between steps for mid-replication cancel; interpreter/process
  backends: replication-granularity cancel — stop dispatching and
  `Future.cancel()` pending work, since isolated workers cannot see a parent
  token); optional zstd spooling for large traces; warm-pool reuse on the
  interpreter backend.
- [x] **2.5 Backend conformance tests** — identical result sets across all
  three backends for fixed seeds (validates the reproducibility guarantee);
  GIL re-enable detection after model import in workers, with loud warning.
- [x] **2.6 Scaling benchmarks + docs** — replication throughput vs worker
  count on 3.14t and GIL builds; publish curves; memory (RSS per replication)
  guidance; the "Which parallelism do I need?" decision-tree doc page.

**Exit criteria:** ≥6× replication throughput on 8 physical cores (3.14t);
identical numerics across all three backends.

## Phase 3 — Single-run conservative PDES (research-grade)

Goal: shard one large model across cores with provable equivalence to the
sequential reference.

- [x] **3.1 Channels + mailboxes** — `parallel/pdes/channel.py`: typed,
  lookahead-carrying channels; locked `deque` mailboxes; send-delay ≥ lookahead
  enforcement; deterministic `(timestamp, channel id, sequence)` ordering.
- [x] **3.2 ShardedSim topology** — `parallel/pdes/shard.py`: `@topo.shard(i)`
  builders, per-shard `Sim` on its own thread, ports API; cross-shard resource
  sharing rejected at construction.
- [x] **3.3 Safe-window synchronizer** — `parallel/pdes/sync.py`: barrier-based
  YAWNS-style rounds (bound reporting, global horizon `H`, delivery-before-
  execution, strict `time < H` execution); GIL-build prominent warning
  (correct but not faster).
- [x] **3.4 Trace-equivalence test suite** — sharded grid-conveyor trace ≡
  sequential trace, bitwise, across 1/2/4/8 shards — including the adversarial
  horizon-boundary model (messages at exactly `H`, ties with local events).
- [x] **3.5 Concurrency soak CI job** — long randomized runs on 3.14t with
  `pytest-repeat` and randomized barriers; assertions-on debug build.
- [x] **3.6 `pdes.analyze()`** — critical-path estimator from sequential
  traces so users can predict achievable speedup before partitioning.
- [x] **3.7 PDES performance gate + honest docs** — grid-conveyor benchmark at
  1/2/4/8 shards; documented slowdown curve as lookahead → 0.

**Exit criteria:** bitwise equivalence suite (including the adversarial
horizon-boundary model) green in CI; 3.14t soak job green; shard-scaling and
lookahead-degradation curves measured and published. The ≥3×-at-8-shards
figure (lookahead = 4× mean event spacing) is **recorded, not blocking**:
Phase 2 measured pure-Python DES event loops anti-scaling across threads on
CPython 3.14.2t (see `docs/perf-notes.md`), so the speedup target is
interpreter-dependent and is asserted when a CPython build demonstrates it.

## Phase 4 — Offload, real-time, and 1.0 polish

Goal: round out the parallel story and freeze the API.

- [x] **4.1 Compute offload** — `parallel/offload.py`: `sim.offload(fn, ...)`
  with deterministic completion slots (`strict=True` default: block wall-clock
  at the slot), `strict=False` opt-out flagged by debug mode; defined
  failure/cancellation semantics; max-vs-sum ceiling documented.
- [x] **4.2 Real-time mode** — `rt.py`: wall-clock-synchronized stepping on
  `time.monotonic()`; offload synergy for hardware-in-the-loop.
- [x] **4.3 Migration guide from SimPy 3** — concept-mapping table
  (`env.process` → `sim.spawn`, `env.timeout` → `sim.delay`, …) plus worked
  example ports of the canonical models.
- [x] **4.4 Docs site** — full documentation build (user guide + mkdocstrings
  API reference); decision tree as the parallel landing page; published scaling
  curves; GitHub Pages deploy workflow with `mkdocs build --strict` as a
  required PR gate.
- [~] **4.5 1.0 API freeze review** — public-API audit **complete**
  (`specs/phase-4.4-4.5/api-audit.md`: typing completeness, `__all__`
  consistency test, naming consistency, deprecation policy page); zero
  unresolved findings. The **Phase 5 gate is now clear** — both domain examples
  are green and the API-friction list is resolved or waived
  (`specs/phase-5-domain-example/api-friction.md`). Only tagging 1.0 and
  publishing to PyPI remains (this phase unblocks but does not perform it).

**Exit criteria:** offload trace-equivalence (strict mode) green; docs
complete; Phase 5 examples green; 1.0 on PyPI.

## Phase 5 — Domain example gallery (runs concurrently with Phase 4)

Goal: two runnable, tested, end-to-end examples in high-relevance domains that
demonstrate every parallelism tier and serve as the final API dogfooding pass
before the 1.0 freeze (step 4.5 gates on this phase). Examples live in
`examples/`, run in CI, and each gets a worked docs page.

- [x] **5.1 Autonomous ride-hailing fleet — core model** — a robotaxi fleet
  serving Poisson trip requests over city zones: vehicle processes (pickup,
  drive, drop-off, reposition, recharge), charging stations as
  `Resource`s, idle-fleet dispatch via `FilterStore`; pluggable dispatch
  policies (closest-available vs power-of-d, as studied in the EV ride-hailing
  DES literature); deterministic same-seed test and KPI collection (wait time,
  utilization, abandonment).
- [x] **5.2 Ride-hailing fleet — parallelism showcases** — (a) fleet-sizing
  Monte Carlo study via `Experiment` (confidence intervals over fleet size ×
  demand configs; Phase 2 showcase); (b) zone-sharded `ShardedSim` variant
  using inter-zone travel time as channel lookahead, with trace-equivalence
  test against the sequential model (Phase 3 showcase); docs page with
  measured scaling curves.
- [x] **5.3 LLM agentic workflow — core model** — a multi-agent pipeline in
  the shape current LLM-scheduling research simulates: tasks arrive at an
  orchestrator; agent processes alternate *think* steps (inference requests
  queued at shared LLM-server `Resource`s with token-length-dependent service
  times and batching) and *act* steps (tool calls with stochastic latency,
  failures, retries); KPIs: end-to-end task latency, queue depth, cost per
  task; deterministic same-seed test.
- [x] **5.4 Agentic workflow — parallelism showcases** — (a) capacity-planning
  sweep via `Experiment` (server count × batch size × agent concurrency);
  (b) `sim.offload` showcase: a CPU-heavy scoring/routing policy evaluated on
  the worker pool in strict mode, with trace-equivalence test (Phase 4
  showcase); docs page with measured curves.
- [x] **5.5 Example gallery integration** — `examples/` wired into CI on both
  builds (smoke-run with small parameters); gallery landing page linking each
  example to the parallelism decision tree; API-friction findings filed and
  resolved (or explicitly waived) before the 4.5 freeze review.

**Exit criteria:** both examples green in CI on 3.14 and 3.14t; same-seed
determinism tests pass; each showcase has a published measured curve; friction
list resolved or waived at the 4.5 review.

## Phase 6 — LLM-powered scenario generation (post-1.0, 1.x)

Goal: an LLM-powered agent that reads system documents (hardware
specifications, operating procedures, failure-mode reports) and generates
realistic, targeted, real-world-inspired simulation scenarios — parameter sets
plus fault-injection event sequences — designed to surface emergent behavior.
Example: given a charging-station hardware spec (MTBF table, thermal derating
curve, duty-cycle limits), the agent proposes scenarios that capture the
system under fault: degraded charge rates during a heat wave, intermittent
connector failures at peak demand, cascading queue collapse after a
dual-station outage.

**Determinism boundary (normative for every step below):** the LLM runs at
*design time only* — it produces validated, serialized scenario artifacts, and
simulations replay artifacts deterministically. No LLM or network call ever
occurs inside a running simulation; same artifact + master seed → bitwise
identical traces. This phase does not gate the 1.0 freeze (step 4.5); it
ships as a 1.x minor release.

- [ ] **6.1 Scenario schema** — `scenario/schema.py`: stdlib-only typed
  dataclasses: `ScenarioSpec` (model parameter overrides, distribution specs
  with explicit bounds, seed policy) and `FaultEvent` sequences (timestamped
  injections: degradation, intermittent fault, hard fault, recovery); strict
  validation with actionable errors; JSON (de)serialization; artifacts are
  content-hashed for provenance and pinned in version control like lockfiles.
- [ ] **6.2 Fault-injection runtime** — `scenario/inject.py`: apply a
  validated `ScenarioSpec` to a model — parameter overrides at construction
  plus an injector process that replays the `FaultEvent` sequence at simulated
  timestamps into user-registered fault hooks; deterministic replay test
  (same artifact + seed → bitwise identical trace); `Experiment` integration
  for scenario × replication sweeps. Depends only on Phase 1–2 machinery.
- [ ] **6.3 LLM client boundary** — `scenario/llm.py`: minimal
  provider-agnostic `LLMClient` protocol (system documents + schema in,
  structured JSON out); `AnthropicClient` default adapter behind the
  `llmsim[llm]` extra; record/replay transport that caches responses as
  committed fixtures so tests and CI never touch the network.
- [ ] **6.4 ScenarioAgent** — `scenario/agent.py`: the LLM-powered agent
  class — `ScenarioAgent(client).propose(docs, target=..., n=...)` ingests
  system documents (plain text / markdown), prompts for grounded fault
  hypotheses, requests schema-constrained JSON, validates against 6.1 with
  bounded repair-and-retry on invalid output, and returns `ScenarioSpec`
  artifacts. **Grounding requirement:** every generated scenario must cite
  the document passage that motivates it (e.g., the MTBF row behind a failure
  rate) and carry a human-readable rationale; ungrounded scenarios are
  rejected at validation. A functional wrapper `generate_scenarios(...)`
  covers the one-shot case.
- [ ] **6.5 Emergent-behavior harness** — `scenario/report.py`: run generated
  scenarios through `Experiment` against a baseline scenario; flag emergent
  outcomes (KPI-distribution excursions, threshold/phase-transition behavior
  across a parameter range, cascade signatures in traces) in a structured
  report; optional bounded refinement loop — the report can be fed back to
  `ScenarioAgent.refine()` to sharpen scenarios toward the emergent regime
  (explicit iteration cap, every intermediate artifact retained).
- [ ] **6.6 Worked example + docs** — end-to-end hardware-fault study on the
  Phase 5.1 ride-hailing model: charging-station hardware spec → ScenarioAgent
  → scenario artifacts → Monte Carlo sweep → emergent-behavior report; CI runs
  fully offline from recorded LLM fixtures and committed artifacts; docs page
  covering grounding, artifact review workflow (generated scenarios are
  reviewed and committed like code), and the design-time/run-time determinism
  boundary.

**Exit criteria:** no LLM/network activity after `run()` starts (enforced by
test); generated artifacts validate against the schema and replay bitwise
identically across backends; the full agent pipeline tested offline via
recorded fixtures; worked example green in CI on 3.14 and 3.14t.

## Cross-cutting (applies to every step)

- **Determinism:** every parallel feature ships with a same-seed-same-result
  test in the same PR.
- **Performance:** benchmark regression gates run on every PR from Phase 0.4
  onward.
- **Memory:** RSS tracking on 3.14t (larger object headers, mimalloc);
  worker-count guidance kept current in docs.
- **Docs honesty:** any step introducing a parallel capability documents its
  slowdown regimes in the same PR that ships the feature.
