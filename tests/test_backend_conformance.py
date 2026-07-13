"""Backend conformance: identical result sets across all three backends (2.5).

The concrete proof of the reproducibility guarantee: for fixed seeds, the
thread, interpreter, and process backends produce result sets equal to each
other and to the sequential reference, on the canonical models. CI runs this
file on 3.14 and 3.14t with PYTHON_GIL=0/1, so the guarantee is asserted on
every supported build.
"""

import sys
from typing import Any

import pytest

from llmsim.parallel.backends import BackendName, CancelToken
from llmsim.parallel.replicate import Experiment, _run_replication
from llmsim.rand.streams import SeedTree
from tests import parallel_support as support

_MASTER = 20260712
_BACKENDS: tuple[BackendName, ...] = ("threads", "interpreters", "processes")

#: The canonical models: (factory, configs) pairs exercising the resource and
#: store machinery with per-stream randomness.
_CANONICAL_MODELS = [
    (
        support.mm1_kpis,
        [
            {"arrival_rate": 0.5, "customers": 40},
            {"arrival_rate": 0.9, "customers": 40},
        ],
    ),
    (
        support.store_throughput,
        [{"items": 40}, {"items": 60}],
    ),
]


def _sequential_reference(
    factory: Any, configs: list[dict[str, float]], replications: int
) -> dict[tuple[int, int], Any]:
    """The shared oracle, bound to this module's master seed."""
    return support.sequential_reference(factory, configs, replications, _MASTER)


@pytest.mark.parametrize(
    ("factory", "configs"),
    _CANONICAL_MODELS,
    ids=["mm1", "store"],
)
def test_all_backends_match_sequential_reference(
    factory: Any, configs: list[dict[str, float]]
) -> None:
    reference = _sequential_reference(factory, configs, replications=3)
    result_sets = {}
    for kind in _BACKENDS:
        experiment = Experiment(factory, configs, master_seed=_MASTER)
        results = experiment.run(replications=3, backend=kind, max_workers=3)
        assert {key: r.value for key, r in results.items()} == reference, kind
        result_sets[kind] = results
    assert result_sets["threads"] == result_sets["interpreters"]
    assert result_sets["interpreters"] == result_sets["processes"]


@pytest.mark.parametrize("max_workers", [1, 2, 5])
def test_worker_count_never_changes_results(max_workers: int) -> None:
    experiment = Experiment(support.mm1_kpis, [{"customers": 40}], master_seed=_MASTER)
    results = experiment.run(
        replications=4, backend="processes", max_workers=max_workers
    )
    reference = _sequential_reference(
        support.mm1_kpis, [{"customers": 40}], replications=4
    )
    assert {key: r.value for key, r in results.items()} == reference


def test_auto_backend_matches_reference_on_this_build() -> None:
    """Whatever `auto` resolves to on the current build, results are identical."""
    results = Experiment(
        support.store_throughput, [{"items": 40}], master_seed=_MASTER
    ).run(replications=3, backend="auto", max_workers=2)
    reference = _sequential_reference(
        support.store_throughput, [{"items": 40}], replications=3
    )
    assert {key: r.value for key, r in results.items()} == reference


# --- GIL re-enable detection through the worker runner (integration seam). ----


def test_worker_runner_warns_when_model_import_reenables_gil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model import that flips the GIL back on is loudly named."""
    states = iter([False, True])  # before import -> after import
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: next(states))
    stream = SeedTree(_MASTER).stream(0, 0)
    with pytest.warns(RuntimeWarning, match="tests.parallel_support"):
        _run_replication(
            "tests.parallel_support",
            "trivial_task",
            stream,
            {},
            False,
            CancelToken(),
            False,
            False,
        )


def test_worker_runner_quiet_when_gil_state_stable() -> None:
    stream = SeedTree(_MASTER).stream(0, 0)
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        value = _run_replication(
            "tests.parallel_support",
            "trivial_task",
            stream,
            {},
            False,
            CancelToken(),
            False,
            False,
        )
    assert value == support.trivial_task(stream, {})
