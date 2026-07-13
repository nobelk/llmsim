# Plan — Phase 3: Single-run conservative PDES

Task groups are ordered by dependency; each is sized to land as its own
commit/PR. Group 1 is the smallest mergeable slice (pure data structures, no
threads). Every group that introduces a parallel capability ships a
same-seed-same-result test in the same PR; Group 7 documents the slowdown
regimes (cross-cutting rules).

## 1. Channels + mailboxes (`parallel/pdes/channel.py`)

- `Channel`: typed sender endpoint with a fixed positive `lookahead`;
  `send(message, delay)` enforces `delay >= lookahead` with an actionable
  error naming the channel and both values; each send stamps
  `(timestamp, channel_id, sequence)` where `sequence` is a per-channel
  monotonic counter.
- Mailbox: the destination-side buffer — `collections.deque` guarded by one
  `threading.Lock`, appended by the sender shard during a window, drained by
  the synchronizer at window edges (the only locked structures, per
  tech-stack constraint 2).
- Deterministic drain: messages sorted by `(timestamp, channel_id, sequence)`
  before delivery; delivered messages carry their assigned tie-break keys.
- Tests (no threads needed): send-delay enforcement, `lookahead <= 0`
  rejected, sequence monotonicity, drain-order determinism over shuffled
  arrival orders, lock discipline (mailbox mutation only through its API).

## 2. ShardedSim topology + sequential reference runner (`parallel/pdes/shard.py`)

- `ShardedSim(shards=N, *, master_seed: int)`; `@topo.shard(i)` registers a
  builder called as `builder(sim, ports)`; `ports.out(name, lookahead=...)`
  declares a sender endpoint, `ports.inbox(name)` a Store-like receiving
  endpoint local to the shard.
- Construction-time validation with actionable errors: every shard index has
  exactly one builder; channel names connect exactly one `out` to one
  `inbox`; `lookahead > 0`; cross-shard `Resource`/`Store`/event sharing
  rejected (a shard-owned object observed from another shard's builder).
- Domain-separated shard seed path in `rand/streams.py` (a co-existing
  versioned variant, e.g. `llmsim.seed.v1:<master>:pdes:<shard_index>`;
  the pinned v1 replication path is untouched) with known-answer and
  no-collision tests; per-shard `Sim` adopts its derived stream.
- **Sequential reference runner**: `topo.run(until, workers=1)` (or an
  explicit `mode="sequential"`) executes all shards on the calling thread —
  one global loop picking the lowest `(time, priority, ...)` event across
  shard heaps, delivering messages with the identical
  `(timestamp, channel_id, sequence)` keys. This is the oracle and the
  debugging mode.
- Tests: validation errors fire at construction; a two-shard
  producer/consumer topology runs sequentially end-to-end; same master seed →
  identical sequential traces across repeated runs (same-seed-same-result).

## 3. Safe-window synchronizer (`parallel/pdes/sync.py`)

- Thread-per-shard execution behind `topo.run(until=...)`: each shard thread
  loops {report `bound_i = next_i + L_i` where `next_i` folds in undelivered
  inbox-message timestamps (the progress-safe horizon from requirements.md —
  no separate undelivered-timestamp term); barrier; coordinator (or
  leaderless min-reduction) computes `H = min_i bound_i`; deliver all
  buffered messages with `timestamp < H` in deterministic order; execute
  local events with `time < H` strictly; buffer outgoing sends; barrier}.
- Termination: `H > until`, or all shard heaps and mailboxes empty; clean
  thread join; exceptions in any shard cancel the round, join all threads,
  and re-raise naming the shard (fail-fast, matching Phase 2's contract).
- GIL-build detection (`sys._is_gil_enabled()`) emits one prominent
  `RuntimeWarning`: correct but not faster than sequential.
- Tests (same PR, per the cross-cutting determinism rule): parallel run of
  the Group 2 topologies produces traces bitwise-equal to the sequential
  reference at 2 and 4 shards; same seed twice → identical results; empty
  shards, one-shard topologies, and `until`-boundary termination covered;
  **progress/no-livelock**: a topology whose minimum pending item is an
  undelivered message with no earlier local event anywhere must terminate,
  and `H` must strictly increase every round with pending work.

## 4. Trace-equivalence suite (`tests/`)

- Port the grid-conveyor canonical model to a sharded topology (row-band
  partitioning; conveyor transit time as lookahead).
- Bitwise trace equivalence (Phase 1 `trace.py` `Tracer` records, canonical
  payloads) between the parallel run and the sequential reference at
  1/2/4/8 shards, on 3.14 and 3.14t (`PYTHON_GIL=0/1` via the CI matrix).
- The **adversarial horizon-boundary model**: a topology engineered so
  cross-shard messages land exactly at `H` and tie with local event
  timestamps; asserts strict-`< H` deferral and deterministic tie-breaking
  match the sequential reference bitwise.
- Fixed-partition determinism at every shard count: for each of 1/2/4/8
  shards, parallel ≡ sequential reference bitwise and repeated same-seed runs
  are identical. (Results are *not* asserted equal between different shard
  counts — a different partition assigns entities different streams; see
  requirements.md.)
- **Ownership-violation acceptance tests**: a builder capturing another
  shard's `Resource`/`Store`/`Event` via closure or module global; awaiting a
  foreign shard's event; sending a `Sim`-owned object as a message payload —
  each rejected at construction where detectable, and otherwise caught by the
  debug-mode owner-thread assertion when touched from the wrong shard thread.

## 5. Concurrency soak CI job (fill the Phase 0 scaffold)

- Replace the no-op soak step in `.github/workflows/ci.yml` with a real run:
  `pytest-repeat` over the equivalence suite's parallel cases on 3.14t
  (`PYTHON_GIL=0`), **debug-mode ownership assertions on**
  (`LLMSIM_DEBUG=1`), with **randomized barrier jitter** (a test-only hook
  injecting microsecond sleeps around window edges) to shake out
  schedule-dependent ordering bugs and ownership escapes.
- Keep wall-clock bounded (a soak budget, e.g. a few minutes) and mark the
  job required only after a stabilization period; document the budget knob.

## 6. `pdes.analyze()` — speedup estimator (`parallel/pdes/analyze.py`)

- Input: a sequential-reference trace of a partitioned topology (Group 2
  runner) — or a plain `Sim` trace plus a proposed shard assignment.
- Output: a small typed report — per-shard event counts/work share, critical
  path across the channel graph, the resulting maximum theoretical speedup
  (total work / critical path), and window-count estimate from lookahead vs
  event spacing.
- Explicitly an estimate: documented assumptions (uniform event cost, zero
  synchronization overhead) stated in the docstring and docs page.
- Tests: hand-built topologies with known critical paths (chain → ~1×,
  independent shards → ~N×, unbalanced 90/10 split → ~1.1×); estimator output
  pinned against hand-computed values.

## 7. Performance gate + honest docs (`benchmarks/`, `docs/`)

- Shard-scaling benchmark: sharded grid-conveyor at 1/2/4/8 shards on 3.14t,
  with lookahead = 4× mean event spacing (the roadmap's reference point);
  record the measured curve in `docs/perf-notes.md`.
- Lookahead-degradation curve: same model, lookahead swept down toward the
  mean event spacing and below; publishes the documented slowdown regime
  (lookahead → 0 ⇒ sharded slower than sequential).
- Loose CI regression floor (per the key decision and Phase 2's CI lessons):
  correctness gates are strict; the performance gate only asserts the sharded
  run at 2 shards is not catastrophically slower than sequential
  (e.g. ≥ 0.5× on Linux runners; timing assertions skipped on shared macOS
  runners, whose best-of-N spread Phase 2 measured at ~20%). The ≥3×
  headline is recorded as interpreter-dependent, not asserted in CI.
- Docs: extend the "Which parallelism do I need?" page's PDES branch from
  placeholder to real guidance (when to shard, lookahead quality, GIL-build
  warning, `pdes.analyze()` workflow); perf-notes Phase 3 section with both
  curves and the 3.14t thread-contention context carried over from Phase 2.
