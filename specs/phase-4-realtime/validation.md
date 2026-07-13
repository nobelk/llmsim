# Validation — Phase 4.2 Real-time mode

## Success criteria

- **Pacing never changes outcomes:** `rt.run` of a model (including strict
  offloads) produces a bitwise-identical structured trace and identical
  results to `sim.run` for the same seed — the determinism bar every
  parallel-story feature meets.
- **Pacing provably works:** with the injectable fake clock, events process
  at exactly their `start + (T - t0) * factor` wall offsets, and the drift
  policy behaves as specified (`strict=True` raises `RealtimeDriftError`
  with simulated time + measured drift; `strict=False` hurries without
  skipping events). A generous-tolerance real-clock smoke test passes where
  timing is measurable (skipped on shared macOS CI per the perf-notes
  precedent).
- **Offload synergy demonstrated:** a strict offload whose payload fits its
  slot's real-time budget completes without drift; an oversized payload
  raises under `strict=True`. Non-strict offloads deliver between paced
  steps and drain at run end, exactly as under `Sim.run`.
- **Honest docs:** drift regimes (factor below the event-density floor,
  overlong payloads, GC pauses) documented in the same PR.

## Checklist

- [ ] Fake-clock unit tests: wall-offset pacing per event, `factor`
      scaling, `factor <= 0` rejected, zero-delay bursts, strict drift
      raise (correct time + drift values), non-strict hurry-then-resync.
- [ ] `until` parity tests with `Sim.run`: `None`/time/event forms, the
      until-never-triggered `RuntimeError`, return values match.
- [ ] Offload-hook parity tests: non-strict delivery between paced steps,
      run-end drain, strict-slot blocking counted as drift, no-pool `Sim`
      pays nothing.
- [ ] Combined `until` + offload test: `rt.run(..., until=...)` with an
      attached pool whose non-strict offloads outlive the schedule — drains
      exactly like `Sim.run` (delivery before any `EmptySchedule` outcome),
      then matches `Sim.run`'s `until`-never-triggered `RuntimeError` or
      clean-return behavior.
- [ ] Trace-equivalence tests: paced ≡ unpaced, bitwise, same seed, on a
      model with timeouts + processes + resources + strict offloads
      (inline and thread offload backends).
- [ ] Offload synergy tests: payload-inside-budget completes drift-free;
      oversized payload raises `RealtimeDriftError` (`strict=True`).
- [ ] Real-clock smoke test with generous tolerance; timing assertions
      skipped on shared macOS CI, equivalence assertions run everywhere.
- [ ] Public API contract updated (`RealtimeDriftError` re-export;
      `tests/test_import.py` Phase 4 set).
- [ ] Drift regimes documented in `docs/perf-notes.md`; decision-tree page
      gains the real-time section with the HIL example.
- [ ] `uv run ruff check`, `uv run ruff format`, `uv run mypy --strict`,
      `uv run pyright`, and `uv run pytest` green across the CI matrix
      (including `PYTHON_GIL=0/1` on 3.14t).
- [ ] Roadmap step 4.2 checked off.

## Done when

The paced-vs-unpaced trace-equivalence tests and the fake-clock pacing/drift
suite pass on the full CI matrix, with the offload-synergy tests green and
the drift-regime docs merged in the same PR.
