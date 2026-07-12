# Performance notes — Phase 1 (sequential core)

llmsim's Phase 1 goal is an honest single-thread win over SimPy 3 to justify the
clean break, *before* any parallelism. This note records the measured numbers
and — per the project's docs-honesty rule — the regimes where llmsim does **not**
lead.

## What is measured

Every number here is measured, never asserted. The benchmark harness
(`benchmarks/test_llmsim_benchmarks.py`) runs each of the three canonical models
on both engines, on the same machine, in the same process:

1. **KPI equivalence** — for a fixed seed, each llmsim model produces the *exact*
   same KPI as its SimPy 3 reference. llmsim reproduces SimPy 3's event ordering
   and RNG draw sequence bit-for-bit, so this is exact equality, not tolerance.
2. **Determinism** — the same seed yields the same KPI on repeated llmsim runs.
3. **Speedup** — a head-to-head, best-of-N wall-clock timing (`SimPy time /
   llmsim time`).

## Measured single-thread speedup

Representative numbers on an Apple M-series laptop (`Darwin-arm64`, CPython 3.14,
GIL build), best-of-9 wall clock. Absolute times are hardware-specific; the
**ratio** is the portable signal.

| Model | Work profile | SimPy 3 | llmsim | Speedup |
|---|---|---:|---:|---:|
| `grid_conveyor` | object-heavy (10 000 `Resource`s, ~16 k events) | ~29.4 ms | ~23.9 ms | **~1.23×** |
| `mm1_queue` | call-bound (~12 k events, thin per-event work) | ~7.9 ms | ~7.7 ms | ~1.03× |
| `machine_shop` | call-bound (preemptive repair, ~parity churn) | ~3.06 ms | ~2.99 ms | ~1.02× |

## Where llmsim leads, and where it is at parity

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
~1.02–1.03× and are gated at ≥0.9× (no meaningful regression). The honest
summary is: **llmsim matches SimPy 3 on lightweight models and pulls ahead as
models get heavier** — exactly where the later share-nothing parallelism
(Phases 2–4) then multiplies the win across cores.

## Caveats

- Micro-benchmark timings vary with hardware, thermal state, and shared CI
  runners; the harness compares best-of-N runs of both engines on the *same*
  machine in the *same* process to keep the ratio meaningful.
- Numbers above are the GIL build. The free-threaded build (`3.14t`) carries a
  small single-thread overhead for both engines equally, so the ratio is
  preserved; the free-threaded payoff arrives in Phase 2 with parallel
  replications, not in this sequential core.
