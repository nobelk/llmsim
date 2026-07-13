"""Experiment API: keying, determinism, fail-fast, transport errors (2.3)."""

import pytest

from llmsim.parallel.backends import BackendName, TransportError
from llmsim.parallel.replicate import (
    Experiment,
    ReplicationError,
    ReplicationResult,
    run_replications,
)
from llmsim.rand.streams import child_seed
from tests import parallel_support as support

_MASTER = 20260712
_CONFIGS = [
    {"arrival_rate": 0.5, "customers": 50},
    {"arrival_rate": 0.9, "customers": 50},
    {"arrival_rate": 1.2, "customers": 50},
]


# --- The explicit master_seed is required (no ambient default). ---------------


def test_master_seed_is_required() -> None:
    with pytest.raises(TypeError):
        Experiment(support.trivial_task, [{}])  # type: ignore[call-arg]


def test_master_seed_must_be_int() -> None:
    with pytest.raises(TypeError, match="master_seed"):
        Experiment(support.trivial_task, [{}], master_seed="7")  # type: ignore[arg-type]


def test_factory_validated_at_construction() -> None:
    from llmsim.parallel.backends import FactoryValidationError

    with pytest.raises(FactoryValidationError, match="lambda"):
        Experiment(lambda stream, config: None, [{}], master_seed=_MASTER)


# --- M configs x N replications -> M x N results keyed by identity. -----------


def test_results_keyed_by_config_and_replication() -> None:
    experiment = Experiment(support.mm1_kpis, _CONFIGS, master_seed=_MASTER)
    results = experiment.run(replications=4, backend="threads")
    assert set(results) == {(c, r) for c in range(3) for r in range(4)}
    for (config_index, replication_index), result in results.items():
        assert isinstance(result, ReplicationResult)
        assert result.config_index == config_index
        assert result.replication_index == replication_index
        assert result.seed == child_seed(_MASTER, config_index, replication_index)


def test_result_dict_iterates_in_key_order() -> None:
    experiment = Experiment(support.mm1_kpis, _CONFIGS, master_seed=_MASTER)
    results = experiment.run(replications=2, backend="threads", max_workers=4)
    assert list(results) == sorted(results)


# --- Same explicit master_seed -> identical keyed result sets. ----------------


def test_same_seed_same_result_across_runs() -> None:
    experiment = Experiment(support.mm1_kpis, _CONFIGS, master_seed=_MASTER)
    first = experiment.run(replications=3, backend="threads", max_workers=4)
    second = experiment.run(replications=3, backend="threads", max_workers=4)
    assert first == second


def test_results_independent_of_worker_count() -> None:
    experiment = Experiment(support.mm1_kpis, _CONFIGS, master_seed=_MASTER)
    serial = experiment.run(replications=3, backend="threads", max_workers=1)
    wide = experiment.run(replications=3, backend="threads", max_workers=8)
    assert serial == wide


def test_parallel_reproduces_sequential_reference() -> None:
    """A KPI study reproduces the sequential per-replication results."""
    sequential = support.sequential_reference(support.mm1_kpis, _CONFIGS, 3, _MASTER)
    experiment = Experiment(support.mm1_kpis, _CONFIGS, master_seed=_MASTER)
    parallel = experiment.run(replications=3, backend="threads", max_workers=4)
    assert {key: result.value for key, result in parallel.items()} == sequential


# --- Functional wrapper. -------------------------------------------------------


def test_run_replications_wrapper() -> None:
    direct = Experiment(support.mm1_kpis, _CONFIGS, master_seed=_MASTER).run(
        replications=2, backend="threads"
    )
    wrapped = run_replications(
        support.mm1_kpis,
        _CONFIGS,
        master_seed=_MASTER,
        replications=2,
        backend="threads",
    )
    assert wrapped == direct


# --- Fail-fast contract: a failing replication names its identity. ------------


def test_failing_replication_raises_naming_identity() -> None:
    experiment = Experiment(support.failing_factory, [{}], master_seed=_MASTER)
    with pytest.raises(ReplicationError, match=r"config_index=0.*replication_index=0"):
        experiment.run(replications=1, backend="threads")


def test_failure_chains_original_exception() -> None:
    experiment = Experiment(support.failing_factory, [{}], master_seed=_MASTER)
    with pytest.raises(ReplicationError) as excinfo:
        experiment.run(replications=1, backend="threads")
    assert isinstance(excinfo.value.__cause__, ValueError)


# --- Transport validation: unpicklable configs and results. -------------------


def test_unpicklable_config_rejected_before_dispatch() -> None:
    experiment = Experiment(
        support.echo_config, [{"handle": lambda: None}], master_seed=_MASTER
    )
    with pytest.raises(TransportError, match="config 0"):
        experiment.run(replications=1, backend="processes")


def test_unpicklable_config_fine_on_threads() -> None:
    config = {"handle": lambda: None}
    experiment = Experiment(support.echo_config, [config], master_seed=_MASTER)
    results = experiment.run(replications=1, backend="threads")
    assert results[(0, 0)].value is config


@pytest.mark.parametrize("kind", ["interpreters", "processes"])
def test_unpicklable_result_raises_actionable_error(kind: BackendName) -> None:
    experiment = Experiment(support.unpicklable_result, [{}], master_seed=_MASTER)
    with pytest.raises(TransportError, match=r"config_index=0.*replication_index=0"):
        experiment.run(replications=1, backend=kind)


# --- Cross-backend equality for a picklable model (smoke; full suite in 2.5). -


def test_process_backend_matches_threads() -> None:
    experiment = Experiment(support.mm1_kpis, _CONFIGS[:2], master_seed=_MASTER)
    threads = experiment.run(replications=2, backend="threads")
    processes = experiment.run(replications=2, backend="processes", max_workers=2)
    assert threads == processes


# --- ReplicationResult value semantics. ----------------------------------------


def test_replication_result_equality_and_repr() -> None:
    experiment = Experiment(support.trivial_task, [{}], master_seed=_MASTER)
    result = experiment.run(replications=1, backend="threads")[(0, 0)]
    assert "config_index=0" in repr(result)
    assert result == result


def test_empty_configs_yield_empty_results() -> None:
    experiment = Experiment(support.trivial_task, [], master_seed=_MASTER)
    assert experiment.run(replications=3, backend="threads") == {}


def test_zero_replications_yield_empty_results() -> None:
    experiment = Experiment(support.trivial_task, [{}], master_seed=_MASTER)
    assert experiment.run(replications=0, backend="threads") == {}
