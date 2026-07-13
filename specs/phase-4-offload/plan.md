# Plan — Phase 4.1 Compute offload

Task groups are ordered by dependency; each lands as its own commit/PR.
Group 1 is the smallest slice that is mergeable and useful on its own.

## 1. Offload event + strict slot on the inline reference mode

- `parallel/offload.py`: `OffloadEvent[T]` (`__slots__`, generic, awaitable)
  and `sim.offload(fn, *args, delay=None, strict=True, **kwargs)`; `delay`
  required iff `strict=True`, validated at the call site.
- Inline reference mode (`"inline"`, offload-local): run `fn` synchronously
  at submission on the owning thread, **capturing exceptions** and deferring
  both the result and any re-raise to the completion slot — the failure
  contract is identical to the pooled backends, so this is a valid
  sequential reference for every later trace-equivalence test.
- Strict-slot scheduling: the result event enters the heap **already
  triggered** at `sim.now + delay` with the normal `(time, priority, eid)`
  key, so ordering vs same-time events is deterministic and `step()`'s
  invariants are untouched.
- Payload validation: reuse Phase 2's `validate_factory` (importable-callable
  check, applied on every backend) and `preflight_config` as-is; the new
  work is offload-specific **args validation** — pickle preflight of
  args/kwargs on transport backends only, with actionable errors.
- Unit tests: slot timing, result value, same-time tie-breaking, exception
  captured at submission and re-raised at the slot, `delay` omitted with
  `strict=True` rejected, `delay < 0` rejected, lambda/closure payloads
  rejected; mypy/pyright strict clean.

## 2. Core seam + ExecutionBackend integration

- Core seam (`core/sim.py`): a typed, generic post-step/run-end completion
  hook that `parallel/offload.py` installs — the core never imports
  `llmsim.parallel`, and the hook adds no locks to the sequential hot path
  (it is a plain attribute checked by the owning thread between steps).
- Wire `sim.offload` to a per-`Sim` offload pool built on the Phase 2
  `ExecutionBackend` (threads / interpreters / processes, `backend="auto"`,
  plus offload-local `"inline"`), configured at `Sim` construction; lazy
  pool startup on first offload.
- Strict mode: when the event loop reaches the completion slot and the
  future is unfinished, block wall-clock on the future (only the owning
  thread touches the schedule; the future is the lone synchronization
  point).
- `strict=False`: completed futures observed via the post-step hook on the
  owning thread and delivered at the then-current simulated time; provided
  `delay` enforced as an earliest-delivery lower bound. Run-end rule: with
  non-strict offloads outstanding and the schedule empty, `run()` blocks
  for them and delivers before concluding `EmptySchedule`.
- Nested-pool rule: default to inline when the `Sim` runs inside an
  `Experiment` replication worker (explicit opt-in overrides); reject
  unverified nesting combinations with actionable errors. Includes a spike
  verifying which nestings work on 3.14 (process pools inside process
  workers, pools inside subinterpreter workers) — findings recorded in the
  docs.
- Backend conformance unit tests: identical simulated behavior — defined as
  the structured `trace.py` log plus returned values — across inline /
  thread / interpreter / process backends at worker counts
  {1, 2, 4, `os.process_cpu_count()`} for fixed seeds.

## 3. Failure, cancellation, and debug-mode semantics

- Failure: exception from `fn` is captured on the worker and re-raised in
  the waiting process at the completion slot (strict mode), wrapped with
  offload context; failure ordering is deterministic.
- Cancellation: interrupting a process waiting on an offload calls
  `Future.cancel()` — not-yet-started work cancelled, running work
  abandoned (result discarded, never delivered) — with no effect on
  simulation state. Run-end / `Sim` shutdown: pool shutdown with
  `cancel_futures=True`; pending futures cancelled, running payloads run to
  completion with results discarded; no deadlock, no leaked workers.
- `strict=False`: as-available delivery; debug mode (`Sim(debug=True)` /
  `LLMSIM_DEBUG=1`) emits a loud per-call flag identifying the call site.
- Tests: failing `fn` on every backend, interrupt-while-waiting (both
  before start and mid-execution), shutdown with in-flight offloads,
  `strict=False` debug flagging, `strict=False` delay lower bound.

## 4. Determinism test suite

- Trace-equivalence test: a model with overlapping offloads produces a
  bitwise-identical `trace.py` event log on every pooled backend at worker
  counts {1, 2, 4, `os.process_cpu_count()`} vs the inline reference,
  including an adversarial model with offload completions tied with local
  events at the same `(time, priority)`.
- Same-seed-same-result test in the same PR (roadmap cross-cutting rule),
  including offloads inside `Experiment` replications — covering the
  inline-by-default nested rule and the verified opt-in nesting
  combinations from the Group 2 spike (unverified combinations excluded).
- Randomized-latency stress: inject artificial jitter into worker execution
  time and assert traces are unchanged (strict mode's core promise).

## 5. Ceiling benchmark + honest docs

- pytest-benchmark model with N overlapping offloads per busy window:
  measure sequential sum vs parallel max, per backend, on 3.14 and 3.14t;
  record the no-overlap regime showing slowdown (dispatch overhead, zero
  concurrency).
- CI gating follows the Phase 2/3 precedent (docs/perf-notes.md): enforce
  only a catastrophic-regression floor (process backend, 2 workers,
  timing gates skipped on shared macOS runners); the full per-backend
  max-vs-sum curves are **recorded, not gated** — thread-backend scaling
  is interpreter-dependent on 3.14t.
- Document slowdown regimes alongside the feature: non-overlapping
  offloads, cheap `fn` vs dispatch cost, pure-Python `fn` on the thread
  backend under 3.14t refcount contention (per docs/perf-notes.md) —
  recommend the process backend for pure-Python payloads — and the
  hung-`fn` hazard (no timeout; the sim blocks indefinitely).
- Update the "Which parallelism do I need?" decision-tree content and tick
  roadmap step 4.1.
