# Requirements — Phase 4.1 Compute offload

## Context

Roadmap step **4.1** rounds out the parallel story before the 1.0 freeze:
`parallel/offload.py` gives event handlers a way to run CPU-heavy functions on
a worker pool (`yield sim.offload(fn, ...)`) without breaking the determinism
guarantee that is llmsim's core correctness requirement (mission principle 2).
The mechanism is the **deterministic completion slot**: the offload result is
delivered at a simulated time fixed by the model, never by how long the
computation actually took, so same-seed-same-result holds even though
wall-clock work happens in parallel. Phases 2–3 supplied the machinery this
step reuses — the `ExecutionBackend` abstraction, the seed tree, and
structured tracing for equivalence testing.

## Scope

In:

- `sim.offload(fn, *args, delay=None, strict=True, **kwargs)` returning an
  awaitable offload event. `delay` is **required iff `strict=True`** (the
  completion slot is `sim.now + delay`; omitting it raises immediately).
  Under `strict=False`, an omitted `delay` means deliver-as-available and a
  provided `delay` is an earliest-delivery lower bound (never delivered
  before `sim.now + delay`).
- `strict=True` (default): the result event enters the heap **already
  triggered** at the completion slot with the normal `(time, priority, eid)`
  key, so `step()`'s invariants and ordering vs same-time events are
  untouched; if the computation has not finished when the event loop reaches
  that simulated time, the loop **blocks wall-clock** at the slot until it
  has. Simulated order is identical to the sequential reference in all cases.
- `strict=False` opt-out: completed futures are observed **only by the
  owning thread**, via a post-step completion hook (no callbacks fire on
  worker threads), and results are delivered at the then-current simulated
  time — nondeterministic ordering is possible and every `strict=False`
  offload is flagged loudly by debug mode (`Sim(debug=True)` /
  `LLMSIM_DEBUG=1`). **Run-end rule:** if the schedule empties while
  non-strict offloads are outstanding, `run()` blocks wall-clock for them
  and delivers their results before concluding the schedule is empty — a
  result is never silently dropped.
- An **inline reference mode** (`"inline"`, offload-local — accepted
  alongside the three `ExecutionBackend` names, not an extension of the
  Phase 2 `BackendName` literal): runs `fn` synchronously on the owning
  thread at submission, delivering results at the completion slot. It is
  the sequential reference for trace-equivalence testing and the default
  when the `Sim` itself runs inside an `Experiment` worker.
- Worker-pool integration through the Phase 2 `ExecutionBackend` abstraction
  (threads / interpreters / processes, `backend="auto"`), configured per
  `Sim`. **Nested-pool rule:** inside an `Experiment` replication worker the
  offload backend defaults to inline — pooled offload inside workers is
  explicit opt-in, preventing nproc×nproc oversubscription; untested nesting
  combinations (e.g. pools inside subinterpreter workers) are rejected with
  actionable errors until verified.
- Defined failure semantics: an exception raised by `fn` is captured on the
  worker and re-raised into the waiting process **at the completion slot**
  (strict mode), preserving deterministic ordering of failures. The inline
  mode captures exceptions identically — nothing propagates at submission.
- Defined cancellation semantics: interrupting a process waiting on an
  offload calls `Future.cancel()` — not-yet-started work is cancelled;
  already-running work is abandoned (its result or exception is discarded,
  never delivered) — with no effect on simulation state. At run end /
  `Sim` shutdown the pool is shut down with `cancel_futures=True`: pending
  futures are cancelled, running payloads run to completion and their
  results are discarded. A non-terminating `fn` cannot be interrupted on
  any backend; it blocks strict-mode progress and shutdown indefinitely
  (no timeout in 1.0) — documented as a failure regime per the
  docs-honesty rule.
- Trace-equivalence test (strict mode ≡ inline reference, bitwise) and
  same-seed-same-result tests across the inline mode and all three pooled
  backends.
- Measured **max-vs-sum ceiling** benchmark and documented slowdown regimes
  (non-overlapping offloads, small `fn` cost vs dispatch overhead, pure-Python
  `fn` on the thread backend under 3.14t refcount contention, the hung-`fn`
  hazard).

Out:

- Real-time mode (`rt.py`) — roadmap step 4.2, a separate spec; offload/RT
  synergy is documented there, not here.
- Migration guide, docs site, and 1.0 freeze review (steps 4.3–4.5).
- Offloading to remote machines — 1.0 targets single multicore hosts.
- Work-stealing or migrating generators to the pool — only plain callables are
  offloaded; generators pin to their home thread (normative constraint 4).
- Async `fn` payloads (coroutines as offload targets); offload takes plain
  callables only.
- Offload timeouts / forcible termination of running payloads — infeasible to
  do portably across the three executors; revisit post-1.0.

## Decisions

- **Executor: reuse `ExecutionBackend`** (user decision). Offload submits to
  the same thread/interpreter/process abstraction as `Experiment`, selected
  per `Sim` with `backend="auto"`. One code path, and users can choose
  processes to dodge the measured 3.14t thread anti-scaling for pure-Python
  CPU work. The inline reference mode is offload-local and does not modify
  the Phase 2 `BackendName` literal or `ExecutionBackend` API.
- **Payload rule**: the **importable-callable** check (Phase 2
  `validate_factory`) applies on every backend — lambdas, closures, and
  locals are rejected everywhere, keeping backends interchangeable
  (normative constraint 5). **Pickleability of args is preflighted on
  transport backends only** (interpreters/processes), matching Phase 2's
  `preflight_config` precedent; the thread backend passes args by live
  reference with no per-call pickle round-trip (hot-path discipline,
  constraint 6). The thread-backend caveat — args must not be `Sim`-owned
  mutable state (constraint 1, thread ownership) — is documented, with
  debug mode as the guardrail.
- **`delay` is model-provided**: `delay: float | None = None`, required iff
  `strict=True`; the completion slot must be a pure function of model state,
  analogous to PDES lookahead. There is no "auto" slot derived from
  wall-clock measurement — that would break determinism by construction.
  Under `strict=False` a provided `delay` is an earliest-delivery lower
  bound.
- **Minimal, generic core seam**: `core/sim.py` gains a typed
  post-step/run-end completion hook that `parallel/offload.py` installs;
  the core never imports `llmsim.parallel` (stdlib-only layering), gains no
  locks (constraint 2), and strict-mode slot events enter the heap already
  triggered so `step()`'s "only triggered events are scheduled" invariant
  is preserved.
- **Results cross threads only through the offload future**: the worker
  returns a value; only the `Sim`-owning thread touches the event, the
  waiting process, and the schedule (constraints 1–2 — the future is the
  lone synchronization point, and it lives in `llmsim.parallel`).
- **Stdlib-only**: `concurrent.futures` for pools, no new dependencies
  (tech-stack rule).
- **Honest-performance obligations**: the max-vs-sum ceiling (parallel time
  per busy window is the *max* of overlapping offloads vs the sequential
  *sum*) is measured per backend, and the slowdown regimes (no-overlap,
  cheap payloads, thread-backend contention, hung `fn`) are documented in
  the same PR (mission principle 3; roadmap cross-cutting rules).
