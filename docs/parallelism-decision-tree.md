# Which parallelism do I need?

llmsim offers three share-nothing strategies. Parallel replications (Phase 2)
and PDES sharding (Phase 3) are shipping; offload lands in Phase 4.

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
    │   → offload (Phase 4) — hand computations to a worker pool
    │     without breaking determinism.
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
