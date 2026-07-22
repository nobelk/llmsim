"""Backend reproducibility for the example factories (validation §checklist).

Both example factories must produce bit-identical result sets across the thread,
interpreter, and process backends for a fixed master seed, keyed by
``(config, replication)`` -- the executor-payloads-are-references guarantee. A
factory or config that captured a closure or a non-picklable object would fail
the importability/pickle check here, loudly, rather than silently on one backend.
"""

import pickle
from typing import Any

import pytest
from examples.agentic_workflow.kpis import AgenticConfig
from examples.agentic_workflow.model import run_agentic_workflow
from examples.ride_hailing.kpis import RideHailingConfig
from examples.ride_hailing.model import run_ride_hailing

from llmsim.parallel.backends import BackendName
from llmsim.parallel.replicate import Experiment
from tests.parallel_support import sequential_reference

_MASTER = 20260712
_BACKENDS: tuple[BackendName, ...] = ("threads", "interpreters", "processes")

#: Small configs that keep each replication a per-PR-fast smoke run.
_MODELS: list[tuple[Any, list[Any]]] = [
    (
        run_ride_hailing,
        [
            RideHailingConfig(duration=60.0),
            RideHailingConfig(fleet_size=12, duration=60.0),
        ],
    ),
    (
        run_agentic_workflow,
        [AgenticConfig(duration=50.0), AgenticConfig(num_servers=3, duration=50.0)],
    ),
]


@pytest.mark.parametrize(
    ("factory", "configs"), _MODELS, ids=["ride_hailing", "agentic_workflow"]
)
def test_all_backends_match_sequential_reference(
    factory: Any, configs: list[Any]
) -> None:
    """Every backend reproduces the sequential reference, and each other."""
    # The shared oracle every parallel suite compares against.
    reference = sequential_reference(factory, configs, 3, _MASTER)
    result_sets: dict[BackendName, Any] = {}
    for kind in _BACKENDS:
        try:
            results = Experiment(factory, configs, master_seed=_MASTER).run(
                replications=3, backend=kind, max_workers=3
            )
        except NotImplementedError as error:  # pragma: no cover - platform gap
            pytest.skip(f"{kind} backend unavailable: {error}")
        assert {key: r.value for key, r in results.items()} == reference, kind
        result_sets[kind] = results
    values = list(result_sets.values())
    for other in values[1:]:
        assert other == values[0]


@pytest.mark.parametrize(
    ("factory", "configs"), _MODELS, ids=["ride_hailing", "agentic_workflow"]
)
def test_factory_and_configs_are_picklable(factory: Any, configs: list[Any]) -> None:
    """Factory and every config survive a pickle round-trip (transport check)."""
    # Safe: this round-trips our own trusted, in-process objects to assert they
    # are transportable, exactly as the process backend transports them. It never
    # loads pickle data from an external or untrusted source.
    assert pickle.loads(pickle.dumps(factory)) is factory
    for config in configs:
        assert pickle.loads(pickle.dumps(config)) == config
