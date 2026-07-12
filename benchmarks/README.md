# Benchmarks

SimPy 3 performance baselines for llmsim. Three canonical models — an M/M/1
queue, a machine shop, and a 100×100 grid conveyor network — are implemented in
*SimPy 3* (never llmsim) so that later phases can compare llmsim's
reimplementations against a recorded, apples-to-apples reference.

Run the harness with:

```bash
uv run --group bench pytest benchmarks/
```

## What the harness enforces

For each model, on every run:

- **Presence** — all three canonical models must be registered; a missing model
  fails `test_all_canonical_models_present`.
- **Determinism** — the same seed must produce the same KPI on repeated runs.
- **KPI** — once a baseline exists for the current machine class, the KPI must
  match it exactly. KPIs are hardware-independent (a fixed seed drives a fixed
  `random.Random` draw order), so this is the substantive correctness gate.
- **Timing** — the mean wall-clock time must stay within `TIMING_TOLERANCE` of
  the baseline. Timing is hardware-specific, so it is only compared against a
  baseline recorded on the same machine class.

## Machine-class keying and baselines

Benchmark timings are hardware-specific, so baselines are keyed by *machine
class* — `<system>-<machine>`, e.g. `Darwin-arm64` or `Linux-x86_64` (see
`baselines.machine_class()`). Each class has its own file under
`benchmarks/baselines/<machine-class>.json`.

**First run for a machine class auto-records.** When no baseline file exists for
the current class, the harness records the observed KPI and timing, emits a
warning, and passes. Enforcement for that class begins only once its baseline
file is committed to the repo.

## Regenerating a baseline

To re-record the baseline for the machine you are on (e.g. after intentionally
changing a model), delete its file and re-run the harness:

```bash
rm benchmarks/baselines/$(python -c "from benchmarks.baselines import machine_class; print(machine_class())").json
uv run --group bench pytest benchmarks/
```

Then commit the regenerated JSON.

## Committing the CI machine-class baselines (bootstrap)

The `benchmarks` CI job runs on both `ubuntu-latest` (`Linux-x86_64`) and
`macos-latest` (`Darwin-arm64`) and uploads any baseline it records as the
`benchmark-baselines-<os>` artifact. `Darwin-arm64.json` is committed and
therefore enforced immediately. To activate enforcement on Linux:

1. Trigger a CI run and download the `benchmark-baselines-ubuntu-latest`
   artifact.
2. Commit its `benchmarks/baselines/Linux-x86_64.json` to the repo.

From then on the Linux job enforces the committed KPIs instead of auto-recording.
A baseline must be recorded on the actual CI runner class it will guard —
timings recorded elsewhere are not representative.
