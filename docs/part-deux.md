# part-deux: `llmsim` — a parallel discrete-event simulation library for Python 3.14+

**Status:** Draft plan (principal-engineer design review requested)
**Author:** Claude (with Dr. Nobel Khandaker)
**Date:** 2026-07-11
**Scope decisions (confirmed):** clean-break API (no SimPy 3 compatibility), brand-new
package named **`llmsim`**, Python **3.14+** targeting *both* the default (GIL) build and
the free-threaded (`3.14t`) build, staged delivery with parallel replications as the
flagship win.

---

## 1. Executive summary

SimPy 3.0.11 is a pure-Python, generator-driven discrete-event simulation (DES)
framework whose engine is a single `heapq` loop (`Environment.step()` in
`src/simpy/core.py`). It is inherently single-threaded and still carries Python 2.7
compatibility baggage (`_compat.py`, no type hints, `super(Cls, self)` calls, no
f-strings).

This plan designs **`llmsim`**, a new library that keeps the proven
generator-as-process model but rebuilds it for the Python 3.14 concurrency era:

1. **Phase 1 — Modern sequential core.** A clean-break, fully typed, `__slots__`-based
   engine. Expected 1.2–1.5× single-thread event throughput vs SimPy 3 on CPython
   3.14, before any parallelism.
2. **Phase 2 — Parallel replications (the flagship).** First-class Monte Carlo /
   experiment API that runs N independent simulations across cores, selecting the best
   backend at runtime: free-threaded `ThreadPoolExecutor` on `3.14t`,
   `InterpreterPoolExecutor` (PEP 734) or `ProcessPoolExecutor` on GIL builds.
   Near-linear speedup: ~6–7× on 8 cores, ~11–14× on 16 cores.
3. **Phase 3 — Single-run PDES.** Partition one large model into logical processes
   (shards) with **conservative synchronization** (lookahead / safe-window), each shard
   running its own event loop on its own core, exchanging timestamped messages through
   locked mailboxes. Model-dependent speedup: 2–8× for well-partitioned models with
   good lookahead; explicitly documented as *not* a free lunch.
4. **Phase 4 — In-run compute offload.** `yield sim.offload(fn, ...)` to run truly
   CPU-heavy event handlers (physics steps, ML inference, optimization solves) on a
   worker pool without blocking the event loop's ability to be interleaved.

Optimistic synchronization (Time Warp) is **explicitly rejected**: rollback requires
snapshotting suspended process state, and CPython cannot copy or pickle a live
generator frame. Conservative synchronization is the only sound choice for a
generator-based engine.

---

## 2. Analysis of the existing SimPy 3 engine

### 2.1 Architecture (what we keep conceptually)

Three layers, all worth preserving in spirit:

| Layer | SimPy 3 location | Core mechanism |
|---|---|---|
| Event system | `src/simpy/events.py` | `Event` with `callbacks` list, `_ok`, `_value` (sentinel `PENDING`); `Process` drives a generator via `send()`/`throw()`; `Condition`/`AllOf`/`AnyOf` composition |
| Event loop | `src/simpy/core.py` | `heapq` of `(time, priority, event_id, event)`; `step()` pops and runs callbacks; `BoundClass` descriptor makes `env.timeout(5)` construct `Timeout(env, 5)` |
| Resources | `src/simpy/resources/` | `BaseResource` with `put`/`get` request events (context managers) and the `_trigger_put`/`_trigger_get` retry chain |

### 2.2 Why it cannot be parallelized as-is

- **The loop is causally sequential.** `step()` pops the globally minimum-time event;
  its callbacks may schedule, cancel, or interrupt anything. There is no safe
  lookahead without model knowledge.
- **Synchronous mutation everywhere.** Creating a `Put` event mutates
  `resource.put_queue` and immediately runs `_trigger_put` (see
  `resources/base.py`). Events append themselves to other events' `callbacks` lists.
  Fine-grained locking here would be both incorrect (lock ordering across the
  callback graph is unknowable) and slow (locks in the hot path).
- **Shared mutable engine state.** `Environment._queue`, `_eid = count()`,
  `_active_proc` are all unsynchronized. `itertools.count` is not documented as
  atomic on free-threaded builds.
- **Generators pin state to one thread.** A suspended generator frame cannot be
  migrated safely, copied, or pickled — this kills work-stealing schedulers and
  optimistic rollback alike. (Free-threading also documents that touching another
  thread's frame objects is unsafe.)

**Conclusion:** parallelism must come from *architecture* — share-nothing environments
with explicit, narrow communication points — not from adding locks to the existing
engine.

### 2.3 Sequential inefficiencies worth fixing regardless

- No `__slots__`: every `Event` carries a dict; millions of events → GC and cache
  pressure. (SimPy 3 even manually breaks `Condition` reference cycles to help GC.)
- Attribute-lookup-heavy hot path (`event.callbacks`, `event._ok`, `event._value`).
- `BoundClass` + `bind_early` is a Python-2-era trick; on 3.14 the adaptive
  specializing interpreter makes plain methods and direct construction competitive
  and clearer.
- `Environment.exit()`/`StopProcess` exist only for pre-3.3 generators — dead code
  in a 3.14 world (`return value` in generators has worked since 3.3).

---

## 3. The Python 3.14 concurrency landscape (what we build on)

### 3.1 Free-threaded CPython (PEP 703 → PEP 779, officially supported in 3.14)

- The free-threaded build (`python3.14t`) is **officially supported** (no longer
  experimental) as of 3.14, though not the default build.
- Single-threaded overhead vs the GIL build: roughly **1% (macOS aarch64) to 8%
  (x86-64 Linux)** on pyperformance; the specializing adaptive interpreter is enabled
  in free-threaded 3.14 (it was disabled in 3.13t).
- True multi-core scaling for pure-Python CPU-bound threads (reported 2–4× on 4-core
  machines for parallel workloads).
- Runtime detection: `sys._is_gil_enabled()`; build detection:
  `sysconfig.get_config_var("Py_GIL_DISABLED")`.
- Library-author guidance (per the official free-threading HOWTO) that shapes our
  design:
  - Built-in containers have internal per-object locks, but treat that as an
    implementation detail — use explicit `threading.Lock` for invariants that span
    multiple operations.
  - **Never share iterators across threads** (can silently duplicate/drop items).
  - Never touch another thread's frame objects (`f_locals`) — reinforces
    "a generator runs only on its home thread".
  - Memory footprint is higher (immortal interned strings, larger object headers,
    mimalloc heaps, biased refcounting, QSBR-deferred frees); GC is
    stop-the-world — minimizing garbage per event matters even more.

### 3.2 Multiple interpreters in the stdlib (PEP 734, new in 3.14)

- `concurrent.interpreters` — create isolated interpreters in one process; strict
  isolation (no shared objects except immortal immutables); communication via
  `interpreters.Queue` (pickle-based) or `memoryview`-shareable buffers.
- `concurrent.futures.InterpreterPoolExecutor` — a `ThreadPoolExecutor` derivative
  where each worker thread hosts its own subinterpreter, giving **GIL-build users
  true in-process parallelism** (each interpreter has its own GIL).
- Constraints that shape our API: work submitted must be picklable / importable
  (module-level callables, not closures); per-interpreter import cost and memory
  footprint are non-trivial → the replication API must accept a *model factory
  reference*, not a live model object.

### 3.3 Other relevant 3.14 improvements

- **Tail-call interpreter**: ~3–5% average speedup — but this is a **build-time
  option of the CPython binary** (requires a new-enough Clang on x86-64/AArch64,
  typically with PGO), not a property of "Python ≥ 3.14". Users on stock
  distribution builds may or may not have it. llmsim treats it as a benchmark
  *variant* (detected and reported by the bench harness), never as a baseline
  assumption.
- **Deferred annotations (PEP 649/749)**: full typing with zero runtime cost.
- **`compression.zstd`**: cheap trace/result compression for cross-interpreter or
  cross-process result shipping.
- **Experimental JIT** available in official binaries (off by default): benchmark
  target, not a dependency.
- `concurrent.futures.ProcessPoolExecutor` fallback (forkserver default on Linux in
  3.14) remains the compatibility floor.

### 3.4 PDES theory recap (why the plan is shaped this way)

Parallel DES has a 40-year literature with exactly two families:

- **Conservative (Chandy–Misra–Bryant, safe windows):** a logical process (LP) may
  execute an event at time *t* only when no other LP can still send it a message with
  timestamp < *t*. Requires **lookahead** — a model-provided lower bound on the delay
  of any cross-LP interaction (e.g., conveyor transit time, network latency).
  Speedup is bounded by partition balance and lookahead quality.
- **Optimistic (Time Warp):** LPs execute speculatively and roll back on causality
  violations. Requires checkpointing every LP's full state. **Infeasible for
  generator-based processes in CPython** (cannot snapshot a generator frame) —
  rejected for llmsim.

llmsim therefore implements: **synchronous safe-window conservative execution**
(a barrier-based variant of CMB that avoids per-channel null-message storms), which
maps cleanly onto shared-memory threads.

---

## 4. `llmsim` design

### 4.1 Package layout

```
llmsim/
├── pyproject.toml            # PEP 621; requires-python = ">=3.14"
├── src/llmsim/
│   ├── __init__.py           # public API re-exports
│   ├── core/
│   │   ├── sim.py            # Sim (the environment/event loop)
│   │   ├── events.py         # Event[T], Timeout, Condition, AllOf, AnyOf
│   │   ├── process.py        # Process; drives generators AND coroutines
│   │   └── errors.py         # Interrupt, SimulationError, EmptySchedule
│   ├── resources/
│   │   ├── base.py           # BaseResource, Request/Release protocol
│   │   ├── resource.py       # Resource, PriorityResource, PreemptiveResource
│   │   ├── container.py
│   │   └── store.py          # Store, PriorityStore, FilterStore
│   ├── rand/
│   │   └── streams.py        # reproducible per-replication / per-shard RNG streams
│   ├── parallel/
│   │   ├── backends.py       # ExecutionBackend: threads | interpreters | processes
│   │   ├── replicate.py      # run_replications(), Experiment, ReplicationResult
│   │   ├── offload.py        # sim.offload() worker-pool integration
│   │   └── pdes/
│   │       ├── shard.py      # ShardedSim: one LP = one core-pinned event loop
│   │       ├── channel.py    # typed, lookahead-carrying inter-shard channels
│   │       └── sync.py       # safe-window barrier synchronizer (conservative)
│   ├── rt.py                 # real-time sync (wall-clock), ported last
│   └── trace.py              # structured event tracing (also powers equivalence tests)
├── tests/
├── benchmarks/               # pytest-benchmark suite; SimPy 3 parity models
└── docs/
```

### 4.2 Clean-break core API (Phase 1)

Generators remain the process primitive — they are the *right* abstraction for DES
(cheap suspension, synchronous mental model, no event-loop reentrancy hazards). The
clean break is in ergonomics and typing, not in the fundamental model:

```python
import llmsim

def customer(sim: llmsim.Sim, bank: llmsim.Resource, service_time: float):
    arrive = sim.now
    with bank.request() as req:
        yield req
        wait = sim.now - arrive
        yield sim.delay(service_time)          # `delay`, not `timeout`

sim = llmsim.Sim()
bank = llmsim.Resource(sim, capacity=2)
sim.spawn(customer, bank, service_time=5.0)    # `spawn`, not `process`
sim.run(until=100.0)
```

Key decisions:

1. **`Event[T]` is generic and `__slots__`-based.** `_value: T | _Pending`,
   `callbacks: list[Callable[[Event[T]], None]] | None`. Full static typing of what a
   `yield` returns via typed helper aliases (`ProcessGen = Generator[Event[Any], Any,
   R]`).
2. **Events are awaitable.** `Event.__await__` yields `self` once — so `async def`
   processes work with the *same* driver, because coroutines expose the same
   `send()`/`throw()` protocol as generators. No asyncio, no separate scheduler;
   users choose `yield` or `await` style per process. (This is the cheapest possible
   "modern API" win.)
3. **Drop `BoundClass`.** Plain methods (`sim.delay()`, `sim.spawn()`,
   `resource.request()`) constructing plain classes. Clearer, and the 3.14
   specializing interpreter erases the historical performance argument.
4. **Drop `StopProcess`/`exit()`** (use `return`), drop `_compat`, drop implicit
   defused-attribute tricks in favor of an explicit `defused: bool` slot.
5. **`Condition` failures carry context.** When multiple watched events fail,
   aggregate into an `ExceptionGroup` instead of racing to fail with the first one.
6. **Time is a protocol.** `SimTime = int | float` (users can choose integer ticks
   for exact arithmetic); comparisons in the heap use a precomputed sort key tuple
   `(time, priority, eid)` exactly as today — it is optimal.
7. **Scheduling stays `heapq`.** Verified best-in-class for this workload; the
   rewrite keeps `(time, priority, eid, event)` tuples with `eid` from a plain
   integer counter owned by the `Sim` (single-threaded by design — see §4.4).
8. **Per-`Sim` RNG.** `sim.rng: random.Random` seeded from the experiment's seed
   tree (§4.5). Models that use `sim.rng` are reproducible and replication-safe for
   free.

### 4.3 Thread-safety model: share-nothing by construction

The core rule, stated in docs and enforced in debug builds:

> **A `Sim` and every object attached to it (events, processes, resources) belong to
> exactly one thread at a time.** Cross-`Sim` interaction happens only through
> `llmsim.parallel` channels, which are the only locked structures in the library.

- Debug mode (`LLMSIM_DEBUG=1` or `Sim(debug=True)`): every `schedule()` asserts
  `threading.get_ident()` equals the owning thread — catching accidental sharing on
  free-threaded builds where it would otherwise silently corrupt state.
- No locks in the sequential hot path — zero overhead on both builds.
- This also sidesteps every free-threading HOWTO caveat: no shared iterators, no
  cross-thread frame access, no reliance on per-object container locks.

### 4.4 Phase 2 — Parallel replications (`llmsim.parallel.replicate`)

The 80% use case for multicore DES: stochastic studies (N replications × M parameter
configurations), confidence intervals, parameter sweeps.

```python
from llmsim.parallel import Experiment

def build_and_run(seed_stream, cfg):          # module-level: importable & picklable
    sim = llmsim.Sim(rng=seed_stream)
    model = BankModel(sim, tellers=cfg["tellers"])
    sim.run(until=8 * 60.0)
    return model.stats()                       # any picklable result

exp = Experiment(build_and_run, configs=[{"tellers": k} for k in (1, 2, 3)])
results = exp.run(replications=1000, backend="auto", max_workers=None)
```

**Backend selection (`backend="auto"`):**

| Runtime | Backend | Rationale |
|---|---|---|
| 3.14t, GIL disabled | `ThreadPoolExecutor` | Shared memory, zero serialization, cheapest workers; share-nothing `Sim`s make it safe |
| 3.14 GIL build | `InterpreterPoolExecutor` | True parallelism in-process; per-worker interpreter cost amortized over many replications |
| Fallback / user override | `ProcessPoolExecutor` | Maximum isolation; survives native-extension crashes; needed if model imports non-interpreter-safe C extensions |

Design details:

- The executor is handed **(callable-by-reference, seed spec, config)** — never live
  objects — so the same code path works on all three backends. On the thread backend
  this is trivially satisfied; the constraint exists so switching backends is a
  one-word change.
- **Result streaming:** results are yielded as they complete (`exp.iter_results()`),
  with optional zstd-compressed spooling for large per-replication traces.
- **Progress/cancellation:** backend-aware, because worker isolation differs.
  On the thread backend a shared in-memory token is checked between `step()`
  calls (cheap flag read) — mid-replication cancellation. Interpreter and
  process workers cannot see a parent-process token, so on those backends
  cancellation is at **replication granularity**: stop dispatching queued work
  and `Future.cancel()` pending submissions; in-flight replications run to
  completion. The API is one `Experiment.cancel()` with the granularity
  difference documented per backend.
- **Warm-pool reuse:** on the interpreter backend, workers import the model module
  once and run many replications, hiding PEP 734 startup cost.

### 4.5 Reproducible randomness (`llmsim.rand.streams`)

Parallel stochastic simulation is worthless without reproducible, statistically
independent streams:

- A single experiment master seed derives a **seed tree**:
  `master → (config index, replication index) → child seed`, implemented by hashing
  (SHA-256 of the path) into 128-bit seeds for `random.Random` — the stdlib
  equivalent of NumPy's `SeedSequence.spawn()` philosophy. Optional NumPy adapter
  (`Generator(Philox)`) for models that want vectorized draws.
- Scoped guarantee (stated precisely, because over-promising here is a
  scientific-validity bug): **llmsim guarantees that the same (master seed, config,
  replication) triple receives the same RNG stream and the same deterministic event
  ordering on any backend, any worker count, and any build.** End-to-end identical
  *results* follow whenever the model code itself is deterministic and
  backend-portable — which the docs define: no reliance on wall clock, unordered
  iteration of identity-keyed containers, global mutable module state (fresh per
  subinterpreter, shared under threads), or native extensions with their own
  threading/rounding behavior. Results are keyed by `(config index, replication
  index)` — never by completion order — so aggregation is order-insensitive by
  construction. The known unsupported nondeterminism sources are listed in the docs
  rather than silently absorbed into the guarantee.

### 4.6 Phase 3 — Single-run conservative PDES (`llmsim.parallel.pdes`)

For the user with *one* enormous model (a rail network, a fab, a warehouse) who wants
one run to go faster.

**Model:** the user partitions the model into `Shard`s. Each shard is a full `Sim`
running on its own thread (free-threaded build) — or, in a degraded mode, time-sliced
on the GIL build (correct but not faster; documented honestly). Shards interact only
via `Channel`s:

```python
topo = llmsim.parallel.ShardedSim(shards=8)

@topo.shard(0)
def build_station_a(sim, ports):
    out: llmsim.Channel = ports.out("a_to_b", lookahead=4.0)  # transit time ≥ 4.0
    def producer(sim):
        while True:
            yield sim.delay(rng.expovariate(1.0))
            out.send(Part(), delay=4.0)         # delay ≥ channel lookahead, enforced
    sim.spawn(producer)

@topo.shard(1)
def build_station_b(sim, ports):
    inbox = ports.inbox("a_to_b")
    def consumer(sim):
        while True:
            part = yield inbox.get()            # a Store-like endpoint, local to shard 1
            ...
    sim.spawn(consumer)

topo.run(until=10_000.0)
```

**Synchronization algorithm — barrier safe-window (conservative, YAWNS-style):**

At every barrier all shards are quiescent and all messages produced in the previous
window sit in their destination mailboxes, undelivered. Each round:

1. Every shard *i* reports `bound_i = next_i + L_i`, where `next_i` is its next
   local event time and `L_i` is the minimum lookahead over its outgoing channels
   (a shard only sends messages while executing events, so nothing it emits can
   carry a timestamp below `next_i + L_i`).
2. The coordinator computes the **global safe horizon**
   `H = min(min_i bound_i, min undelivered message timestamp)`.
3. **Delivery before execution:** every buffered message with `timestamp < H` is
   inserted into its destination shard's heap *before* the window opens. Delivery
   order is globally deterministic: messages are sorted by
   `(timestamp, channel id, per-channel sequence number)` and their heap tie-break
   keys are assigned from that sorted order.
4. Every shard executes only events with `time < H` — **strictly** less than; events
   at exactly `H` wait for the next window, because a message with timestamp equal
   to `H` may still be produced or still sit undelivered. Within the window a shard
   is pure Phase 1 sequential code (no locks); outgoing messages are buffered.
5. Barrier; repeat. Termination when `H` exceeds `until` or all heaps and mailboxes
   are empty.

**Causality invariant (normative, tested):** no event at simulation time *t*
executes on any shard until every inter-shard message with timestamp < *t* has been
delivered, and same-timestamp ordering between delivered messages and local events
is fixed by the deterministic composite key `(timestamp, priority, origin key)` —
identical to the order produced by a reference single-`Sim` execution of the same
partitioned model. Phase 3 ships an adversarial test in which cross-shard messages
land exactly at the horizon (`timestamp == H`) and at ties with local events, and
asserts bitwise trace equivalence against the sequential reference.

Why this variant:

- Barrier-based windows avoid CMB per-channel null-message storms and deadlock
  handling; on shared memory the barrier is cheap (`threading.Barrier` /
  condition variables).
- Within a window, each shard is exactly the Phase 1 sequential engine — zero locks
  in the hot path; the only synchronized structures are per-channel mailboxes
  (each a `deque` + `Lock`), touched at window edges.
- **Determinism preserved:** message delivery is sorted by `(timestamp, channel id,
  sequence number)` before insertion, so a sharded run is bit-reproducible across
  worker interleavings — and testable against reference sequential runs.

**Honest constraints, documented up front:**

- Speedup requires (a) balanced shards, (b) lookahead ≫ mean event spacing. With
  lookahead ≈ 0, `H` advances one event at a time and the sharded run is *slower*
  than sequential.
- Cross-shard interactions are message-passing only: no `yield` on another shard's
  event, no sharing a `Resource` across shards (enforced at construction).
- GIL-build note: PDES mode on the default build parallelizes only if event handlers
  release the GIL (rare in pure-Python models). `ShardedSim.run()` on a GIL build
  therefore emits a prominent warning: it runs *correctly* (time-sliced threads) but
  will not be faster than sequential. **Interpreter-backed PDES is explicitly out of
  scope for 1.0.** It is not a backend swap: subinterpreters cannot share the
  thread-mode `deque`+`Lock` mailboxes, live `Sim`s, or channel endpoints, so it
  requires its own design — importable (picklable) shard-builder references, a
  cross-interpreter channel identity scheme, serialized message framing that
  preserves the deterministic `(timestamp, channel id, sequence)` ordering, and its
  own equivalence and performance gates. That design is a post-1.0 document; on
  1.0 GIL builds, the answer for parallel single-run speed is "use the free-threaded
  build" — stated plainly in the docs.

### 4.7 Phase 4 — In-run compute offload (`sim.offload`)

For models where individual events are CPU-heavy (physics, routing solvers,
ML-driven agents):

```python
def machine(sim, part):
    result = yield sim.offload(expensive_quality_model, part.features)
```

- `offload()` returns an `Event[T]` completed by a worker pool; on the free-threaded
  build the workers are threads (shared memory — zero copies of `part.features`);
  on GIL builds an interpreter/process pool with pickling.
- **Deterministic completion slot.** At issue time, the completion event is
  *scheduled normally* at `sim.now + sim_duration` (default `0`) with an event id
  assigned immediately — it occupies a fixed, reproducible position in the event
  order regardless of how long the worker actually takes. `strict=True` (default):
  when the loop reaches that slot and the worker has not finished, the loop
  **blocks on wall-clock time** until it does. Simulated order is therefore
  identical to a hypothetical inline execution; there is no retroactive insertion
  and no completion-timing-dependent ordering.
- **Where the speedup actually comes from (stated honestly):** strict offload does
  *not* let unrelated simulation events "run in the background" — it parallelizes
  **concurrent offloads**: N processes issuing offloads at the same simulation time
  (or within the same `sim_duration` span) fan out across N workers and the loop
  blocks only for the slowest (max instead of sum of wall-clock costs). A model
  with one heavy handler at a time gains nothing.
- `strict=False` opts out of determinism for throughput: the completion event is
  scheduled at whatever `sim.now` holds when the worker finishes. Documented as
  incompatible with trace-equivalence testing; `Sim(debug=True)` flags it.
- Failure/cancellation semantics are defined up front: a worker exception fails the
  event (normal failed-event propagation into the waiting process); interrupting
  the waiting process cancels delivery but not the worker task (best-effort
  `Future.cancel()` first).
- Amdahl-bound: valuable exactly when per-event compute dominates event dispatch
  *and* offloads overlap; the docs include the max-vs-sum model above so users can
  estimate their ceiling before adopting it.

### 4.8 Real-time mode (`llmsim.rt`)

Port of `RealtimeEnvironment` (wall-clock-synchronized `step()`), rebuilt on
`time.monotonic()` — trivial, scheduled last; also gains `sim.offload` synergy for
hardware-in-the-loop uses.

---

## 5. Expected speedups (and what we will not promise)

| Improvement | Mechanism | Expected gain | Confidence |
|---|---|---|---|
| Sequential core rewrite | `__slots__`, leaner hot path, no descriptor tricks, fewer temporaries | 1.2–1.5× event throughput vs SimPy 3 on same interpreter | High (measure in Phase 1) |
| CPython 3.14 tail-call interpreter | Opt-in binary build feature (Clang, PGO) — benchmark variant, **not** counted in baselines or exit criteria | +3–5% where the user's binary has it | Conditional (build-dependent) |
| Free-threaded single-thread cost | PEP 703 runtime overhead | −1% to −8% (recovered many times over by parallel phases) | High (documented) |
| **Parallel replications, 3.14t threads** | N share-nothing `Sim`s, no serialization | ~0.75–0.9 × cores → **6–7× @ 8 cores, 11–14× @ 16** (memory-bandwidth limited) | High |
| Parallel replications, GIL build via interpreters | Per-worker subinterpreter | Similar CPU scaling minus per-worker memory (tens of MB) and pickle cost of results | Medium-high |
| Single-run PDES (Phase 3) | Conservative safe-window over shards | **2–8×** on well-partitioned, high-lookahead models; ≤1× (slowdown) on tightly coupled ones | Medium — inherently model-dependent |
| Compute offload (Phase 4) | Worker pool for heavy handlers | Amdahl-bound: ≈ cores × (compute fraction); e.g. 80% compute @ 8 workers → ~3.3× | Medium |
| Experimental 3.14 JIT | `PYTHON_JIT=1` benchmark configuration | 0–10%, tracked not relied upon | Low |

Non-goals we will state in the README to protect users from disappointment:

- No optimistic/Time Warp execution (impossible to snapshot generator frames).
- No automatic parallelization of an unpartitioned model.
- No speedup promise for PDES mode without measured lookahead; ship
  `llmsim.parallel.pdes.analyze()` to *estimate* achievable parallelism from a
  sequential trace (critical-path analysis) before users invest in partitioning.

---

## 6. Delivery plan

### Phase 0 — Scaffolding (week 1)
- New repo/package `llmsim`; `pyproject.toml` (PEP 621), `requires-python = ">=3.14"`.
- CI matrix from day one: `{3.14, 3.14t, 3.15-dev} × {Linux, macOS}`, plus a
  `PYTHON_GIL=0`/`=1` axis on 3.14t; lint (ruff), type-check (mypy + pyright strict),
  `pytest`.
- Benchmark harness (pytest-benchmark) with three canonical models: M/M/1 queue,
  SimPy's machine-shop example, and a 100×100 grid conveyor network (the PDES
  stress model). Record SimPy 3 baselines on the same machines.

### Phase 1 — Sequential core (weeks 2–5)
- `core/events.py`, `core/sim.py`, `core/process.py` per §4.2; generator **and**
  coroutine process support behind one driver.
- Resources layer port (request/release, container, stores) with the same trigger
  semantics, minus `BoundClass`.
- Thread-ownership debug assertions (§4.3).
- Structured tracing (`trace.py`) — needed by Phase 3 equivalence tests, cheap to
  add now.
- **Exit criteria:** SimPy 3 behavioral test suite (ported: ~150 tests) green;
  ≥1.2× event-throughput vs SimPy 3 on 3.14; zero-regression on 3.14t.

### Phase 2 — Replications + RNG streams (weeks 6–8)
- `rand/streams.py` seed tree; `parallel/backends.py`; `parallel/replicate.py`.
- Backend conformance test: identical result sets across all three backends for a
  fixed seed (validates §4.5 guarantee).
- Scaling benchmark: replication throughput vs worker count on 3.14t and GIL builds;
  publish the curves in docs.
- **Exit criteria:** ≥6× replication throughput on 8 physical cores (3.14t);
  identical numerics across backends.

### Phase 3 — Conservative PDES (weeks 9–16, the research-grade phase)
- `Channel`/mailbox, `ShardedSim`, barrier safe-window synchronizer, lookahead
  enforcement, deterministic message ordering.
- `pdes.analyze()` critical-path estimator from sequential traces.
- Equivalence testing: sharded grid-conveyor trace ≡ sequential trace (bitwise, via
  `trace.py`) across 1/2/4/8 shards — including the adversarial horizon-boundary
  model (§4.6): cross-shard messages timestamped exactly at `H` and tied with local
  events.
- Stress: thread-sanitizer-style soak runs on 3.14t (long runs under `pytest-repeat`
  with randomized barriers) since free-threading bugs are schedule-dependent.
- **Exit criteria:** ≥3× on the grid-conveyor model @ 8 shards with lookahead = 4×
  mean event spacing; documented slowdown curve as lookahead → 0.

### Phase 4 — Offload + RT + polish (weeks 17–19)
- `parallel/offload.py`, `rt.py`, docs site, migration guide *from* SimPy 3
  (concept mapping table: `env.process` → `sim.spawn`, `env.timeout` → `sim.delay`,
  etc.).
- 1.0 API freeze review.

### Cross-cutting workstreams
- **Determinism:** every parallel feature ships with a same-seed-same-result test.
- **Memory:** track RSS per replication on 3.14t (free-threading's larger headers +
  mimalloc fragmentation); document worker-count guidance for memory-constrained
  hosts.
- **Docs honesty:** a "Which parallelism do I need?" decision tree is the first page
  of the parallel docs.

---

## 7. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Free-threaded ecosystem gaps (C extensions in user models not `Py_mod_gil` ready) | Import forces GIL re-enable on 3.14t → silent loss of parallelism | Detect via `sys._is_gil_enabled()` *after* model import inside workers; warn loudly; interpreter/process backends as fallback |
| PEP 734 pickling constraints surprise users (closures, lambdas as model factories) | Runtime errors on interpreter backend | Validate factory importability at `Experiment` construction with actionable error; thread backend unaffected |
| Stop-the-world GC pauses on 3.14t with many worker threads | Throughput jitter | Low-garbage core (`__slots__`, tuple reuse); expose `gc.freeze()` guidance post-warmup; benchmark GC pause impact in Phase 2 |
| PDES adoption failure (users can't find lookahead) | Phase 3 underused | `pdes.analyze()` sets expectations from a sequential trace *before* users invest; replications remain the headline feature |
| Barrier synchronizer scalability beyond ~16 shards | Coordination overhead dominates | Acceptable for 1.0 (target: single multicore machines, 8–32 cores); tree-barriers or CMB-hybrid as post-1.0 work |
| 3.14t behavior differences across point releases (young, officially-supported-but-evolving build) | CI churn | Pin CI to latest 3.14.x + 3.15-dev canary; subscribe to free-threading release notes |
| Determinism bugs (parallel result ≠ sequential) | Scientific validity — worst possible bug class | Bitwise trace-equivalence tests in CI for every parallel mode; seed-tree unit tests; deterministic message ordering by construction |

---

## 8. Validation strategy

1. **Behavioral parity:** port SimPy 3's test suite (tests/, ~150 tests) to the new
   API as the Phase 1 acceptance gate — it encodes 15 years of DES semantics
   (interrupt edge cases, condition composition, preemption, store filtering).
2. **Trace equivalence:** `trace.py` canonical event logs; sequential vs sharded vs
   offload-strict runs must match bitwise for fixed seeds.
3. **Cross-backend equivalence:** replication result sets identical across
   thread/interpreter/process backends.
4. **Property-based testing:** Hypothesis strategies generating random
   process/resource graphs; invariants: no event executes before its schedule time,
   monotonic `sim.now` per shard, conservation laws in stores/containers.
5. **Concurrency soak:** long randomized runs on 3.14t in CI (schedule-dependent bug
   hunting); assertions-on debug build.
6. **Performance regression gates:** pytest-benchmark thresholds in CI for the three
   canonical models; scaling-curve artifacts published per release.

---

## 9. References

- Python 3.14 free-threading HOWTO — https://docs.python.org/3/howto/free-threading-python.html
- PEP 779 (free-threading officially supported) / PEP 703 (make the GIL optional)
- PEP 734 — `concurrent.interpreters` — https://docs.python.org/3.14/library/concurrent.interpreters.html
- What's new in Python 3.14 — https://docs.python.org/3.14/whatsnew/3.14.html
- Fujimoto, R. — *Parallel and Distributed Simulation Systems* (conservative vs
  optimistic synchronization, lookahead)
- Chandy & Misra (1979); Bryant (1977) — conservative null-message algorithm
- Jefferson (1985) — Virtual Time / Time Warp (evaluated, rejected for
  generator-state reasons)
- SimPy 3.0.11 sources in this repository (`src/simpy/`) — architectural baseline
