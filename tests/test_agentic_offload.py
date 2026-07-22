"""Strict-mode offload trace-equivalence tests (roadmap 5.4b)."""

import pytest
from examples.agentic_workflow.kpis import AgenticConfig
from examples.agentic_workflow.model import run_sequential
from examples.agentic_workflow.offload import (
    run_agentic_offload,
    run_offload_showcase,
    run_offload_traced,
)

from llmsim.parallel.offload import OffloadBackendName
from llmsim.rand.streams import SeedTree

_MASTER = 20260712

#: Small scenario keeping the CPU-heavy score cheap for a per-PR smoke run.
_CONFIG = AgenticConfig(duration=30.0, max_tokens=64)

#: Real worker-pool backends compared against the inline reference.
_POOLED: tuple[OffloadBackendName, ...] = ("threads", "interpreters", "processes")


@pytest.mark.parametrize("backend", _POOLED)
def test_offloaded_policy_equals_inline_bitwise(backend: OffloadBackendName) -> None:
    """A worker-pool run is bitwise-identical to the inline reference (strict)."""
    reference_kpis, reference_records = run_offload_traced(
        _MASTER, _CONFIG, backend="inline"
    )
    try:
        kpis, records = run_offload_traced(_MASTER, _CONFIG, backend=backend)
    except NotImplementedError as error:  # pragma: no cover - platform gap
        pytest.skip(f"{backend} offload backend unavailable: {error}")
    assert kpis == reference_kpis
    assert records == reference_records


def test_offload_factory_is_deterministic() -> None:
    """The offload factory is a deterministic function of its seed stream."""
    tree = SeedTree(_MASTER)
    first = run_agentic_offload(tree.stream(0, 0), _CONFIG)
    second = run_agentic_offload(tree.stream(0, 0), _CONFIG)
    assert first == second


def test_offloaded_scoring_changes_cost() -> None:
    """The offloaded score is really consumed, not dead work."""
    with_offload = run_offload_showcase(_MASTER, _CONFIG, backend="inline")
    without_offload = run_sequential(_MASTER, _CONFIG)
    assert with_offload.completed > 0
    # The scorer folds a positive score into cost, so the offloaded run costs more.
    assert with_offload.mean_cost > without_offload.mean_cost
