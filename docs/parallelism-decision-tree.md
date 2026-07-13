# Which parallelism do I need?

llmsim offers three share-nothing strategies, all shipping: parallel
replications (Phase 2), PDES sharding (Phase 3), and compute offload
(Phase 4).

```
Do you run one model many times (replications, parameter sweeps,
confidence intervals)?
│
├── YES → llmsim.Experiment / run_replications        ← START HERE (shipping)
│         Many independent Sims, one per worker.
│         Bit-identical results on any backend or worker count.
│
└── NO — one single run is too big or too slow?
    │
    ├── One replication is CPU-bound in *computation* (not events)?
    │   → yield sim.offload(fn, ...) (shipping) — hand computations
    │     to a worker pool without breaking determinism. Read
    │     "Offloading computation" below first.
    │
    └── One replication has too many *events* for one core?
        → llmsim.ShardedSim (shipping) — conservative (YAWNS-style)
          partitioning of a single model across cores. Read the
          "Should I shard?" checklist below first.
```

## Should I shard? (PDES)

Sharding is an explicit modeling decision, not a flag. Work through this
checklist — every "no" costs real speedup:

1. **Can you partition the model so shards interact only by messages** with a
   known minimum delay (the *lookahead*)? Shards cannot share `Resource`s,
   `Store`s, or events — miswiring is rejected at construction, yielding
   another shard's event is rejected by the process driver in every mode,
   and the debug mode (`ShardedSim(..., debug=True)` / `LLMSIM_DEBUG=1`)
   catches objects smuggled through closures or payloads at runtime.
2. **Is the lookahead a large multiple of the mean event spacing?** The
   synchronizer advances one safe window per barrier round; with lookahead
   near the event spacing the run is barrier-dominated and *slower* than
   sequential (measured curve in [Performance notes](perf-notes.md)).
3. **Are the shards balanced?** The window cost is the busiest shard's.
4. **Check before you build:** run your unpartitioned model with a tracer,
   then `llmsim.parallel.pdes.analyze(traces, lookahead=...)` — it reports
   the balance ceiling and a window-model speedup estimate from the trace
   alone.

The correctness guarantee is unconditional: a threaded `topo.run()` is
bitwise trace-equivalent to the same topology's sequential reference
(`topo.run(mode="sequential")`), for the same `master_seed`, at any shard
count — enforced by the equivalence suite and a jittered soak job in CI.
Results are deterministic per fixed topology; a *different* partition is a
different (equally deterministic) model, because shard streams derive from
the domain-separated seed path.

Honest performance status (2026-07, CPython 3.14.2t): thread-parallel DES is
currently capped near ~1.1× by interpreter-level contention (see
[Performance notes](perf-notes.md)); on GIL builds PDES runs correct but
time-sliced, with a prominent runtime warning. Shard for *scale* today
(models too big for one heap), and for speed as free-threaded CPython
matures.

If you are unsure: replications. Most stochastic studies need confidence
intervals anyway, and replications parallelize embarrassingly — the whole
model stays single-threaded, exactly as you wrote it.

## Offloading computation

When one *event handler* is CPU-heavy (a scoring policy, a routing solve, a
physics step) but the event count is fine, hand the computation to a worker
pool without leaving the deterministic world:

```python
from llmsim import OffloadPool, Sim

def dispatcher(sim, fleet):
    ...
    # The result arrives exactly at sim.now + 2.0 — a completion slot the
    # *model* chose — no matter how long the computation takes on the wall
    # clock. Same trace as running it inline, on any backend.
    plan = yield sim.offload(score_assignments, snapshot, delay=2.0)
    ...

sim = Sim(seed=7)
pool = OffloadPool(sim, backend="auto")   # attach before sim.run()
...
sim.run()
pool.close()                              # or use OffloadPool as a context manager
```

The rules, in decreasing order of importance:

1. **The payload is a module-level function of its arguments** — validated at
   submission (lambdas/closures rejected), pickle-preflighted on the process
   and interpreter backends. Never pass `Sim`-owned mutable state; on the
   thread backend arguments travel by live reference and debug mode is your
   guard.
2. **`delay` is the completion slot, a modeling decision** (like PDES
   lookahead): the slot must be a pure function of model state. If the
   computation outlives the slot, the run blocks wall-clock at the slot —
   correctness never bends, you just wait.
3. **Speedup comes only from offloads that overlap in simulated time** — the
   ceiling is max-vs-sum per busy window, measured curves and slowdown
   regimes (no overlap, cheap payloads, thread-backend caveats, the hung-
   payload hazard) in [Performance notes](perf-notes.md).
4. **`strict=False` trades determinism for latency** — results deliver as
   available (optionally no earlier than `now + delay`); ordering then
   depends on wall-clock timing, and debug mode flags every such call. A
   non-strict result is never dropped: `run()` drains outstanding offloads
   before concluding the schedule is empty.
5. **Inside an `Experiment` worker, offload defaults to inline** — nested
   pools are explicit opt-in (`backend="threads"` etc.); process pools
   inside interpreter workers are rejected (broken upstream).

Interrupting a process that waits on an offload abandons the computation
(pending work is cancelled; a finished result is discarded, never
delivered), and `OffloadEvent.cancel()` does the same explicitly.

## Real-time mode (hardware-in-the-loop)

`llmsim.rt.run` paces any ordinary `Sim` against the wall clock — a driver
function, not a different engine, so the model is unchanged and a paced run
of a deterministic model produces the **same trace** as `sim.run()`:

```python
from llmsim import OffloadPool, Sim, rt

sim = Sim(seed=7)
pool = OffloadPool(sim, backend="threads")   # optional: the HIL synergy
...
rt.run(sim, factor=0.5)   # one simulated time unit = 0.5 real seconds
pool.close()
```

The contract:

- **`factor`** is real seconds per simulated time unit; an event at
  simulated `T` processes no earlier than `start + (T - t0) * factor` on
  `time.monotonic()`.
- **Drift**: if processing falls behind by more than one `factor` of slack,
  `strict=True` (default) raises `RealtimeDriftError` with the simulated
  time and measured drift; `strict=False` hurries (no sleeping) until the
  schedule catches up. Events are never skipped in either mode.
- **Offload synergy**: a strict offload's completion slot becomes a real
  deadline, and the payload computes *during* the pacing sleep — a scoring
  policy with a 0.2 s slot budget and a 50 ms payload costs zero drift.
  Non-strict offloads deliver between paced steps, exactly as under
  `sim.run()`.
- Drift regimes (event-density floor, overlong payloads) are measured in
  [Performance notes](perf-notes.md).

## The 80% case

```python
# mymodel.py — the factory must be a module-level function.
from llmsim import Sim, Resource, SeedStream

def bank(stream: SeedStream, config: dict[str, float]) -> dict[str, float]:
    sim = Sim(rng=stream.rng())          # the derived, reproducible stream
    ...                                   # build and run the model
    return {"mean_wait": ...}             # return plain picklable KPIs

# study.py
from llmsim import Experiment
from mymodel import bank

results = Experiment(
    bank,
    configs=[{"tellers": 2}, {"tellers": 3}],
    master_seed=20260712,                 # explicit, required
).run(replications=100)                   # backend="auto", all cores

results[(1, 42)].value                    # config 1, replication 42
```

Results are keyed by `(config_index, replication_index)` — never by
completion order — so aggregation is order-insensitive by construction.
`iter_results()` yields the same results as they complete; `cancel()` (or
exiting an `Experiment` used as a context manager) stops a running study.

## Choosing a backend

`backend="auto"` picks the right default; override it only after reading the
measured curves in [Performance notes](perf-notes.md).

| Backend | When `auto` picks it | Startup cost | Cancellation granularity |
|---|---|---|---|
| `threads` | free-threaded 3.14t (GIL off) | ~none | mid-replication, if the factory consults its `CancelToken` |
| `processes` | GIL builds | highest (spawn/forkserver) | per replication |
| `interpreters` | opt-in only (PEP 734) | between the two | per replication |

Two practical notes from measurement (details and numbers in
[Performance notes](perf-notes.md)):

- On CPython **3.14.2t**, allocation-heavy DES event loops currently scale
  poorly across *threads* (interpreter-level reference-count contention on
  shared objects). Until upstream contention improves, `backend="processes"`
  is usually faster for replication studies even on 3.14t.
- On **GIL builds**, `interpreters` can beat `processes` at higher worker
  counts (cheaper worker startup) once your model imports cleanly in a
  subinterpreter — it is opt-in while PEP 734 matures.

## The reproducibility guarantee — and what it does not cover

llmsim guarantees the same `(master_seed, config_index, replication_index)`
triple receives the same RNG stream and the same deterministic event ordering
on any backend, worker count, and build. End-to-end identical *results* follow
whenever the model itself is deterministic and backend-portable.

The guarantee does **not** absorb nondeterminism your model introduces.
Known unsupported sources:

- **Wall-clock time** — `time.time()`, `datetime.now()`, timestamps in KPIs.
- **Identity-keyed iteration** — iterating a `set`/`dict` keyed by object
  identity (`id()`-dependent order varies per process).
- **Global mutable module state** — counters or caches shared across
  replications; workers may or may not share them depending on the backend.
- **Native extensions with their own threading or rounding** — BLAS thread
  pools, SIMD reductions, GPU kernels.
- **OS entropy** — `random.random()` module-level calls, `os.urandom`,
  `uuid.uuid4()`; draw only from the injected stream (`sim.rng` /
  `stream.rng()`).

## Memory: how many workers?

Measured on the Phase 2 benchmark model (an M/M/1 with ~6 000 customers in
flight; Apple M5, 3.14t): the coordinator's base interpreter is ~30 MB and
each *concurrent* replication adds roughly **3–4 MB** of peak RSS on the
thread backend. The process backend pays the ~30 MB interpreter base **per
worker** instead. Free-threaded builds carry larger object headers, so budget
~10–20% extra RSS on 3.14t for the same model.

Rule of thumb: `max_workers = physical cores` for CPU-bound replications;
reduce it if `workers × (per-replication RSS)` (threads) or
`workers × (interpreter + model RSS)` (processes) approaches available
memory. For studies whose per-replication results are large, pass
`Experiment(..., spool=True)` to hold results as zstd-compressed bytes and
decompress on access.
