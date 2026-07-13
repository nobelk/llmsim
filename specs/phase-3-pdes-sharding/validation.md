# Validation — Phase 3: Single-run conservative PDES

## Success criteria

Correctness is gated strictly; performance is measured and published, gated
only against catastrophic regression (key decision in `requirements.md`).

1. **Bitwise trace equivalence.** For fixed master seeds, the parallel
   sharded run's traces are bitwise-equal to the sequential reference runner
   on the canonical topologies — including the sharded grid-conveyor at
   1/2/4/8 shards — on 3.14 and 3.14t (`PYTHON_GIL=0/1`). The adversarial
   horizon-boundary model (messages exactly at `H`, timestamp ties with local
   events) passes the same bitwise bar.
2. **Determinism (fixed partition).** Same `(master_seed, topology, until)`
   → identical traces and results on repeated parallel runs and across
   thread interleavings, at every shard count 1/2/4/8 individually. Results
   are not asserted equal *between* different shard counts — repartitioning
   assigns entities different streams (requirements.md seed decision); the
   invariant at each count is parallel ≡ sequential reference, bitwise.
   **Progress:** the no-livelock case (minimum pending item is an undelivered
   message with no earlier local event) terminates, and `H` strictly
   increases every round with pending work.
3. **Concurrency soak green.** The 3.14t (`PYTHON_GIL=0`) soak job — repeated
   randomized runs with barrier jitter and assertions on — passes within its
   wall-clock budget; no schedule-dependent failure over the stabilization
   period.
4. **Honest performance record.** The shard-scaling curve (1/2/4/8 shards,
   lookahead = 4× mean event spacing) and the lookahead-degradation curve are
   measured on 3.14t and published in `docs/perf-notes.md`, alongside the
   3.14.2t thread-contention context. CI enforces only the loose floor
   (2-shard run ≥ 0.5× sequential on Linux runners; macOS CI timing skipped).
   The roadmap's ≥3×-at-8-shards figure is recorded as interpreter-dependent
   and asserted only when a CPython build demonstrates it — not a merge
   blocker (mirrors the Phase 2 6× headline treatment).
5. **Types/lint clean; required matrix green.** `mypy --strict` and `pyright`
   strict on the new public API (`ShardedSim`, ports/channel types,
   `pdes.analyze` report types) and internals; `ruff check` + `ruff format
   --check`; required CI rows are 3.14 and 3.14t × {Linux, macOS} +
   `PYTHON_GIL=0/1`; 3.15 stays a non-blocking canary.

## Checklist

- [ ] `channel.py`: send-delay ≥ lookahead enforced (actionable error);
      `lookahead <= 0` rejected at construction; per-channel sequence
      monotonic; drain order deterministic under shuffled arrivals.
- [ ] `shard.py`: construction-time validation (duplicate/missing builders,
      unmatched channel names, cross-shard resource sharing) raises the
      documented errors; sequential reference runner produces identical
      traces across repeated same-seed runs; the domain-separated shard seed
      path has known-answer and no-collision tests and leaves the pinned v1
      replication path byte-identical.
- [ ] Ownership enforcement: closure/global capture of a foreign
      `Resource`/`Store`/`Event`, awaiting a foreign shard's event, and a
      `Sim`-owned object sent as a message payload are each rejected at
      construction where detectable and otherwise trip the debug-mode
      owner-thread assertion; the soak job runs with `LLMSIM_DEBUG=1`.
- [ ] `sync.py`: parallel traces ≡ sequential reference bitwise on the
      Group 2/3 topologies at 2 and 4 shards; strict `time < H` verified by
      the horizon-boundary test; the progress-safe horizon delivers a
      minimum undelivered message within finitely many rounds (no-livelock
      test) and `H` strictly increases; termination on `until` and on
      drained heaps/mailboxes; a failing shard fail-fasts, joins all
      threads, and names the shard; GIL build warns prominently.
- [ ] Trace-equivalence suite: sharded grid-conveyor ≡ sequential, bitwise,
      at each of 1/2/4/8 shards (fixed-partition determinism per count; no
      cross-count equality claim); runs on 3.14 and 3.14t
      (`PYTHON_GIL=0/1`).
- [ ] Soak job: scaffold replaced with the real randomized-jitter soak on
      3.14t; wall-clock budget documented; green across the stabilization
      period.
- [ ] `pdes.analyze()`: estimator output pinned against hand-computed
      critical paths (chain, independent, unbalanced topologies); assumptions
      documented.
- [ ] `benchmarks/`: shard-scaling and lookahead-degradation curves recorded
      on 3.14t; loose CI floor green on Linux; macOS timing skip in place.
- [ ] `docs/`: decision-tree PDES branch filled in (when to shard, lookahead
      quality, GIL warning, analyze() workflow); perf-notes Phase 3 section
      published with both curves and the slowdown regimes.
- [ ] Same-seed-same-result test ships in the same PR as each parallel
      capability (cross-cutting rule).

## Done when

The bitwise trace-equivalence suite (including the adversarial
horizon-boundary model) and the shard-count-invariance tests are green on the
required CI matrix; the 3.14t soak job passes within budget; the shard-scaling
and lookahead-degradation curves are published in `docs/perf-notes.md`; and
all lint/type gates are clean. The ≥3×-at-8-shards roadmap figure is expressly
**not** a merge gate: it is recorded in perf-notes with its
interpreter-dependence noted, to be asserted when hardware and CPython allow.
