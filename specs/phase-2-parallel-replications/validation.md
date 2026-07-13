# Validation — Phase 2: Parallel replications + reproducible randomness

## Success criteria

The acceptance gate is the roadmap's Phase 2 exit-criteria bundle plus the
seed-tree correctness tests:

1. **Backend conformance: identical numerics across all three backends.** For
   fixed seeds, the `thread`, `interpreter`, and `process` backends produce
   result sets equal to each other and to the sequential Phase 1 reference, on
   the canonical models — the concrete proof of the reproducibility guarantee.
2. **Scaling: ≥6× replication throughput on 8 physical cores (3.14t).** Measured
   and validated in an 8+-physical-core environment. Because standard CI runners
   have only 2–4 cores, the **CI-enforced** gate is a **parallel-efficiency
   threshold** meaningful at the runner's core count (e.g. ≥0.75× per-core
   efficiency vs the sequential baseline at `max_workers = os.cpu_count()`); the
   headline ≥6×-on-8-cores figure is recorded from an 8+-core run in the docs
   (docs-honesty rule), not asserted on small runners.
3. **Seed tree: deterministic, distinct, stable streams.** Known-answer tests pin
   the canonical path serialization and derived child seeds for fixed triples; no
   child-seed collisions occur over a specified sample; the same triple yields the
   same pinned first-N draws across runs, platforms, and builds; and a bounded
   statistical smoke test (explicit, generous thresholds) rules out a grossly
   biased derivation. ("Statistical independence" is claimed only to the extent
   these testable proxies establish it.)
4. **Determinism: same-seed-same-result across backends, worker counts, and
   builds.** The same explicit `(master seed, config, replication)` triple produces
   an identical result regardless of backend, `max_workers`, or GIL/free-threaded
   build, for a deterministic model. Two `run`s with the same `master_seed` and
   inputs return identical keyed result sets.
5. **Types/lint clean; required CI matrix green.** `mypy --strict` and `pyright`
   strict both pass on the new public API (`Experiment`, `ReplicationResult`,
   `run_replications`, the seed-tree types) and internals; `ruff check` and
   `ruff format --check` pass. The **required** gates are **3.14 and 3.14t only**
   (× `{Linux, macOS}`, plus the `PYTHON_GIL=0/1` axis on 3.14t); `3.15-dev` runs
   as a **non-blocking canary** (`continue-on-error`), so dev-interpreter churn
   cannot block Phase 2.

## Checklist

- [ ] `rand/streams.py`: canonical-path known-answer tests, no child-seed
      collisions over the sample, pinned first-N draw literals (stable across
      runs/platforms/builds), same-seed-same-result, and the bounded statistical
      smoke test all pass.
- [ ] `parallel/backends.py`: each of thread/interpreter/process runs a trivial
      importable task to identical results; `backend="auto"` resolves to
      **threads on 3.14t** and **processes on the GIL build**; the
      factory-importability validation raises the documented actionable error on
      a closure/lambda/local function; an **unpicklable config** and an
      **unpicklable result** each raise the documented actionable error (naming
      the offending `(config, replication)`) on the process/interpreter backends.
- [ ] `parallel/replicate.py`: the **explicit `master_seed`** is required (no
      ambient default); M configs × N replications yield M×N results keyed by
      `(config index, replication index)`; two runs with the same `master_seed`
      and inputs return identical keyed result sets; results are independent of
      completion order (shuffle-safe); `run_replications(...)` wrapper works.
- [ ] `exp.iter_results()`: every result is yielded exactly once; aggregation is
      order-insensitive.
- [ ] Cancellation: `Experiment.cancel()` stops further dispatch; a
      cancellation-handle-aware factory is cancelled mid-replication on the thread
      backend, while a factory that owns its own `sim.run()` is cancelled at
      replication granularity; interpreter/process backends cancel at replication
      granularity; already-collected results stay consistent; the per-backend
      granularity difference is documented.
- [ ] zstd spooling (opt-in, but implemented in Phase 2): when enabled, spooled
      results round-trip bit-identically; interpreter warm-pool reuse runs many
      replications per worker.
- [ ] **Backend conformance**: `thread`/`interpreter`/`process` result sets are
      asserted equal to each other and to the sequential reference on the
      canonical models, on 3.14 and 3.14t (`PYTHON_GIL=0/1`).
- [ ] GIL re-enable after model import in a worker is detected and warned about,
      naming the offending import.
- [ ] `benchmarks/`: replication-throughput-vs-worker-count curves recorded on
      3.14t and the GIL build; CI parallel-efficiency gate green at the runner's
      core count; ≥6×-on-8-cores figure recorded from an 8+-core run.
- [ ] `docs/`: "Which parallelism do I need?" decision-tree page wired into the
      mkdocs nav; RSS-per-replication and worker-count guidance published; the
      unsupported-nondeterminism-sources list documented.

## Done when

Backend-conformance tests confirm identical numerics across the thread,
interpreter, and process backends (and the sequential reference) for fixed seeds;
the seed-tree known-answer/no-collision/stability tests and same-seed determinism
tests pass; the CI parallel-efficiency gate is green with the
≥6×-on-8-physical-cores figure recorded from an 8+-core run; and all
lint/type/format gates are clean on the **required** matrix (3.14 and 3.14t ×
{Linux, macOS} + the `PYTHON_GIL=0/1` axis). A `3.15-dev` canary failure does not
block acceptance.
