"""Smoke test proving the package imports and the quality-gate pipeline runs."""

import importlib

import llmsim


def test_package_imports() -> None:
    """The top-level package imports without side effects."""
    assert llmsim.__name__ == "llmsim"


def test_public_api_is_a_list() -> None:
    """``__all__`` is a list so re-exports can accumulate phase by phase."""
    assert isinstance(llmsim.__all__, list)


def test_submodules_import() -> None:
    """Every scaffolded submodule imports as an empty, typed stub."""
    submodules = [
        "llmsim.core",
        "llmsim.core.sim",
        "llmsim.core.events",
        "llmsim.core.process",
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
