# Performance notes

## Phase 2 — parallel replications

Every number below is measured by `benchmarks/replication_scaling.py`
(64 replications of an ~20 ms M/M/1, `Experiment.run` wall clock **including**
executor startup and result transport, vs a pure in-process sequential loop).
Machine: Apple M5, 10 physical cores (**4 performance + 6 efficiency**),
macOS, CPython 3.14.2 / 3.14.2t. Ratios are the portable signal; absolute
times are hardware-specific.

### Measured replication throughput vs worker count

Free-threaded build (3.14.2t, GIL off — `auto` picks threads):

| Workers | threads | processes | interpreters |
|---:|---:|---:|---:|
| 2 | 1.33× | — | — |
| 4 | 1.29× | 2.80× | 2.67× |
| 8 | 0.98× | 3.68× | 2.92× |
| 10 | — | **3.70×** | — |

GIL build (3.14.2 — `auto` picks processes):

| Workers | processes | interpreters |
|---:|---:|---:|
| 1 | 0.94× | — |
| 2 | 1.87× | — |
| 4 | 2.86× | 3.01× |
| 8 | 3.85× | **4.31×** |
| 10 | 3.83× | — |

Context for the ceiling: an embarrassingly parallel pure-CPU baseline (no
llmsim, no allocation-heavy inner loop) measures **4.69×** at 8 workers on
this machine — the 4P+6E core asymmetry, not coordination overhead, is the
dominant cap. The process backend reaches ~80–90% of that ceiling; per-core
efficiency at low worker counts is 0.94–0.99× (2 workers) and 0.72–0.77×
(4 workers).

**Status of the ≥6×-on-8-cores roadmap target:** not yet demonstrated,
honestly. This 10-core machine is heterogeneous (4P+6E); even perfect scaling
cannot show 6× at 8 workers here. The measured per-core efficiencies above
(0.94×/core at 2 workers, 0.72–0.77×/core at 4) are consistent with ≥6× on
8 *homogeneous performance* cores, but per the docs-honesty rule that number
will be recorded only when measured on such a machine.

### Slowdown regimes (read before choosing a backend)

- **Threads on 3.14.2t anti-scale for DES event loops.** The engine's and
  `random.py`'s hot paths repeatedly touch objects shared by every thread
  (module-level C functions like `heapq.heappush`, code-object float
  constants, `random.py` globals), and reference-count cache-line contention
  on those objects currently outweighs the parallelism: the benchmark model
  measures 1.33× at 2 workers, then *degrades* (0.98× at 8). An isolated
  probe makes the mechanism unambiguous: a loop through pure-Python
  `Random.expovariate` scales 0.37× at 8 threads, while the *same math* with
  thread-locally bound `log`/constants scales 3.54×, and a bound C-method
  loop 3.19×. Until upstream free-threading contention improves, use
  `backend="processes"` for replication studies even on 3.14t.
- **Process startup dominates small studies.** A worker pays interpreter
  spawn + model import (macOS `spawn` is the worst case). A study whose
  *total sequential* runtime is under ~1 s can easily be slower with
  processes than sequentially (`workers=1` measures 0.94×). Size studies to
  seconds, or keep `max_workers` low for tiny ones.
- **Result transport is per-replication overhead.** On the process and
  interpreter backends every config and result crosses a pickle boundary
  (zstd-compressed when `spool=True`); returning multi-MB traces per
  replication shifts time from simulation to serialization. Return KPIs, not
  raw traces, when you can.
- **Efficiency cores flatten the top of every curve.** Beyond the number of
  performance cores, each extra worker adds a fraction of a core's
  throughput (see the ceiling note above); `max_workers = physical cores` is
  the sweet spot, and more than that is wasted coordination.

### CI gate

CI cannot see many cores, so the enforced regression gate
(`benchmarks/test_replication_scaling.py`) is a **per-core efficiency floor**
at `min(4, cpu_count)` workers on the **process backend** — ≥0.40×/core, far
under the measured 0.72–0.99×/core, so it trips on a genuine scaling
regression (e.g. accidental serialization in the coordinator) rather than
runner noise. The gate pins processes because the thread backend's 3.14t
anti-scaling above is an interpreter-level regime, not an llmsim regression a
gate could act on.

### Memory (RSS) guidance

Measured on the benchmark model, 3.14t thread backend: coordinator base
~30 MB; each concurrent replication adds ~3–4 MB peak RSS. The process
backend pays the interpreter base per worker instead. Free-threaded builds
carry larger object headers and a stop-the-world collector, so budget
~10–20% extra for the same model on 3.14t, and prefer
`Experiment(..., spool=True)` (zstd-compressed results, decompressed on
access) when per-replication outputs are large. Worker-count rule of thumb:
`max_workers = physical cores`, reduced if `workers × per-worker RSS`
approaches available memory.

## Phase 1 — sequential core

llmsim's Phase 1 goal is an honest single-thread win over SimPy 3 to justify the
clean break, *before* any parallelism. This note records the measured numbers
and — per the project's docs-honesty rule — the regimes where llmsim does **not**
lead.

### What is measured

Every number here is measured, never asserted. The benchmark harness
(`benchmarks/test_llmsim_benchmarks.py`) runs each of the three canonical models
on both engines, on the same machine, in the same process:

1. **KPI equivalence** — for a fixed seed, each llmsim model produces the *exact*
   same KPI as its SimPy 3 reference. llmsim reproduces SimPy 3's event ordering
   and RNG draw sequence bit-for-bit, so this is exact equality, not tolerance.
2. **Determinism** — the same seed yields the same KPI on repeated llmsim runs.
3. **Speedup** — a head-to-head, best-of-N wall-clock timing (`SimPy time /
   llmsim time`).

### Measured single-thread speedup

Representative numbers on an Apple M-series laptop (`Darwin-arm64`, CPython 3.14,
GIL build), best-of-9 wall clock. Absolute times are hardware-specific; the
**ratio** is the portable signal.

| Model | Work profile | SimPy 3 | llmsim | Speedup |
|---|---|---:|---:|---:|
| `grid_conveyor` | object-heavy (10 000 `Resource`s, ~16 k events) | ~29.4 ms | ~23.9 ms | **~1.23×** |
| `mm1_queue` | call-bound (~12 k events, thin per-event work) | ~7.9 ms | ~7.7 ms | ~1.03× |
| `machine_shop` | call-bound (preemptive repair, ~parity churn) | ~3.06 ms | ~2.99 ms | ~1.02× |

### Where llmsim leads, and where it is at parity

- **Object-heavy models lead clearly.** `grid_conveyor` allocates thousands of
  resources and events; llmsim's `__slots__`-based, minimal-garbage objects cut
  per-object memory and GC pressure, yielding ~1.23× — clearing the ≥1.2× design
  target. The advantage grows with the number of live events and resources.
- **Call-bound models run at parity.** `mm1_queue` and `machine_shop` spend most
  of their time in generator `send()`/`throw()` and `heapq` push/pop — operations
  that are *identical* in both engines (near-identical call counts: ~3.95 M vs
  ~3.98 M for `mm1_queue`). There is no 1.2× to be had there without out-running
  an inner loop that llmsim and SimPy 3 share; llmsim lands a few percent ahead
  (~1.02–1.03×), i.e. at parity with no regression.

This is why the CI gate is **tiered**: `grid_conveyor` must show a clear lead,
while the call-bound models are gated only against a meaningful regression. The
enforced CI floors carry margin below the measured ratios so the gate catches a
real regression without flaking on shared-runner timing noise: `grid_conveyor`
measures ~1.24–1.38× and is gated at ≥1.15×; `mm1_queue`/`machine_shop` measure
~1.02–1.03× locally and are gated at ≥0.85× (no meaningful regression — shared
macOS CI runners measure as low as ~0.88× on code that benches at parity
locally, so the floor sits under that noise band). The honest
summary is: **llmsim matches SimPy 3 on lightweight models and pulls ahead as
models get heavier** — exactly where the later share-nothing parallelism
(Phases 2–4) then multiplies the win across cores.

### Caveats

- Micro-benchmark timings vary with hardware, thermal state, and shared CI
  runners; the harness compares best-of-N runs of both engines on the *same*
  machine in the *same* process to keep the ratio meaningful.
- Numbers above are the GIL build. The free-threaded build (`3.14t`) carries a
  small single-thread overhead for both engines equally, so the ratio is
  preserved; the free-threaded payoff arrives in Phase 2 with parallel
  replications, not in this sequential core.
