"""Zone-sharded ride-hailing PDES trace-equivalence tests (roadmap 5.2b)."""

import pytest
from examples.ride_hailing.kpis import RideHailingConfig
from examples.ride_hailing.sharded import (
    ShardedKPIs,
    _merge,
    build_sharded_topology,
    run_sharded,
)

from llmsim.trace import Tracer

_MASTER = 20260712

#: num_zones divisible by every shard count under test.
_CONFIG = RideHailingConfig(num_zones=8, fleet_size=12, duration=120.0)


def _traces_equal(left: dict[int, Tracer], right: dict[int, Tracer]) -> bool:
    """Return whether every shard's trace records match bitwise."""
    return all(left[shard].records == right[shard].records for shard in left)


@pytest.mark.parametrize("shards", [1, 2, 4])
def test_threaded_equals_sequential_bitwise(shards: int) -> None:
    """The threaded run is bitwise-identical to the sequential reference."""
    seq_topo, seq_metrics, seq_tracers = build_sharded_topology(
        _CONFIG, shards, _MASTER, tracing=True
    )
    seq_topo.run(until=_CONFIG.duration, mode="sequential")

    thr_topo, thr_metrics, thr_tracers = build_sharded_topology(
        _CONFIG, shards, _MASTER, tracing=True
    )
    thr_topo.run(until=_CONFIG.duration)

    assert _merge(thr_metrics) == _merge(seq_metrics)
    assert _traces_equal(thr_tracers, seq_tracers)


@pytest.mark.parametrize("shards", [2, 4])
def test_cross_shard_migration_actually_happens(shards: int) -> None:
    """The multi-shard runs exercise cross-shard vehicle handoffs."""
    kpis = run_sharded(_CONFIG, shards=shards, seed=_MASTER, mode="sequential")
    assert kpis.migrations > 0
    assert kpis.served > 0


def test_repeated_threaded_runs_are_identical() -> None:
    """Two threaded runs of the same topology give identical KPIs."""
    first = run_sharded(_CONFIG, shards=4, seed=_MASTER)
    second = run_sharded(_CONFIG, shards=4, seed=_MASTER)
    assert first == second


def test_num_zones_must_divide_shards() -> None:
    """An indivisible partition is a loud error, not a silent misgrouping."""
    config = RideHailingConfig(num_zones=6, duration=40.0)
    with pytest.raises(ValueError, match="divisible"):
        run_sharded(config, shards=4)


def test_single_shard_has_no_migrations() -> None:
    """One shard owns every zone, so no trip ever crosses a boundary."""
    kpis = run_sharded(_CONFIG, shards=1, seed=_MASTER, mode="sequential")
    assert isinstance(kpis, ShardedKPIs)
    assert kpis.migrations == 0
