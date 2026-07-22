# Validation — Phase 5: Domain example gallery

## Success criteria (chosen gate)

The primary "done" gate for **every example and showcase in this spec** is the
trio selected for this phase:

1. **Same-seed determinism test** — for each example, two runs with the same
   master seed produce identical KPI results; for each parallel showcase, the
   parallel result equals the sequential reference for a fixed seed
   (the cross-cutting roadmap determinism rule).
2. **KPI regression snapshot** — a committed snapshot of the headline KPIs
   (ride-hailing: wait time, utilization, abandonment; agentic: end-to-end
   latency, queue depth, cost per task) at fixed small parameters; the test
   fails if a KPI drifts outside a tight tolerance.
3. **CI smoke-run** — each example runs to completion with small parameters on
   both the 3.14 and 3.14t builds inside per-PR CI.

## Inherited exit criteria (roadmap Phase 5 — required because scope = 5.1–5.5)

Selecting full Phase 5 scope pulls in the parallelism showcases, so the
roadmap's own Phase 5 exit criteria apply and are **not** optional. These are
enforced in addition to the trio above:

4. **Trace-equivalence tests** — bitwise equivalence of the zone-sharded
   ride-hailing run (5.2b) and the strict-mode offloaded agentic policy (5.4b)
   against their sequential references (roadmap 5.2/5.4; determinism principle).
5. **A published measured curve per showcase** — the fleet-sizing study, the
   sharded variant, the capacity sweep, and the offload showcase each publish a
   measured scaling/CI curve with its documented slowdown regime
   (honest-performance rule); numbers are regenerated from committed
   small-parameter study scripts. Absolute speedup figures on anti-scaling
   interpreters are recorded-not-blocking, consistent with the Phase 3 exit note.
6. **Friction list resolved or waived** — API-friction findings from building
   the examples are filed and each is resolved or explicitly waived before the
   4.5 freeze review (roadmap 5.5; unblocks the 1.0 freeze).

## Checklist

- [ ] `examples/ride_hailing/` and `examples/agentic_workflow/` are importable
      packages with a module-level factory each (no live objects in payloads).
- [ ] Ride-hailing: behavioral tests (serve, abandon-on-patience, recharge
      blocks on full station) pass; `closest_available` and `power_of_d`
      policies both exercised.
- [ ] Agentic: behavioral tests (task completes, tool-call retry, batching
      groups concurrent inference) pass.
- [ ] Agentic **no-network enforcement** (tech-stack §9, enforced-by-test):
      a test wraps the factory/`run()` path with `socket`/network APIs
      monkeypatched to raise, bans stdlib network modules from the example
      package, and asserts the example completes with no LLM/network dependency
      installed (no `llmsim[llm]` extra) — not merely an import/offline check.
- [ ] Same-seed determinism test green for both examples.
- [ ] Backend-reproducibility test: study results identical across **all
      supported backends** (thread, interpreter, process) for a fixed master
      seed, keyed by (config, replication), with an explicit skip only where a
      backend's runtime support is unavailable. Includes an
      importability/pickle check on each factory and config so a closure or
      non-picklable payload fails here, not silently on one backend
      (tech-stack §5, executor-payloads-are-references).
- [ ] Trace-equivalence: sharded ride-hailing ≡ sequential at 1/2/4 shards;
      offloaded agentic policy ≡ inline (strict mode).
- [ ] KPI snapshot tests committed and green.
- [ ] One docs page per example, each linking the decision tree, with an
      embedded measured curve; `mkdocs build --strict` passes.
- [ ] CI smoke-run job runs both examples with small params on 3.14 and 3.14t.
- [ ] Gates green: `uv run ruff check`, `uv run ruff format --check`,
      `uv run mypy --strict`, `uv run pyright`, `uv run pytest`.
- [ ] API-friction list written and each item resolved or waived.

## Done when

Both examples and all four showcases are green in CI on 3.14 and 3.14t, every
same-seed determinism and trace-equivalence test passes, each showcase has a
published measured curve, and the API-friction list is resolved or waived —
i.e. the 4.5 freeze review has everything it needs to proceed.
