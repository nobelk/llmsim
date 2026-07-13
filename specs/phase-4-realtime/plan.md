# Plan — Phase 4.2 Real-time mode

Task groups are ordered by dependency; each lands as its own commit/PR.
Group 1 is the smallest viable slice that is mergeable on its own.

## 1. Pacing driver with injectable clock

- `rt.py`: `rt.run(sim, until=None, *, factor=1.0, strict=True)` pacing
  `sim.step()` against a module-level monotonic/sleep seam
  (`_monotonic`/`_sleep`, monkeypatch-able like
  `backends._runtime_gil_enabled`); `RealtimeDriftError(SimulationError)`
  carrying simulated time and measured drift; `factor <= 0` rejected with
  `ValueError`.
- `until` semantics copied from `Sim.run`: `None` runs to `EmptySchedule`;
  a number pins a stop event; an event returns its value; the
  "until never triggered" `RuntimeError` matches.
- Unit tests with a fake clock (no real sleeping): events processed at their
  scheduled wall offsets, `factor` scaling, strict drift raise with the
  right numbers, non-strict hurry-then-resync, zero-delay event bursts,
  `factor` validation; mypy/pyright strict clean.
- Public API re-export (`llmsim.rt` module import path plus
  `RealtimeDriftError` in `__init__.py`/`test_import.py` contract).

## 2. Offload-hook parity

- `rt.run` mirrors `Sim.run`'s Phase 4.1 seam exactly: `poll()` after each
  step, and `drain()` on **every** `EmptySchedule` while a pool is attached
  — including when an `until` time/event is still pending; only after
  `drain()` reports nothing outstanding does the `until`-never-triggered
  `RuntimeError` (or clean return) path run, matching `core/sim.py`'s loop
  (comment cross-references keep the two in lockstep).
- Tests: non-strict offload delivery between paced steps; run-end drain
  under pacing; strict offload slot blocking counted as drift (fake clock
  advanced by a stub payload); `rt.run` of a `Sim` with no pool pays no
  offload cost.

## 3. Equivalence suite + offload synergy showcase

- Trace-equivalence tests: `rt.run(sim)` at small real `factor` produces a
  bitwise-identical `trace.py` log to `sim.run()` for the same seed, on a
  model mixing timeouts, processes, resources, and strict offloads
  (inline and thread backends).
- Offload synergy test (HIL showcase): a strict offload whose payload
  wall-time fits inside its slot's real-time budget completes without
  drift — the computation hides inside the pacing sleep; the same payload
  with an undersized budget raises `RealtimeDriftError` under
  `strict=True` (fake clock where determinism matters, generous-tolerance
  real-clock smoke test otherwise).
- Real-clock smoke test with generous tolerance, gated by
  `benchmarks.skip_if_shared_macos_ci`-equivalent policy for tests (skip
  timing assertions on shared macOS CI; equivalence assertions run
  everywhere).

## 4. Docs + roadmap

- Docs: real-time section in the parallelism decision tree page (when to
  pace, the factor/strict contract, the HIL offload-synergy example);
  drift regimes recorded in `docs/perf-notes.md` (factor below the
  event-density floor, overlong offload payloads, GC pauses — measured
  where practical, per the docs-honesty rule).
- SimPy `RealtimeEnvironment` differences noted inline for the future 4.3
  migration guide to lift.
- Tick roadmap step 4.2.
