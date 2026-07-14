# Public-API audit — Phase 4.5 (1.0 freeze)

Status: **audit complete.** No unresolved gaps. The 1.0 tag and PyPI publish
remain gated on Phase 5 (the domain examples are the API's dogfooding pass), per
the roadmap.

## Method

This audit walks **every public symbol** — the names re-exported from
`src/llmsim/__init__.py` (`llmsim.__all__`) plus the public `llmsim.rt`,
`llmsim.trace`, and `llmsim.parallel.pdes` submodule surfaces (each declares its
own `__all__`) — against four criteria:

- **Annotated** — fully type-annotated on the public surface. Enforced
  repository-wide by `uv run mypy --strict` **and** `uv run pyright` (strict);
  both are required CI gates, so a public symbol cannot merge unannotated. This
  audit confirms *public-surface completeness* rather than re-checking types:
  `__all__` consistency, no accidental exports, and generics surfaced correctly
  (`Event` is `Generic[T]`, so `Event[T]` is the public form).
- **Documented** — carries a PEP 257 docstring. Enforced by ruff's `D`
  (pydocstyle) rules and, for the reference build, by `mkdocs build --strict`
  (mkdocstrings warns → strict fails on any missing docstring).
- **Named consistently** — reads naturally in DES domain terms (see the review
  below).
- **In API reference** — has a `:::` directive under `docs/reference/`, verified
  automatically by `tests/docs/test_api_reference_coverage.py`, which diffs
  `__all__` (and the `rt`/`trace` surfaces) against the reference pages in both
  directions.

The table columns below were generated mechanically from the installed package
and the committed reference pages; they are not hand-asserted.

## Coverage table

Legend: **A**nnotated · **D**ocumented · **N**amed-consistent · in **R**eference.

### Core engine — `docs/reference/core.md`

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `Sim` | `llmsim.core.sim.Sim` | class | ✅ | ✅ | ✅ | ✅ |
| `Event` | `llmsim.core.events.Event` | class (`Generic[T]`) | ✅ | ✅ | ✅ | ✅ |
| `Timeout` | `llmsim.core.events.Timeout` | class | ✅ | ✅ | ⚠️ | ✅ |
| `Process` | `llmsim.core.process.Process` | class | ✅ | ✅ | ✅ | ✅ |
| `Condition` | `llmsim.core.conditions.Condition` | class | ✅ | ✅ | ✅ | ✅ |
| `AllOf` | `llmsim.core.conditions.AllOf` | class | ✅ | ✅ | ✅ | ✅ |
| `AnyOf` | `llmsim.core.conditions.AnyOf` | class | ✅ | ✅ | ✅ | ✅ |
| `SimulationError` | `llmsim.core.errors.SimulationError` | class | ✅ | ✅ | ✅ | ✅ |
| `Interrupt` | `llmsim.core.errors.Interrupt` | class | ✅ | ✅ | ⚠️ | ✅ |
| `EmptySchedule` | `llmsim.core.errors.EmptySchedule` | class | ✅ | ✅ | ⚠️ | ✅ |

### Resources — `docs/reference/resources.md`

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `Resource` | `llmsim.resources.resource.Resource` | class | ✅ | ✅ | ✅ | ✅ |
| `PriorityResource` | `llmsim.resources.resource.PriorityResource` | class | ✅ | ✅ | ✅ | ✅ |
| `PreemptiveResource` | `llmsim.resources.resource.PreemptiveResource` | class | ✅ | ✅ | ✅ | ✅ |
| `Container` | `llmsim.resources.container.Container` | class | ✅ | ✅ | ✅ | ✅ |
| `Store` | `llmsim.resources.store.Store` | class | ✅ | ✅ | ✅ | ✅ |
| `PriorityStore` | `llmsim.resources.store.PriorityStore` | class | ✅ | ✅ | ✅ | ✅ |
| `FilterStore` | `llmsim.resources.store.FilterStore` | class | ✅ | ✅ | ✅ | ✅ |

### Randomness — `docs/reference/randomness.md`

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `SeedTree` | `llmsim.rand.streams.SeedTree` | class | ✅ | ✅ | ✅ | ✅ |
| `SeedStream` | `llmsim.rand.streams.SeedStream` | class | ✅ | ✅ | ✅ | ✅ |

### Parallel replications — `docs/reference/parallel.md`

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `Experiment` | `llmsim.parallel.replicate.Experiment` | class | ✅ | ✅ | ✅ | ✅ |
| `ReplicationResult` | `llmsim.parallel.replicate.ReplicationResult` | class | ✅ | ✅ | ✅ | ✅ |
| `ReplicationError` | `llmsim.parallel.replicate.ReplicationError` | class | ✅ | ✅ | ✅ | ✅ |
| `run_replications` | `llmsim.parallel.replicate.run_replications` | func | ✅ | ✅ | ✅ | ✅ |
| `ExecutionBackend` | `llmsim.parallel.backends.ExecutionBackend` | class | ✅ | ✅ | ✅ | ✅ |
| `CancelToken` | `llmsim.parallel.backends.CancelToken` | class | ✅ | ✅ | ✅ | ✅ |
| `FactoryValidationError` | `llmsim.parallel.backends.FactoryValidationError` | class | ✅ | ✅ | ✅ | ✅ |
| `TransportError` | `llmsim.parallel.backends.TransportError` | class | ✅ | ✅ | ✅ | ✅ |

### PDES sharding — `docs/reference/parallel.md`

Covers the full public `llmsim.parallel.pdes.__all__` surface, not only the
names re-exported at the top level. `ShardedSim`, `ShardPorts`, `ShardError`,
`TopologyError`, and `LookaheadError` are also in `llmsim.__all__`; the
remaining six (`RunMode`, `Channel`, `Inbox`, `Message`, `analyze`,
`PdesAnalysis`) are public via the package `__all__` and are documented and
gated by `tests/docs/test_api_reference_coverage.py`.

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `ShardedSim` | `llmsim.parallel.pdes.shard.ShardedSim` | class | ✅ | ✅ | ✅ | ✅ |
| `ShardPorts` | `llmsim.parallel.pdes.shard.ShardPorts` | class | ✅ | ✅ | ✅ | ✅ |
| `ShardError` | `llmsim.parallel.pdes.shard.ShardError` | class | ✅ | ✅ | ✅ | ✅ |
| `TopologyError` | `llmsim.parallel.pdes.shard.TopologyError` | class | ✅ | ✅ | ✅ | ✅ |
| `LookaheadError` | `llmsim.parallel.pdes.channel.LookaheadError` | class | ✅ | ✅ | ✅ | ✅ |
| `RunMode` | `llmsim.parallel.pdes.shard.RunMode` | `Literal` alias | ✅ | — | ✅ | ✅ |
| `Channel` | `llmsim.parallel.pdes.channel.Channel` | class | ✅ | ✅ | ✅ | ✅ |
| `Inbox` | `llmsim.parallel.pdes.channel.Inbox` | class | ✅ | ✅ | ✅ | ✅ |
| `Message` | `llmsim.parallel.pdes.channel.Message` | class | ✅ | ✅ | ✅ | ✅ |
| `analyze` | `llmsim.parallel.pdes.analyze.analyze` | func | ✅ | ✅ | ✅ | ✅ |
| `PdesAnalysis` | `llmsim.parallel.pdes.analyze.PdesAnalysis` | class | ✅ | ✅ | ✅ | ✅ |

`RunMode` is a `Literal["threads", "sequential"]` type alias; it carries no
docstring by convention (its value is self-describing and renders in the
reference), so the **D** column is marked n/a rather than ❌.

### Compute offload — `docs/reference/parallel.md`

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `OffloadPool` | `llmsim.parallel.offload.OffloadPool` | class | ✅ | ✅ | ✅ | ✅ |
| `OffloadEvent` | `llmsim.parallel.offload.OffloadEvent` | class | ✅ | ✅ | ✅ | ✅ |
| `NonStrictOffloadWarning` | `llmsim.parallel.offload.NonStrictOffloadWarning` | class | ✅ | ✅ | ✅ | ✅ |

### Real-time — `docs/reference/realtime.md`

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `rt` | `llmsim.rt` | module | ✅ | ✅ | ✅ | ✅ |
| `rt.run` | `llmsim.rt.run` | func | ✅ | ✅ | ✅ | ✅ |
| `RealtimeDriftError` | `llmsim.rt.RealtimeDriftError` | class | ✅ | ✅ | ✅ | ✅ |

### Tracing (public submodule surface) — `docs/reference/tracing.md`

| Symbol | Defining path | Kind | A | D | N | R |
|---|---|---|:-:|:-:|:-:|:-:|
| `trace` | `llmsim.trace.trace` | func | ✅ | ✅ | ✅ | ✅ |
| `disable_trace` | `llmsim.trace.disable_trace` | func | ✅ | ✅ | ✅ | ✅ |
| `Tracer` | `llmsim.trace.Tracer` | class | ✅ | ✅ | ✅ | ✅ |
| `TraceRecord` | `llmsim.trace.TraceRecord` | class | ✅ | ✅ | ✅ | ✅ |

## `__all__` consistency

- Every name in `llmsim.__all__` resolves to a live object and is documented in
  the reference (`tests/docs/test_api_reference_coverage.py`).
- `__all__` equals the exact documented Phase 1–4 contract, and no accidental
  public names leak (`tests/test_import.py::test_all_matches_documented_public_api`).
- The public submodules that declare their own `__all__` — `llmsim.rt`,
  `llmsim.trace`, and `llmsim.parallel.pdes` — are each covered symbol-for-symbol
  in the reference, verified by object identity (so a new public name in any of
  them fails the gate until documented). `rt.py` and `trace.py` gained explicit
  `__all__`s in this change so their surfaces are declared, not inferred.
- `llmsim.scenario.*` (Phase 6 LLM scenario generation) is **deliberately not**
  re-exported and is absent from `__all__` — it is post-1.0 surface and is
  correctly excluded from the freeze.

## Naming-consistency review (DES domain terms)

The surface reads consistently in DES terms; three items are flagged (⚠️) with
their dispositions. **No finding requires a code change before 1.0.**

1. **`Interrupt` and `EmptySchedule` do not carry the `*Error` suffix**
   (finding `NAME-1`). Every other exception ends in `Error`
   (`SimulationError`, `ShardError`, `TopologyError`, …). Both are marked
   `# noqa: N818 -- spec-mandated public name` in `src/llmsim/core/errors.py`.
   **Disposition: waived by design.** `Interrupt` matches SimPy 3's exception
   name (migration familiarity; the migration guide relies on it), and
   `EmptySchedule` is a domain noun for the terminal condition. Renaming would
   break the intended SimPy-porting ergonomics for no correctness gain.
2. **`Sim.delay(...)` returns a `Timeout`** (finding `NAME-2`) — a verb method
   producing a noun-named event, inherited from SimPy 3 (`env.timeout`).
   **Disposition: waived by design.** The pairing is documented in the
   [migration guide](../../docs/migration-from-simpy.md) and in
   `docs/guide/core-concepts.md`; `delay` reads better than `timeout` as a
   method while `Timeout` remains the recognizable event type.
3. **Both `Experiment` (class) and `run_replications` (function) run
   replications** (finding `NAME-3`). **Disposition: waived by design.**
   `Experiment` is the stateful, context-manager-capable entry point;
   `run_replications` is the one-shot convenience wrapper. Both are documented;
   the naming distinguishes lifecycle from convenience.

No renames or deprecations are scheduled for the audit PR. Should any of the
above be reopened, they execute as their own follow-up change under the
[deprecation policy](../../docs/deprecation-policy.md), never silently.

## Conclusion

Every public symbol is annotated, documented, named consistently (or flagged
with a recorded, waived rationale), and present in the API reference. `__all__`
consistency and reference coverage are enforced by tests, and the deprecation
policy for the 1.x series is published. **The audit is complete with zero
unresolved (unfixed and unfiled) findings.** The 1.0 tag and PyPI publish are
deferred to the Phase 5 gate.
