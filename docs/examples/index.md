# Example gallery

Two runnable, CI-tested, end-to-end examples that exercise **every parallelism
tier** the engine ships. Each is built entirely on the public API — no engine
edits — and doubles as the final API dogfooding pass before the 1.0 freeze.

Start with [Which parallelism do I need?](../parallelism-decision-tree.md), then
see the tier in action:

| Example | Domain | Tiers shown |
| --- | --- | --- |
| [Ride-hailing fleet](ride-hailing.md) | Autonomous robotaxi dispatch over a zone graph | Replications (5.2a), PDES sharding (5.2b) |
| [LLM agentic workflow](agentic-workflow.md) | Multi-agent task pipeline over a modelled LLM server | Replications (5.4a), strict-mode offload (5.4b) |

## What each tier maps to

- **Run one model many times** (parameter sweeps, confidence intervals) →
  `Experiment` / `run_replications`. Both examples' studies
  ([fleet sizing](ride-hailing.md#showcase-52a-fleet-sizing-monte-carlo),
  [capacity](agentic-workflow.md#showcase-54a-capacity-planning-sweep)) are this
  tier.
- **One run has too many events for one core** → `ShardedSim`. The
  [zone-sharded ride-hailing variant](ride-hailing.md#showcase-52b-zone-sharded-pdes)
  is this tier.
- **One run is CPU-bound in computation, not events** → `sim.offload`. The
  [strict-mode scoring showcase](agentic-workflow.md#showcase-54b-strict-mode-offload)
  is this tier.

## Guarantees every example holds

- **Same-seed determinism** — two runs with the same master seed produce
  identical KPIs.
- **Backend reproducibility** — study results are bit-identical across the
  thread, interpreter, and process backends for a fixed master seed.
- **Trace-equivalence** — the sharded run equals its sequential reference
  bitwise; the offloaded policy equals the inline reference bitwise (strict
  mode).
- **Stdlib-only, no network** — the examples add no runtime dependency, and the
  agentic example is proven by test to make no LLM or network call.

Regenerate the showcase curves with
`python scripts/generate_example_charts.py`.
