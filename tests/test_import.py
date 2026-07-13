"""Public API surface and package-import smoke tests."""

import importlib

import llmsim

# The public import contract, phase by phase. Users depend on every one of
# these resolving from the top-level package.
PHASE_1_PUBLIC_API = frozenset(
    {
        "Sim",
        "Event",
        "Timeout",
        "Process",
        "Interrupt",
        "SimulationError",
        "EmptySchedule",
        "Condition",
        "AllOf",
        "AnyOf",
        "Resource",
        "PriorityResource",
        "PreemptiveResource",
        "Container",
        "Store",
        "PriorityStore",
        "FilterStore",
    }
)

# Phase 2: parallel replications + reproducible randomness.
PHASE_2_PUBLIC_API = frozenset(
    {
        "Experiment",
        "ReplicationResult",
        "ReplicationError",
        "run_replications",
        "ExecutionBackend",
        "CancelToken",
        "FactoryValidationError",
        "TransportError",
        "SeedTree",
        "SeedStream",
    }
)

# Phase 3: single-run conservative PDES.
PHASE_3_PUBLIC_API = frozenset(
    {
        "ShardedSim",
        "ShardPorts",
        "ShardError",
        "TopologyError",
        "LookaheadError",
    }
)

# Phase 4: compute offload + real-time mode.
PHASE_4_PUBLIC_API = frozenset(
    {
        "OffloadPool",
        "OffloadEvent",
        "NonStrictOffloadWarning",
        "rt",
        "RealtimeDriftError",
    }
)

PUBLIC_API = (
    PHASE_1_PUBLIC_API | PHASE_2_PUBLIC_API | PHASE_3_PUBLIC_API | PHASE_4_PUBLIC_API
)


def test_package_imports() -> None:
    """The top-level package imports without side effects."""
    assert llmsim.__name__ == "llmsim"


def test_public_api_is_a_list() -> None:
    """``__all__`` is a list so re-exports can accumulate phase by phase."""
    assert isinstance(llmsim.__all__, list)


def test_all_matches_documented_public_api() -> None:
    """``__all__`` is exactly the documented Phase 1-4 contract."""
    assert set(llmsim.__all__) == PUBLIC_API


def test_public_names_resolve() -> None:
    """Every documented public name is importable from the package."""
    for name in PUBLIC_API:
        assert hasattr(llmsim, name), f"llmsim.{name} does not resolve"
        assert getattr(llmsim, name) is not None


def test_submodules_import() -> None:
    """Every scaffolded submodule imports (Phase 1 engine + later-phase stubs)."""
    submodules = [
        "llmsim.core",
        "llmsim.core.sim",
        "llmsim.core.events",
        "llmsim.core.process",
        "llmsim.core.conditions",
        "llmsim.core.errors",
        "llmsim.resources",
        "llmsim.resources.base",
        "llmsim.resources.resource",
        "llmsim.resources.container",
        "llmsim.resources.store",
        "llmsim.rand",
        "llmsim.rand.streams",
        "llmsim.parallel",
        "llmsim.parallel.backends",
        "llmsim.parallel.replicate",
        "llmsim.parallel.offload",
        "llmsim.parallel.pdes",
        "llmsim.parallel.pdes.shard",
        "llmsim.parallel.pdes.channel",
        "llmsim.parallel.pdes.sync",
        "llmsim.scenario",
        "llmsim.scenario.schema",
        "llmsim.scenario.inject",
        "llmsim.scenario.llm",
        "llmsim.scenario.agent",
        "llmsim.scenario.report",
        "llmsim.rt",
        "llmsim.trace",
    ]
    for name in submodules:
        assert importlib.import_module(name) is not None
