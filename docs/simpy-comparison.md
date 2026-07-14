# Why llmsim will outperform SimPy — implementation-plan vs. current SimPy master

**Baseline reviewed:** SimPy **4.1.2** (GitLab `team-simpy/simpy` master, commit
`f438164`, 2026-05-23) — not the SimPy 3.0.11 snapshot referenced in
`docs/part-deux.md`. SimPy 4 already added full type hints and dropped the
Python 2 `_compat` layer, so those are *not* llmsim differentiators. Everything
below compares llmsim's plans (`specs/`, `docs/part-deux.md`) against what is
actually in SimPy master today.

This page argues *why* to migrate; for the *how* — a concept-by-concept
mapping with worked model ports — see
[Migrating from SimPy 3](migration-from-simpy.md).

## Where SimPy master stands

- **Engine:** one single-threaded `heapq` loop — `Environment.step()` pops
  `(time, priority, eid, event)` tuples and runs callbacks
  (`src/simpy/core.py`). Architecturally unchanged from SimPy 3.
- **Python floor:** `requires-python = ">= 3.8"`. SimPy cannot use
  free-threaded CPython idioms, PEP 734 subinterpreters, PEP 649 deferred
  annotations, or `compression.zstd` *unconditionally* — adopting them would
  mean either raising the floor past six minor versions of users or
  maintaining version-gated dual code paths, neither of which the project
  shows any movement toward.
- **No `__slots__` anywhere:** every `Event` carries an instance `__dict__`;
  `defused` is tracked by attribute *presence* (`hasattr(self, '_defused')`)
  rather than an explicit boolean field. `Condition` manually strips
  callbacks to break reference cycles — evidence of real GC pressure at scale.
- **Hot path built on inherited tricks** (what llmsim's plan calls
  "Python-2-era" idioms, `docs/part-deux.md` §2.3): the `BoundClass`
  descriptor (`core.py:41`) plus hand-inlined copies of `Event.__init__` in
  `Timeout`, `Initialize`, `Interruption`, *and* `Process` ("for performance
  reasons", `events.py`) — micro-optimizations at the ceiling of what the
  current architecture allows.
- **Zero parallelism support** (SimPy's "concurrency" is simulated process
  interleaving on one thread): no `threading`/`concurrent.futures` import in
  the engine; no replication/experiment API; no managed RNG (models seed
  `random` themselves); unsynchronized shared engine state
  (`_queue`, `_eid = itertools.count()`, `_active_proc`) and synchronous
  queue mutation in `resources/base.py` (`_trigger_put`/`_trigger_get` retry
  chains) make retrofitting threads onto it both unsafe and, with locks,
  slow.

## How llmsim's plan wins

### 1. Sequential core: modest, measured, structural (planned 1.2–1.5×)

The plan (roadmap Phase 1) removes per-event costs SimPy cannot remove without
breaking its compatibility floor: `__slots__` on all hot-path classes (no
per-event dict allocation, better cache locality, less GC), an explicit
`defused: bool` slot instead of `hasattr`, plain methods instead of
`BoundClass` descriptors (the 3.14 specializing interpreter makes direct
construction competitive), a plain integer counter instead of
`itertools.count`, and PEP 649 annotations at zero runtime cost. The claim is
deliberately conservative — 1.2–1.5× event throughput, gated in CI against
three canonical models (M/M/1, machine shop, grid conveyor). SimPy baselines
are recorded first in Phase 0.4; the ≥1.2× threshold is Phase 1's exit
criterion.

### 2. Parallel replications: the headline speedup SimPy doesn't offer (planned 6–14×)

SimPy has no experiment layer; users hand-roll `multiprocessing`, paying
process spawn + pickle costs and inventing their own seed management. llmsim's
`Experiment.run(backend="auto")` (Phase 2) runs N independent simulations
across cores with runtime backend selection: free-threaded
`ThreadPoolExecutor` on 3.14t (shared memory, zero serialization),
`InterpreterPoolExecutor` (PEP 734) on GIL builds (true in-process
parallelism, warm-pool amortized imports), `ProcessPoolExecutor` as the
floor. Exit criterion: ≥6× replication throughput on 8 physical cores on
3.14t, with identical numerics across all three backends (a guarantee the
plan scopes precisely: same RNG stream and event ordering per
(master seed, config, replication) triple; identical end-to-end results
follow for deterministic, backend-portable model code). This is where
"6–14× on hardware you already own" comes from — architecture (share-nothing
`Sim`s), not interpreter magic.

### 3. GIL-free correctness by construction, not retrofit

SimPy's engine could run under free-threaded CPython, but nothing in it is
designed for it, and one `Environment` can never use a second core. llmsim's
normative rules (tech-stack "Technical constraints") — one thread owns a `Sim`
and everything attached to it, zero locks in the sequential hot path, locked
structures only in `parallel` channels touched at safe-window edges,
generators pinned to their home thread — mean free-threading adds parallelism
*between* simulations without taxing the code *inside* one. Debug builds
assert thread ownership on every `schedule()`, converting silent corruption
into loud failure.

### 4. Single-run PDES and compute offload: speedups with stated limits

For one large model, sharded conservative (YAWNS-style safe-window) execution
targets ≥3× at 8 shards on the grid-conveyor gate model (Phase 3), with
bitwise trace-equivalence to the sequential reference as a merge gate, and
`pdes.analyze()` to predict achievable speedup before users invest.
`sim.offload()` (Phase 4) parallelizes concurrent CPU-heavy handlers
(max-instead-of-sum wall-clock cost) with a deterministic completion slot.
Neither exists as a first-class capability in SimPy; users can only
approximate them by orchestrating whole SimPy runs from outside the engine,
which gives up in-run parallelism and deterministic cross-shard ordering.

### 5. Reproducibility that makes the parallelism usable

Parallel speed is worthless for stochastic studies if results are not
reproducible. The SHA-256 seed tree (Phase 2.1) guarantees the same
(master seed, config, replication) triple gives the same stream and event
ordering on any backend, worker count, or build — a guarantee SimPy does not
attempt (it manages no RNG at all). Identical end-to-end *results* are
guaranteed only for models that are themselves deterministic and
backend-portable; the plan documents the unsupported nondeterminism sources
rather than silently absorbing them.

## Honest caveats (per mission principle 3)

- All multipliers above are *planned exit criteria*, not measurements; nothing
  is implemented yet, and Phase 0.4 exists precisely to record real SimPy
  baselines first.
- The roadmap's benchmark models and baselines are written against "SimPy 3";
  since GitLab master is now 4.1.2 (same engine architecture, but the live
  competitor), Phase 0.4 should record its baselines against current SimPy —
  this document's source review does not by itself validate the multipliers
  against 4.1.2.
- Replication scaling is not literally linear per core: the plan itself
  estimates ~0.75–0.9× per core (memory-bandwidth limited), which is where
  6–7× at 8 cores and 11–14× at 16 cores come from.
- The free-threaded build itself costs roughly 1–8% single-thread overhead;
  llmsim's sequential-core claim is made against the *default* 3.14 build.
- PDES speedup is model-dependent (needs balanced shards and lookahead ≫ mean
  event spacing); GIL-build PDES is documented as correct but not faster.
- SimPy's maturity, ecosystem, and 3.8+ reach remain real advantages; llmsim
  trades that reach for the 3.14 concurrency features that make its speedups
  possible.

**Bottom line:** SimPy master remains, by deliberate design, a maximally
compatible single-threaded engine; its own source shows it optimizing at the
margin (inlined constructors, descriptor tricks) within that constraint.
llmsim's plan wins on performance not by out-micro-optimizing SimPy but by
changing the constraint: a 3.14-only, `__slots__`-based, share-nothing
architecture where the sequential engine gets structurally cheaper (1.2–1.5×)
and — the real prize — additional cores multiply throughput at ~0.75–0.9×
efficiency per core (6–14× for replication studies; 2–8× for well-partitioned,
high-lookahead single runs), with reproducibility enforced in CI.
