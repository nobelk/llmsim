# Requirements — Phase 3: Single-run conservative PDES (research-grade)

## Context

Phases 1–2 delivered the sequential core (with structured tracing, step 1.9,
built explicitly for this phase's equivalence tests) and the flagship
replication API. Phase 3 serves the user with *one* enormous model who wants
one run to go faster: shard a single model across cores with **provable
equivalence to the sequential reference** (`docs/part-deux.md` §4.6). Shards
interact only through lookahead-carrying channels — the only locked structures
in the library (mission principle 1) — synchronized by barrier safe-window
(YAWNS-style) rounds. Correctness is absolute (bitwise trace equivalence,
mission principle 2); performance is measured and documented honestly
(principle 3), because Phase 2 established that pure-Python DES event loops
currently anti-scale across threads on CPython 3.14.2t.

## Scope

### In

- **3.1 Channels + mailboxes** — `parallel/pdes/channel.py`: typed,
  lookahead-carrying channels between shards; locked `deque` mailboxes
  (`deque` + `threading.Lock`, touched only at window edges); send-delay ≥
  lookahead enforced at `send()` with an actionable error; deterministic
  message ordering by `(timestamp, channel id, per-channel sequence number)`.
- **3.2 ShardedSim topology + sequential reference runner** —
  `parallel/pdes/shard.py`: `ShardedSim(shards=N, master_seed=...)`,
  `@topo.shard(i)` builder registration, `ports.out(name, lookahead=...)` /
  `ports.inbox(name)` wiring; construction-time validation (cross-shard
  resource sharing rejected, unknown/duplicate channel names, missing shard
  builders, non-positive lookahead); a **sequential reference mode** that runs
  the same topology on one thread with identical message-ordering keys — the
  oracle every equivalence test compares against.
- **3.3 Safe-window synchronizer** — `parallel/pdes/sync.py`: one `Sim` per
  shard on its own thread; barrier-based rounds (bound reporting, global
  horizon `H`, delivery-before-execution, strict `time < H` execution);
  termination when `H` exceeds `until` or all heaps and mailboxes drain;
  prominent GIL-build warning (correct but not faster).
- **3.4 Trace-equivalence suite** — sharded traces bitwise-equal to the
  sequential reference at 1/2/4/8 shards on the canonical models, including
  the adversarial horizon-boundary model (messages landing exactly at `H`,
  timestamp ties with local events).
- **3.5 Concurrency soak CI job** — fill the existing Phase 0 soak scaffold:
  long randomized runs on 3.14t (`PYTHON_GIL=0`) with `pytest-repeat`,
  randomized barrier jitter, assertions on.
- **3.6 `pdes.analyze()`** — critical-path estimator over Phase 1 traces of a
  partitioned topology, predicting achievable speedup before the user invests
  in sharding; documented as an estimate.
- **3.7 Performance gate + honest docs** — grid-conveyor shard-scaling
  benchmark at 1/2/4/8 shards; the documented slowdown curve as lookahead → 0;
  a loose CI regression floor sized to real runner hardware; decision-tree and
  perf-notes updates.

### Out

- **Optimistic / Time Warp synchronization** — permanently rejected
  (generator frames cannot be snapshotted; mission).
- **Interpreter-backed PDES** — permanently out for 1.0: subinterpreters
  cannot share thread-mode mailboxes, live `Sim`s, or channel endpoints; it
  needs its own post-1.0 design (`docs/part-deux.md` §4.6).
- **Automatic partitioning** — sharding is an explicit modeling decision;
  `pdes.analyze()` estimates, it does not partition.
- **Cross-shard resource sharing or event awaiting** — message passing only;
  rejected at construction, not silently degraded.
- **Dynamic topology** — shards and channels are fixed at construction;
  re-sharding mid-run is a non-goal for 1.0.
- **Engine hot-path contention mitigation** — deliberately excluded (key
  decision below): no Phase 1 core changes to chase 3.14.2t thread scaling in
  this phase.
- **Process-backed PDES** — shards share mailboxes by reference; the thread
  backend is the only 1.0 execution mode (GIL builds run it degraded, with a
  warning).

## Decisions

- **Synchronization is barrier safe-window, YAWNS-style, with a
  progress-safe horizon (normative; supersedes the literal formula in
  `docs/part-deux.md` §4.6).** Each round: (1) every shard *i* reports
  `bound_i = next_i + L_i`, where `next_i` is the minimum of its next local
  event time **and the timestamps of undelivered messages already sitting in
  its inbox mailboxes**, and `L_i` is the min lookahead over its outgoing
  channels (`+inf` for a shard with none); (2) the global safe horizon is
  `H = min_i bound_i` — pending messages are accounted for through `next_i`,
  **not** as a separate `min undelivered timestamp` term (the design doc's
  literal formula livelocks: a message at time `m` that itself defines
  `H = m` is never delivered by a strict `< H` rule; folding it into the
  destination's `next_i` yields `H ≥ m + L_dest > m`, so it clears);
  (3) every buffered message with `timestamp < H` is delivered into its
  destination heap **before** the window opens, in globally deterministic
  order; (4) shards execute only events with `time` **strictly** `< H` —
  events at exactly `H` wait for the next window; (5) barrier, repeat.
  **Progress property (normative, tested):** with all lookaheads positive,
  every round with pending work satisfies `H_new > H_old`, so the
  minimum-pending-work item (event or undelivered message) is always
  executed or delivered within finitely many rounds — including the case
  where the minimum undelivered message has no earlier local event anywhere.
  Within a window a shard is pure Phase 1 sequential code — zero locks in
  the hot path.
- **Causality invariant (normative, tested).** No event at simulation time
  *t* executes on any shard until every inter-shard message with timestamp
  < *t* has been delivered; same-timestamp ordering between delivered
  messages and local events is fixed by deterministic composite keys and is
  identical to the sequential reference execution of the same partitioned
  model. The adversarial horizon-boundary test is part of acceptance.
- **Message ordering is `(timestamp, channel id, per-channel sequence
  number)` (normative, tech-stack constraint 7).** Delivered messages get
  their heap tie-break keys assigned from that sorted order, so a sharded run
  is bit-reproducible across worker interleavings.
- **Positive lookahead is required at construction (normative).** With
  lookahead = 0 the strict `< H` rule cannot make progress (the shard owning
  the minimum event could never execute it). `ports.out(...)` rejects
  `lookahead <= 0` with an actionable error; the lookahead → 0 *slowdown*
  regime (small but positive lookahead) is measured and documented instead.
- **The sequential reference is a first-class runner, not a test fixture.**
  The same registered topology runs on one thread (single scheduler loop over
  all shard `Sim`s with the same delivery keys), giving users a debuggable
  mode and the equivalence suite its oracle. Same master seed → the parallel
  run's traces are bitwise-equal to this reference.
- **Shard RNG derives from a domain-separated PDES seed path (normative).**
  `ShardedSim(..., master_seed: int)` is explicit and required (no ambient
  default, matching Phase 2). Shard streams are **not** derived through the
  Phase 2 `(config_index, replication_index)` path — that would collide
  semantically with `Experiment` streams for the same master seed. Instead
  `rand/streams.py` gains a co-existing, versioned shard path (e.g.
  `llmsim.seed.v1:<master_seed>:pdes:<shard_index>`) with its own
  known-answer and no-collision tests; the v1 replication path is a pinned
  wire contract and is not modified. One seed reproduces the whole sharded
  run for a **fixed topology/partition** on any build and any thread
  interleaving. Results are *not* claimed invariant across different shard
  counts: repartitioning reassigns entities to different shards and streams,
  so a different partition is a different (equally deterministic) model.
  Models that need partition-invariant randomness should derive per-entity
  streams from the seed tree themselves — documented as guidance, not
  enforced.
- **Performance is measured, recorded, and gated loosely (key decision).**
  Phase 2 measured pure-Python DES event loops anti-scaling across threads on
  CPython 3.14.2t (refcount cache-line contention on shared objects; mm1
  replications 0.98× at 8 workers). PDES shards are threads, so the roadmap's
  ≥3×-at-8-shards exit criterion is treated as **interpreter-dependent**: the
  benchmark measures and publishes the real shard-scaling and
  lookahead-degradation curves; CI enforces correctness strictly (equivalence,
  soak) plus only a loose performance-regression floor; the ≥3× headline is
  recorded when a CPython build demonstrates it. No Phase 1 hot-path changes
  in this phase to chase contention.
- **GIL builds run PDES correctly but degraded, with a prominent runtime
  warning** (time-sliced threads; not faster than sequential). Correctness
  tests run on both builds; performance claims come from 3.14t only.
- **Thread ownership per tech-stack constraints 1–4 — enforced by two
  mechanisms, honestly scoped.** Each shard's `Sim` and everything attached
  to it lives on exactly one thread; generators pin to their home thread;
  the only synchronized structures are the per-channel mailboxes.
  Enforcement: (a) **construction-time structural validation** rejects a
  shard builder wiring another shard's `Resource`/`Store`/`Event`/`Process`
  where detectable; (b) **the process driver rejects cross-`Sim` yields
  outright** — yielding an event owned by a different `Sim` raises
  deterministically in every mode, debug or not (SimPy-faithful; implemented
  during Phase 3 because the debug guard provably cannot catch this class:
  the foreign event's state is read cross-thread and one interleaving
  resumes the process locally and silently); (c) **runtime debug-mode
  assertions** — Phase 1's owner-thread guard on `Sim.schedule()` — catch
  the remaining escapes (foreign objects smuggled via closures, module
  globals, or message payloads), and the soak job runs with debug assertions
  on so schedule-dependent escapes surface in CI. Message payloads should be
  plain data; sending a `Sim`-owned object is documented as unsupported and
  is caught by the debug guard when the receiving shard touches it.
- **Stdlib-only** — `threading` (`Lock`, `Barrier`), `collections.deque`,
  `heapq`; no new dependencies.
