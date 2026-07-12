# Tech Stack — llmsim

## Language and runtime

- **Python 3.14+ only** (`requires-python = ">=3.14"`). The library targets *both*
  runtime flavors of CPython 3.14:
  - the **default (GIL) build**, and
  - the **free-threaded build (`3.14t`, PEP 703/779)** — officially supported as
    of 3.14, where true multi-core threading is the preferred parallel backend.
- Runtime detection: `sys._is_gil_enabled()`; build detection:
  `sysconfig.get_config_var("Py_GIL_DISABLED")`.
- The CPython **tail-call interpreter** and **experimental JIT** are treated as
  benchmark *variants* (detected and reported by the bench harness), never as
  baseline assumptions or exit-criteria inputs.

## Core dependencies

- **Zero required runtime dependencies.** The engine is stdlib-only:
  - `heapq` for the event queue — `(time, priority, eid, event)` tuples.
  - `random.Random` for per-`Sim` RNG; seed tree via `hashlib` (SHA-256 of the
    seed path → 128-bit child seeds).
  - `concurrent.futures` for all parallel backends: `ThreadPoolExecutor`
    (free-threaded), `InterpreterPoolExecutor` (PEP 734, GIL builds),
    `ProcessPoolExecutor` (compatibility floor; forkserver default on Linux).
  - `threading` (`Lock`, `Barrier`, condition variables) — used *only* in
    `llmsim.parallel` channel/mailbox structures, never in the sequential core.
  - `compression.zstd` (new in 3.14) for optional spooling of large
    per-replication traces/results.
  - `time.monotonic()` for real-time mode.
- **Optional extras:**
  - `numpy` adapter (`Generator(Philox)`) for models wanting vectorized draws —
    `pip install llmsim[numpy]`.
  - `anthropic` SDK for LLM-powered scenario generation (Phase 6) —
    `pip install llmsim[llm]`. Used only by `llmsim.scenario`'s design-time
    agent behind a provider-agnostic `LLMClient` protocol; default to the
    latest Claude model. The scenario *schema*, validation, and
    fault-injection replay are stdlib-only (`dataclasses`, `json`, `hashlib`)
    so artifacts can be replayed without the extra installed.

## Package layout

```
llmsim/
├── pyproject.toml            # PEP 621
├── src/llmsim/
│   ├── __init__.py           # public API re-exports
│   ├── core/                 # sim.py, events.py, process.py, errors.py
│   ├── resources/            # base.py, resource.py, container.py, store.py
│   ├── rand/                 # streams.py — seed tree, per-replication RNG
│   ├── parallel/
│   │   ├── backends.py       # ExecutionBackend: threads | interpreters | processes
│   │   ├── replicate.py      # Experiment, run_replications(), ReplicationResult
│   │   ├── offload.py        # sim.offload() worker-pool integration
│   │   └── pdes/             # shard.py, channel.py, sync.py
│   ├── scenario/             # Phase 6: schema.py, inject.py, llm.py, agent.py, report.py
│   ├── rt.py                 # real-time (wall-clock) mode
│   └── trace.py              # structured event tracing
├── tests/
├── benchmarks/               # pytest-benchmark; SimPy 3 parity models
├── examples/                 # domain example gallery (ride-hailing fleet, agentic workflow); CI smoke-run
└── docs/
```

- `src/` layout, PEP 621 metadata, single package, no namespace packages.

## Tooling

| Concern | Tool | Notes |
|---|---|---|
| Package manager | `uv` | Standard for all dev workflows: env creation (`uv venv`), dependency sync (`uv sync`), running gates (`uv run pytest` etc.), and interpreter installs — including free-threaded `3.14t` (`uv python install 3.14t`). Lockfile (`uv.lock`) committed. End users still install via plain `pip` from PyPI |
| Build backend | `hatchling` (PEP 621 / pyproject-only) | No setup.py |
| Coding style | **PEP 8** | Project-wide standard for all Python code (naming, layout, imports); PEP 8-derived docstring conventions per PEP 257 |
| Lint + format | `ruff` (lint **and** format) | Single tool, CI-enforced; configured to enforce PEP 8 (`E`/`W` pycodestyle + `N` pep8-naming rules) |
| Type checking | `mypy --strict` **and** `pyright` strict | Both must pass; the public API is fully generic (`Event[T]`) |
| Tests | `pytest` | Plus `hypothesis` for property-based invariants and `pytest-repeat` for concurrency soak runs |
| Benchmarks | `pytest-benchmark` | Regression thresholds enforced in CI |
| Docs | **mkdocs-material** (decided in Phase 0) | Hosts the "Which parallelism do I need?" decision tree as the parallel docs landing page; Python API reference will use an mkdocs-compatible plugin (e.g. mkdocstrings), not Sphinx/autodoc |

## CI matrix (from day one)

- Interpreters: `{3.14, 3.14t, 3.15-dev}` × OS: `{Linux, macOS}`, provisioned
  via `uv python install`; jobs run gates through `uv run` against the
  committed `uv.lock`.
- On `3.14t`, an additional `PYTHON_GIL=0` / `PYTHON_GIL=1` axis.
- Gates per PR: ruff, mypy strict, pyright strict, pytest, benchmark regression
  thresholds on the three canonical models (M/M/1 queue, machine shop,
  100×100 grid conveyor network).
- Concurrency soak job on `3.14t`: long randomized runs (schedule-dependent bug
  hunting), assertions-on debug build.
- Pin CI to the latest 3.14.x point release; treat 3.15-dev as a canary
  (free-threaded behavior is still evolving across point releases).

## Technical constraints (normative)

These are architecture-level rules, not preferences; violating them is a bug:

1. **Thread ownership.** A `Sim` and all attached objects (events, processes,
   resources) belong to exactly one thread at a time. Debug builds
   (`LLMSIM_DEBUG=1` / `Sim(debug=True)`) assert `threading.get_ident()` on every
   `schedule()`.
2. **No locks in the sequential hot path.** The only synchronized structures in
   the library are `llmsim.parallel` channels/mailboxes (`deque` + `Lock`),
   touched at safe-window edges.
3. **Free-threading discipline** (per the official HOWTO): never share iterators
   across threads; never touch another thread's frame objects; use explicit
   locks for multi-operation invariants rather than relying on per-object
   container locks.
4. **Generators pin to their home thread.** No work-stealing, no generator
   migration, no state snapshotting — this is why optimistic synchronization is
   permanently rejected.
5. **Executor payloads are references, not objects.** Parallel work is submitted
   as (importable callable, seed spec, config) — never live model objects — so
   thread, interpreter, and process backends share one code path and switching
   backends is a one-word change.
6. **Low-garbage hot path.** `__slots__` on all hot-path classes; minimal
   temporaries per event (free-threaded GC is stop-the-world, so garbage costs
   more there); track RSS per replication on 3.14t.
7. **Determinism by construction.** Event ordering uses `(time, priority, eid)`
   sort keys; PDES message delivery is sorted by `(timestamp, channel id,
   per-channel sequence number)`; replication results are keyed by
   `(config index, replication index)`, never completion order.
8. **Typed public API.** Every public symbol fully annotated; mypy and pyright
   strict clean; PEP 649 deferred annotations (zero runtime cost).
9. **LLM at design time only.** `llmsim.scenario`'s agent may call an LLM to
   *generate* scenario artifacts; no LLM or network call may occur after
   `run()` starts, on any code path (enforced by test). Simulations consume
   validated, content-hashed artifacts — the artifact is the determinism
   boundary. Tests and CI use a record/replay transport with committed
   fixtures; CI never touches the network.

## Deployment / distribution

- Pure-Python wheel (`py3-none-any`) published to **PyPI**; no compiled
  extensions in 1.0 (keeps free-threaded compatibility trivial — no
  `Py_mod_gil` concerns in llmsim itself).
- Versioning: SemVer; 0.x during Phases 0–3, API freeze review before 1.0.
- Docs published per release with scaling-curve benchmark artifacts.
- License: Apache License 2.0 (matching the repository's existing LICENSE file).
