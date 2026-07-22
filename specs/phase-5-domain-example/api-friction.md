# API-friction findings — Phase 5 examples

Findings surfaced while building the two examples against the public Phase 1–4
API (roadmap 5.5). Each is **resolved** (handled within the examples, no engine
change) or **waived** (a deliberate non-change, with the reason), so the step 4.5
freeze review has a complete list. **None requires an engine or public-API change
before 1.0** — the freeze is unblocked.

## 1. Trace-equivalence requires value-comparable payloads — resolved

`TraceRecord` compares payloads with `==`, so any domain object that appears as a
traced event payload/value (a `FilterStore` item, an event's resolved value) must
have value identity for two independent runs to compare bitwise-equal — even when
the simulation is perfectly deterministic. With default object identity, the
threaded-vs-sequential and offload-vs-inline trace comparisons diverge only in
the payload's memory address.

- **Resolution:** the examples give `_Vehicle`, `_Request`, and
  `_InferenceRequest` stable value identity (`__eq__`/`__hash__` on their
  immutable keys). This is a natural domain statement ("a vehicle *is* its id").
- **Recommendation for the freeze review (docs-only):** add a short note to the
  tracing guide — "bitwise trace-equivalence across runs requires event payloads
  to be value-comparable; carry plain data or give domain objects a stable
  `__eq__`." No API change.

## 2. Global cross-zone dispatch is not share-nothing-decomposable — waived

The monolithic model ranks *all* idle vehicles across every zone. A share-nothing
`ShardedSim` shard cannot rank vehicles it does not own without reading another
shard's state, so the requirement's "cross-zone dispatch is a channel message to
the candidate vehicle's shard" cannot be implemented as a cheap global ranking.

- **Resolution:** the sharded variant uses **local dispatch + vehicle migration**
  (a trip crossing a zone-group boundary is a channel handoff with the minimum
  inter-zone time as lookahead). This is an honest conservative-PDES
  decomposition, not a bitwise clone of the monolithic model.
- **Interpretation of the spec (waived, no engine change):** "bitwise
  trace-equivalence against the sequential model" is read — consistent with the
  repo's own PDES equivalence convention (`tests/test_pdes_equivalence.py`) — as
  equivalence against the **sequential reference of the sharded topology**
  (`mode="sequential"`), which is the genuine Phase 3 guarantee and is proven at
  1/2/4 shards. Recommend the roadmap/requirements wording be clarified to say
  "sequential reference" to avoid implying monolithic-equivalence, which is
  infeasible for any non-trivial model.

## 3. `examples/` was outside every tooling scope — resolved

`pyproject.toml` scoped ruff `src`, mypy `files`, and pyright `include` to
`src`/`tests` only, so example code was unchecked.

- **Resolution:** added `examples` to all three scopes; example tests live under
  `tests/` (the default `testpaths`). Example modules keep full PEP 257
  docstrings (they are a docs surface). No API change.

## 4. Strict-typing ergonomics for typed public example code — waived

Two pyright-strict frictions when writing fully typed, public-facing example
code: `dataclasses.field(default_factory=list)` reports an unknown element type,
and `dict.fromkeys(<tuple of str literals>, 0.0)` yields `dict[Literal[...],
float]` that will not assign to `dict[str, float]`.

- **Resolution:** used an explicit `__init__` for the mutable accumulator and
  annotated the key tuple as `tuple[str, ...]`. These are standard typed-Python
  idioms; no engine or API change.

## 5. Strict-mode `sim.offload` requires a positive delay — waived

Offloading the scoring policy required choosing a fixed completion slot
(`SCORING_SLOT`) because strict mode mandates a `delay`. A conceptually
"zero-latency" offload still needs a positive slot.

- **Waived:** this is exactly the strict-mode contract (deterministic completion
  slots make the backend invisible to the trace). Documented behavior, working as
  intended; the fixed slot reads naturally as "routing-decision latency."

## 6. No first-class per-shard result collection on `ShardedSim` — waived (post-1.0 idea)

Recovering KPIs from a `ShardedSim` run means closing over an external dict in
each shard builder (as `tests/test_pdes_equivalence.py` already does). A
first-class per-shard result-collection helper would be cleaner.

- **Waived for 1.0:** the closure pattern is small, deterministic, and matches
  the existing test convention. Filed as a **post-1.0 enhancement idea**, not a
  freeze blocker. Any such addition is its own spec.

## Freeze verdict

All six findings are resolved or waived with no pre-1.0 engine/API change. Items
1 and 2 carry docs/wording recommendations; item 6 is a post-1.0 enhancement
idea. The Phase 5 gate on step 4.5 is therefore clear from the API-friction side.
