# Validation — Phase 4.3: Migration guide from SimPy 3

## Success criteria

Per the chosen validation strategy (snippet tests + API audit):

1. **Every code excerpt in the guide is proven current in CI.** The
   snippet-sync test asserts every Python fence in
   `docs/migration-from-simpy.md` carries a snippet marker and is
   byte-identical (after dedent) to its named region in
   `benchmarks/models/` or `benchmarks/llmsim_models/` — files that
   already execute in the benchmark/test gates. A guide excerpt can
   therefore never show code that does not run, and an unmarked
   excerpt fails the test outright.
2. **The concept table is complete, by test.** The API-coverage audit
   asserts every name in the checked-in inventory — the union of the
   required mapping rows and "no equivalent" names from
   `requirements.md` and the SimPy 3 public-API names exercised by the
   ported behavioral suite (Phase 1.10) — appears in the mapping table
   or the "no equivalent" section.
3. **Zero behavior change.** Region markers added to benchmark models
   are comments only; benchmark regression thresholds and the
   same-seed determinism tests stay green on 3.14 and 3.14t.

## Checklist

- [ ] `docs/migration-from-simpy.md` exists with concept table,
      "no equivalent" section, and all three worked-port sections.
- [ ] `tests/docs/test_migration_guide_snippets.py` passes; a
      deliberate one-character edit to a guide excerpt makes it fail,
      and so does adding an unmarked Python fence (each verified once
      by hand, then reverted).
- [ ] `tests/docs/test_migration_guide_coverage.py` passes; removing a
      table row makes it fail (verified once by hand, then reverted).
- [ ] All six benchmark model files carry region markers; `uv run
      pytest benchmarks/` and the regression thresholds still pass.
- [ ] `uv run ruff check`, `uv run mypy --strict`, and `uv run pyright`
      clean (new test files fully typed).
- [ ] Guide cross-linked from `README.md` and `docs/index.md`; links
      to and from `docs/simpy-comparison.md` in place.
- [ ] Prose review: each worked-port section explains every visible
      delta between its SimPy and llmsim excerpts (no unexplained
      differences a migrating reader would trip on).

## Done when

`uv run pytest tests/docs/` passes in CI on 3.14 and 3.14t with both
new tests active, alongside green benchmark regression gates — i.e.
the guide's code and coverage are enforced, not just written.
