"""Public API surface and package-import smoke tests."""

import importlib

import llmsim

# The Phase 1 public import contract from requirements.md. Users depend on
# every one of these resolving from the top-level package.
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


def test_package_imports() -> None:
    """The top-level package imports without side effects."""
    assert llmsim.__name__ == "llmsim"


def test_public_api_is_a_list() -> None:
    """``__all__`` is a list so re-exports can accumulate phase by phase."""
    assert isinstance(llmsim.__all__, list)


def test_all_matches_documented_public_api() -> None:
    """``__all__`` is exactly the documented Phase 1 contract."""
    assert set(llmsim.__all__) == PHASE_1_PUBLIC_API


def test_public_names_resolve() -> None:
    """Every documented public name is importable from the package."""
    for name in PHASE_1_PUBLIC_API:
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
