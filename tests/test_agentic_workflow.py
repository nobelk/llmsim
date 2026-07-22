"""Agentic-workflow core-model tests: behavior, no-network, determinism (5.3)."""

import ast
import socket
from pathlib import Path
from typing import Any

import pytest
from examples.agentic_workflow.kpis import AgenticConfig, AgenticKPIs
from examples.agentic_workflow.model import (
    _act,
    _World,
    run_agentic_workflow,
    run_sequential,
)

from llmsim import Sim
from llmsim.rand.streams import SeedTree

_MASTER = 20260712

#: The committed headline KPIs for the default scenario at the canonical seed.
_SNAPSHOT = AgenticKPIs(
    mean_latency=70.248935367,
    completed=96,
    failed=1,
    failure_rate=0.010309278,
    mean_queue_depth=1.372483221,
    peak_queue_depth=4,
    mean_cost=1.030515464,
    mean_batch_size=1.624309392,
    makespan=200.0,
)

#: Stdlib and third-party modules that would mean the example reaches a network.
_BANNED_MODULES = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "http.client",
        "urllib",
        "urllib.request",
        "ftplib",
        "smtplib",
        "telnetlib",
        "asyncore",
        "anthropic",
        "requests",
        "httpx",
        "aiohttp",
        "openai",
    }
)


# --- Behavioral tests. -------------------------------------------------------


def test_task_completes() -> None:
    """A healthy workflow completes a positive number of tasks."""
    kpis = run_sequential(_MASTER, AgenticConfig())
    assert kpis.completed > 0
    assert kpis.mean_latency > 0.0


def test_tool_failure_retries_then_surfaces() -> None:
    """An always-failing tool call retries ``max_retries`` times, then surfaces."""
    config = AgenticConfig(tool_failure_prob=1.0, max_retries=2)
    sim = Sim(seed=0)
    world = _World(sim, config, None)
    outcome: list[tuple[float, bool]] = []

    def driver(sim: Sim) -> Any:
        cost, succeeded = yield from _act(sim, world)
        outcome.append((cost, succeeded))

    sim.spawn(driver)
    sim.run()
    cost, succeeded = outcome[0]
    assert succeeded is False  # the failure surfaced to the caller
    # One initial attempt plus two retries -> three charged tool calls.
    assert cost == pytest.approx(3 * config.tool_cost)


def test_all_failing_tasks_surface() -> None:
    """With a certain-failure tool, every task surfaces a failure."""
    config = AgenticConfig(tool_failure_prob=1.0, max_retries=0, duration=60.0)
    kpis = run_sequential(1, config)
    assert kpis.completed == 0
    assert kpis.failed > 0


def test_batching_groups_concurrent_inference() -> None:
    """Under load a single server serves multi-request inference batches."""
    config = AgenticConfig(
        arrival_rate=5.0,
        num_servers=1,
        batch_size=8,
        agent_concurrency=30,
        duration=100.0,
    )
    kpis = run_sequential(2, config)
    assert kpis.mean_batch_size > 1.0
    assert kpis.peak_queue_depth > 1


# --- No-network enforcement (tech-stack §9, enforced-by-test). ---------------


def test_factory_completes_with_sockets_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model runs to completion with every socket entry point disabled."""

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the agentic example must not touch the network")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    # A real run under the trap: if any code path opened a socket it would raise.
    kpis = run_sequential(_MASTER, AgenticConfig(duration=40.0))
    assert kpis.completed + kpis.failed >= 0
    assert kpis.makespan <= 40.0


def test_example_package_imports_no_network_modules() -> None:
    """No source file in the package imports a network or LLM module."""
    package_root = (
        Path(__file__).resolve().parent.parent / "examples" / "agentic_workflow"
    )
    offenders: list[str] = []
    for source_file in sorted(package_root.rglob("*.py")):
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"), filename=str(source_file)
        )
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if name in _BANNED_MODULES or root in _BANNED_MODULES:
                    offenders.append(f"{source_file.name}: {name}")
    assert offenders == []


def test_no_llm_extra_installed_is_not_required() -> None:
    """The example needs no ``llmsim[llm]`` dependency to run."""
    with pytest.raises(ImportError):
        __import__("anthropic")
    # And it still runs a full simulation without it.
    kpis = run_sequential(3, AgenticConfig(duration=30.0))
    assert kpis.makespan <= 30.0


# --- Determinism (the cross-cutting roadmap gate). ---------------------------


def test_same_seed_same_result_sequential() -> None:
    """Two whole runs with the same seed produce identical KPIs."""
    config = AgenticConfig()
    assert run_sequential(_MASTER, config) == run_sequential(_MASTER, config)


def test_same_seed_same_result_factory() -> None:
    """The replication factory is a deterministic function of its seed stream."""
    tree = SeedTree(_MASTER)
    config = AgenticConfig()
    first = run_agentic_workflow(tree.stream(0, 0), config)
    second = run_agentic_workflow(tree.stream(0, 0), config)
    assert first == second


def test_kpi_snapshot() -> None:
    """Headline KPIs match the committed snapshot (drift guard)."""
    assert run_sequential(_MASTER, AgenticConfig()) == _SNAPSHOT
