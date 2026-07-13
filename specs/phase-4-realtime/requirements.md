# Requirements — Phase 4.2 Real-time mode

## Context

Roadmap step **4.2** adds wall-clock-synchronized stepping for
hardware-in-the-loop use (mission scope: "Real-time mode"): `rt.py` paces an
ordinary `Sim` against `time.monotonic()` (the tech-stack-named clock) so one
simulated time unit takes a configurable amount of real time. Pacing is a
*driver* concern layered on the untouched sequential core — the same
architecture posture as Phase 4.1's offload seam — and it must never change
simulated outcomes: for deterministic models, a paced run and an unpaced run
of the same model and seed are bitwise trace-equivalent (mission
principle 2; `strict=False` offloads are wall-clock-dependent by their own
Phase 4.1 contract and sit outside the bitwise bar under either driver). The
offload synergy is
the point for HIL: a strict offload's completion slot becomes a real
wall-clock deadline, and the payload computes *during* the pacing sleep.

## Scope

In:

- `rt.run(sim, until=None, *, factor=1.0, strict=True)` in `rt.py`: drives
  `sim.step()` while sleeping so that an event at simulated time `T` is
  processed no earlier than `start + (T - t0) * factor` wall-clock seconds
  (`factor` = real seconds per simulated time unit; `factor=0.1` runs 10×
  faster than real time). `until` mirrors `Sim.run` exactly: `None` (run to
  empty schedule), a time, or an event whose value is returned.
- **Drift policy**: when processing falls behind the wall-clock schedule by
  more than the allowed slack, `strict=True` (default) raises
  `RealtimeDriftError` naming the simulated time and the measured drift;
  `strict=False` continues without sleeping until caught up. Events are
  never skipped in either mode — determinism is unaffected.
- **Offload-hook parity**: `rt.run` honors the Phase 4.1 seam exactly as
  `Sim.run` does — post-step `poll()`, run-end `drain()` — so non-strict
  offloads deliver between paced steps and strict offload slots become
  wall-clock deadlines (blocking at an unfinished slot counts as drift).
- **Offload synergy (HIL showcase)**: a test and a docs example where a
  CPU-heavy strict offload overlaps its pacing sleep — the payload's wall
  time hides inside the slot's real-time budget.
- **Injectable clock seam** for deterministic tests: the monotonic/sleep
  pair is a module seam (monkeypatch-able, like
  `backends._runtime_gil_enabled`), so drift and pacing logic are unit-tested
  with a fake clock; only a small smoke test touches the real clock.
- Same-seed trace-equivalence tests (paced ≡ unpaced, bitwise) and
  documented drift regimes (factor too small for the event density, hung or
  overlong offload payloads, GC pauses).

Out:

- SimPy 3 migration guide (roadmap 4.3) — the `RealtimeEnvironment` mapping
  row lands there, not here.
- Docs site build-out and 1.0 freeze review (4.4–4.5).
- A `RealtimeSim` subclass or a `Sim.run(realtime=...)` flag — rejected by
  the key decision below.
- Real-time pacing of `Experiment` replications or PDES shards — pacing is
  single-`Sim`; combining it with the other parallel tiers is post-1.0 if
  ever.
- Catch-up scheduling policies (dropping/coalescing events) — events are
  never skipped; the only behind-schedule policies are raise or hurry.

## Decisions

- **API shape: a driver function, not a subclass or core flag** (user
  decision). `rt.run(sim, ...)` lives in `rt.py` and paces `sim.step()` from
  outside: the lock-free core gains no third `run()` variant, no hot-path
  branch, and no public class to freeze at 1.0; any existing `Sim` (with or
  without an `OffloadPool`) can be paced. The `Sim.run`/`rt.run` behavioral
  contract (until semantics, offload hooks, `EmptySchedule` handling) must
  stay in lockstep — asserted by the equivalence suite.
- **Clock**: `time.monotonic()` only (tech-stack rule); never wall-calendar
  time, never `time.time()`.
- **Determinism**: pacing sleeps happen strictly *between* steps; `rt.run`
  itself introduces no clock dependence into event ordering, RNG, or values.
  For deterministic models (everything except `strict=False` offloads) a
  paced run's trace is bitwise-equal to the unpaced reference — enforced by
  test, same bar as offload strict mode. `strict=False` offloads are already
  wall-clock-dependent under `Sim.run` (documented in Phase 4.1) and are
  excluded from the bitwise guarantee; pacing neither adds to nor removes
  that nondeterminism.
- **Drift is measured and surfaced, never absorbed silently**: `strict=True`
  raises with the numbers; `strict=False` hurries but the behavior is
  documented as a slowdown/latency regime per the docs-honesty rule.
- **Stdlib-only**: `time.monotonic`, `time.sleep` — no new dependencies.
- **Thread ownership unchanged**: `rt.run` executes on the `Sim`'s owning
  thread; no locks, no cross-thread scheduling (constraints 1–2).
