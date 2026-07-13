# Validation — Phase 4.1 Compute offload

## Success criteria

- **Trace equivalence (strict mode):** a model using `sim.offload` produces a
  bitwise-identical structured trace on every pooled backend (threads,
  interpreters, processes) at worker counts {1, 2, 4,
  `os.process_cpu_count()`} vs the inline reference mode — the roadmap exit
  criterion for 4.1.
- **Same-seed-same-result:** identical results for a fixed
  (master seed, config, replication) with offloads enabled, including offloads
  running inside `Experiment` replications under the inline-by-default nested
  rule (cross-cutting roadmap rule).
- **Defined failure/cancellation semantics:** exception delivery at the
  completion slot, interrupt-while-waiting (before start and mid-execution),
  and shutdown-with-in-flight-work behave exactly as pinned in
  requirements.md (`Future.cancel()` + `shutdown(cancel_futures=True)`,
  results of abandoned work never delivered), on every backend, with no
  deadlock and no leaked workers.
- **Non-strict delivery is well-defined:** `strict=False` results are
  observed only by the owning thread via the post-step hook, respect a
  provided `delay` as an earliest-delivery lower bound, and are never
  silently dropped — `run()` delivers outstanding results before concluding
  `EmptySchedule`.
- **Measured ceiling + honest docs:** the max-vs-sum ceiling benchmark is
  recorded per backend on 3.14 and 3.14t; CI enforces only the
  catastrophic-regression floor (process backend, 2 workers, per the
  Phase 2/3 precedent); the slowdown regimes (no-overlap, cheap payloads,
  pure-Python thread-backend contention, hung `fn`) are documented in the
  same PR.

## Checklist

- [ ] Unit tests: slot timing, tie-breaking at equal `(time, priority)`,
      payload validation errors (lambda/closure rejected on every backend;
      unpicklable args rejected on transport backends only), `delay`
      omitted with `strict=True` rejected, negative `delay` rejected.
- [ ] Inline reference mode captures `fn` exceptions at submission and
      re-raises at the slot — identical failure contract to pooled backends.
- [ ] Backend conformance test: identical structured trace and returned
      values across inline / thread / interpreter / process backends at
      worker counts {1, 2, 4, `os.process_cpu_count()`} for fixed seeds.
- [ ] Trace-equivalence suite green, including the adversarial
      slot-tied-with-local-event model and randomized worker-latency jitter.
- [ ] Failure tests: raising `fn` on every backend delivers the exception at
      the slot with deterministic ordering.
- [ ] Cancellation tests: interrupt-while-waiting (not-started and
      mid-execution) and `Sim` shutdown with in-flight offloads; abandoned
      results never delivered; no deadlocks, no leaked workers (pytest
      process exits cleanly).
- [ ] `strict=False` tests: post-step delivery on the owning thread only,
      `delay` lower bound honored, run-end drain delivers outstanding
      results before `EmptySchedule`, debug-mode flagging
      (`Sim(debug=True)` and `LLMSIM_DEBUG=1`).
- [ ] Nested-pool tests: inline default inside `Experiment` workers; the
      Group 2 spike's verified opt-in combinations pass conformance;
      unverified combinations rejected with actionable errors.
- [ ] Same-seed-same-result test with offloads inside `Experiment`.
- [ ] pytest-benchmark ceiling model committed; catastrophic-regression
      floor gated in CI (process backend, 2 workers, macOS timing skips per
      perf-notes precedent); full max-vs-sum and no-overlap curves recorded
      for 3.14 and 3.14t.
- [ ] Slowdown regimes documented (docs page/perf-notes) in the same PR,
      including the hung-`fn` hazard.
- [ ] `uv run ruff check`, `uv run ruff format`, `uv run mypy --strict`,
      `uv run pyright`, and `uv run pytest` all green across the CI matrix
      (including `PYTHON_GIL=0/1` on 3.14t).
- [ ] Roadmap step 4.1 checked off.

## Done when

The strict-mode trace-equivalence suite and the same-seed-same-result test
pass on all pooled backends at the enumerated worker counts on the full CI
matrix, with the ceiling benchmark recorded (floor-gated only) and the
slowdown-regime docs merged in the same PR.
