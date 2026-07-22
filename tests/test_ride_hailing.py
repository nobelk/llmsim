"""Ride-hailing core-model tests: behavior, policies, determinism (roadmap 5.1)."""

import random

from examples.ride_hailing.kpis import RideHailingConfig, RideHailingKPIs
from examples.ride_hailing.model import (
    ZoneGraph,
    _recharge,
    _Vehicle,
    _World,
    run_ride_hailing,
    run_sequential,
)
from examples.ride_hailing.policies import PowerOfD, closest_available, get_policy

from llmsim import Sim
from llmsim.rand.streams import SeedTree

_MASTER = 20260712

#: The committed headline KPIs for the default scenario at the canonical seed.
#: Regenerate deliberately (never loosen to hide drift): a change here is a
#: change in model behavior that must be understood.
_SNAPSHOT_CLOSEST = RideHailingKPIs(
    mean_wait=5.694617137,
    served=167,
    abandoned=96,
    abandonment_rate=0.365019011,
    mean_utilization=0.949344815,
    makespan=200.0,
)


# --- Behavioral tests. -------------------------------------------------------


def test_serves_requests() -> None:
    """A healthy fleet serves a positive number of requests."""
    kpis = run_sequential(_MASTER, RideHailingConfig())
    assert kpis.served > 0
    assert kpis.mean_wait >= 0.0


def test_over_capacity_requests_abandon() -> None:
    """A saturated one-vehicle fleet with a short patience window abandons."""
    config = RideHailingConfig(
        fleet_size=1, request_rate=3.0, patience=1.0, duration=100.0
    )
    kpis = run_sequential(_MASTER, config)
    assert kpis.abandoned > 0
    assert kpis.abandonment_rate > 0.0


def test_recharge_blocks_on_full_station() -> None:
    """Two depleted vehicles at a capacity-1 station recharge in series."""
    config = RideHailingConfig(
        charging_zones=(0,),
        charging_capacity=1,
        battery_capacity=100.0,
        charge_rate=10.0,
    )
    sim = Sim(seed=0)
    world = _World(sim, config)
    # Both vehicles start empty in the (only) charging zone: no travel, equal
    # 10.0-unit charges. Serialized -> the run ends at 20.0, not 10.0.
    for vehicle_id in (0, 1):
        vehicle = _Vehicle(vehicle_id, zone=0, soc=0.0)
        sim.spawn(_recharge, world, vehicle)
    sim.run()
    assert sim.now == 20.0


# --- Dispatch policies. ------------------------------------------------------


class _FakeGraph:
    """A minimal :class:`TravelGraph` returning a fixed deadhead table."""

    def pickup_time(self, from_zone: int, to_zone: int) -> float:
        return float(abs(from_zone - to_zone))


class _FakeVehicle:
    """A minimal :class:`Candidate`."""

    def __init__(self, vehicle_id: int, zone: int) -> None:
        self.vehicle_id = vehicle_id
        self.zone = zone


def test_closest_available_breaks_ties_by_id() -> None:
    """Equal-distance candidates resolve to the lowest vehicle id."""
    graph = _FakeGraph()
    rng = random.Random(0)
    # Vehicles 3 and 1 are both one hop from origin 2; id breaks the tie.
    candidates = [_FakeVehicle(3, 3), _FakeVehicle(1, 1), _FakeVehicle(5, 5)]
    chosen = closest_available(candidates, origin_zone=2, graph=graph, rng=rng)
    assert chosen.vehicle_id == 1


def test_power_of_d_is_deterministic_and_in_sample() -> None:
    """``power_of_d`` samples deterministically and picks within the sample."""
    graph = _FakeGraph()
    candidates = [_FakeVehicle(vehicle_id, vehicle_id) for vehicle_id in range(10)]
    policy = PowerOfD(3)
    first = policy(candidates, origin_zone=0, graph=graph, rng=random.Random(7))
    second = policy(candidates, origin_zone=0, graph=graph, rng=random.Random(7))
    assert first.vehicle_id == second.vehicle_id


def test_power_of_d_reduces_to_nearest_when_d_covers_fleet() -> None:
    """With ``d`` >= fleet size every candidate is sampled, so it is the nearest."""
    graph = _FakeGraph()
    candidates = [_FakeVehicle(vehicle_id, vehicle_id) for vehicle_id in range(4)]
    policy = PowerOfD(10)
    chosen = policy(candidates, origin_zone=0, graph=graph, rng=random.Random(1))
    assert chosen.vehicle_id == 0


def test_both_policies_run_end_to_end() -> None:
    """Both dispatch policies drive a full run and give distinct KPIs."""
    closest = run_sequential(_MASTER, RideHailingConfig(policy="closest_available"))
    powered = run_sequential(
        _MASTER, RideHailingConfig(policy="power_of_d", policy_d=2)
    )
    assert closest.served > 0
    assert powered.served > 0
    assert closest != powered


def test_get_policy_rejects_unknown() -> None:
    """An unknown policy name is a loud error, not a silent default."""
    try:
        get_policy("teleport")
    except ValueError as error:
        assert "teleport" in str(error)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("get_policy accepted an unknown policy")


# --- Zone graph. -------------------------------------------------------------


def test_min_interzone_is_the_lookahead_floor() -> None:
    """The minimum over all distinct-zone pairs equals the declared lookahead."""
    config = RideHailingConfig(num_zones=6, min_interzone_time=3.0, interzone_step=1.5)
    graph = ZoneGraph(config)
    pairwise = [
        graph.interzone_time(i, j)
        for i in range(config.num_zones)
        for j in range(config.num_zones)
        if i != j
    ]
    assert min(pairwise) == graph.min_lookahead() == 3.0


# --- Determinism (the cross-cutting roadmap gate). ---------------------------


def test_same_seed_same_result_sequential() -> None:
    """Two whole runs with the same seed produce identical KPIs."""
    config = RideHailingConfig()
    assert run_sequential(_MASTER, config) == run_sequential(_MASTER, config)


def test_same_seed_same_result_factory() -> None:
    """The replication factory is a deterministic function of its seed stream."""
    tree = SeedTree(_MASTER)
    config = RideHailingConfig()
    first = run_ride_hailing(tree.stream(0, 0), config)
    second = run_ride_hailing(tree.stream(0, 0), config)
    assert first == second


def test_kpi_snapshot() -> None:
    """Headline KPIs match the committed snapshot (drift guard)."""
    assert run_sequential(_MASTER, RideHailingConfig()) == _SNAPSHOT_CLOSEST


def test_run_respects_horizon() -> None:
    """No event is processed past the configured horizon."""
    config = RideHailingConfig(duration=50.0)
    kpis = run_sequential(1, config)
    assert kpis.makespan <= config.duration
