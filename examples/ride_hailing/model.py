"""Autonomous ride-hailing fleet -- the core sequential model (roadmap 5.1).

A robotaxi fleet serves Poisson trip requests over a discrete **zone graph**.
Each vehicle is a generator process running the full lifecycle -- idle, drive to
pickup, carry the trip, drop off, reposition, recharge -- on one ``Sim``.
Charging stations are finite-capacity ``Resource``s; idle vehicles wait in a
``FilterStore`` and are pulled out by a pluggable dispatch policy that ranks
candidates across *all* zones. Requests abandon if unassigned within a patience
window.

The zone graph uses **fixed inter-zone travel times with a strictly positive
minimum** (a ring metric). That minimum is exactly the channel lookahead the
zone-sharded PDES variant (roadmap 5.2b) needs, so the core model and the PDES
showcase share one geometry. Continuous coordinates would give adjacent points a
~0 lookahead and no feasible sharding -- hence the discrete graph
(``specs/phase-5-domain-example/requirements.md`` Decisions).

Everything stochastic draws from ``sim.rng`` and every tie is broken by ascending
vehicle id, so the run is a deterministic function of ``(seed, config)``.
"""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Generator
from typing import Any

from examples.ride_hailing.kpis import (
    KpiAccumulator,
    RideHailingConfig,
    RideHailingKPIs,
)
from examples.ride_hailing.policies import DispatchPolicy, get_policy
from llmsim import Event, FilterStore, Resource, Sim
from llmsim.rand.streams import SeedStream


class ZoneGraph:
    """A ring of zones with fixed inter-zone travel times (positive minimum).

    Inter-zone time grows with ring distance from a strictly positive floor;
    intra-zone trips draw from an exponential distribution. The floor
    (:meth:`min_lookahead`) is the sharded variant's channel lookahead.
    """

    __slots__ = ("num_zones", "_min_interzone", "_step", "_intra_mean")

    def __init__(self, config: RideHailingConfig) -> None:
        """Derive the graph deterministically from *config*."""
        self.num_zones = config.num_zones
        self._min_interzone = config.min_interzone_time
        self._step = config.interzone_step
        self._intra_mean = config.intra_zone_mean

    def _ring_distance(self, from_zone: int, to_zone: int) -> int:
        """Return the shorter hop count between two zones around the ring."""
        raw = abs(from_zone - to_zone)
        return min(raw, self.num_zones - raw)

    def interzone_time(self, from_zone: int, to_zone: int) -> float:
        """Return the fixed travel time between two *distinct* zones.

        Equals :meth:`min_lookahead` at ring distance 1 and grows from there, so
        the minimum over all distinct-zone pairs is strictly positive.
        """
        return (
            self._min_interzone
            + (self._ring_distance(from_zone, to_zone) - 1) * self._step
        )

    def pickup_time(self, from_zone: int, to_zone: int) -> float:
        """Return deadhead time to reposition a vehicle (0 within a zone)."""
        if from_zone == to_zone:
            return 0.0
        return self.interzone_time(from_zone, to_zone)

    def trip_time(self, origin: int, destination: int, rng: random.Random) -> float:
        """Return the carried-trip duration (stochastic only within a zone)."""
        if origin == destination:
            return (
                self._intra_mean
                if self._intra_mean <= 0
                else rng.expovariate(1.0 / self._intra_mean)
            )
        return self.interzone_time(origin, destination)

    def min_lookahead(self) -> float:
        """Return the strictly positive minimum inter-zone travel time."""
        return self._min_interzone


class _Vehicle:
    """One robotaxi: its identity, current zone, charge, and dispatch handle."""

    __slots__ = ("vehicle_id", "zone", "soc", "available")

    def __init__(self, vehicle_id: int, zone: int, soc: float) -> None:
        self.vehicle_id = vehicle_id
        self.zone = zone
        self.soc = soc
        #: Resolved with a ``_Request`` when the dispatcher pulls this vehicle
        #: out of the idle store; reset before each idle wait.
        self.available: Event[Any] | None = None

    def __eq__(self, other: object) -> bool:
        """Two vehicles are equal iff they share an id (stable identity).

        Vehicle ids are unique within a run, so this matches object identity for
        model logic, while letting a traced payload compare equal across two runs
        (threaded vs sequential) -- the basis of the trace-equivalence test.
        """
        return isinstance(other, _Vehicle) and other.vehicle_id == self.vehicle_id

    def __hash__(self) -> int:
        """Hash by the stable vehicle id."""
        return hash(self.vehicle_id)


class _Request:
    """One trip request: its route, arrival time, and settlement flag."""

    __slots__ = ("origin", "destination", "created", "settled")

    def __init__(self, origin: int, destination: int, created: float) -> None:
        self.origin = origin
        self.destination = destination
        self.created = created
        #: Set once the request is either assigned or abandoned -- guards the
        #: race between the patience timer and a late waiting-queue handoff.
        self.settled = False

    def __eq__(self, other: object) -> bool:
        """Equal iff route and arrival time match (the immutable identity).

        The mutable ``settled`` flag is excluded so a request that appears as a
        traced event value compares equal across two runs -- the basis of the
        trace-equivalence test.
        """
        return isinstance(other, _Request) and (
            other.origin,
            other.destination,
            other.created,
        ) == (self.origin, self.destination, self.created)

    def __hash__(self) -> int:
        """Hash by the immutable route and arrival time."""
        return hash((self.origin, self.destination, self.created))


def take_waiting_request(pending: deque[_Request]) -> _Request | None:
    """Pop and settle the oldest still-waiting request in *pending*, or ``None``.

    Shared by the core model and the sharded variant -- both drain a per-owner
    FIFO of requests that arrived to an empty idle set.
    """
    while pending:
        request = pending.popleft()
        if not request.settled:
            request.settled = True
            return request
    return None


def drive_and_charge(
    sim: Sim,
    config: RideHailingConfig,
    graph: ZoneGraph,
    vehicle: _Vehicle,
    station_zone: int,
    station: Resource,
) -> Generator[Event[Any], Any, None]:
    """Drive *vehicle* to *station_zone* and recharge, blocking on a full station.

    The shared vehicle-charging physics (deadhead, deplete, queue, top up) used by
    both the core model and the sharded variant; only the choice of station
    differs between them.
    """
    move = graph.pickup_time(vehicle.zone, station_zone)
    if move > 0:
        yield sim.delay(move)
        vehicle.soc -= move * config.consumption_per_time
        vehicle.zone = station_zone
    with station.request() as slot:
        yield slot
        charge_time = (config.battery_capacity - vehicle.soc) / config.charge_rate
        if charge_time > 0:
            yield sim.delay(charge_time)
        vehicle.soc = config.battery_capacity


class _World:
    """Shared, single-thread simulation state for one ride-hailing run."""

    __slots__ = (
        "config",
        "graph",
        "policy",
        "idle_store",
        "stations",
        "pending",
        "kpis",
    )

    def __init__(self, sim: Sim, config: RideHailingConfig) -> None:
        self.config = config
        self.graph = ZoneGraph(config)
        self.policy: DispatchPolicy = get_policy(config.policy, d=config.policy_d)
        self.idle_store: FilterStore[_Vehicle] = FilterStore(sim)
        self.stations: dict[int, Resource] = {
            zone: Resource(sim, capacity=config.charging_capacity)
            for zone in config.charging_zones
        }
        #: FIFO of requests that arrived to an empty idle set and are waiting.
        self.pending: deque[_Request] = deque()
        self.kpis = KpiAccumulator()

    def take_waiting_request(self) -> _Request | None:
        """Pop and settle the oldest still-waiting request, or return ``None``."""
        return take_waiting_request(self.pending)

    def nearest_charging_zone(self, from_zone: int) -> int:
        """Return the charging zone nearest *from_zone* (id breaks ties)."""
        return min(
            self.config.charging_zones,
            key=lambda zone: (self.graph.pickup_time(from_zone, zone), zone),
        )


def _serve(
    sim: Sim, world: _World, vehicle: _Vehicle, request: _Request
) -> Generator[Event[Any], Any, None]:
    """Drive one assigned request end to end, then reposition and recharge."""
    config, graph, kpis = world.config, world.graph, world.kpis
    kpis.record_served(sim.now - request.created)
    busy_start = sim.now

    deadhead = graph.pickup_time(vehicle.zone, request.origin)
    if deadhead > 0:
        yield sim.delay(deadhead)
        vehicle.soc -= deadhead * config.consumption_per_time
        vehicle.zone = request.origin

    trip = graph.trip_time(request.origin, request.destination, sim.rng)
    yield sim.delay(trip)
    vehicle.soc -= trip * config.consumption_per_time
    vehicle.zone = request.destination

    if sim.rng.random() < config.reposition_prob:
        target = sim.rng.randrange(config.num_zones)
        move = graph.pickup_time(vehicle.zone, target)
        if move > 0:
            yield sim.delay(move)
            vehicle.soc -= move * config.consumption_per_time
            vehicle.zone = target

    if vehicle.soc < config.recharge_threshold:
        yield from _recharge(sim, world, vehicle)

    kpis.record_busy(sim.now - busy_start)


def _recharge(
    sim: Sim, world: _World, vehicle: _Vehicle
) -> Generator[Event[Any], Any, None]:
    """Drive to the nearest station and recharge, blocking on a full station."""
    station_zone = world.nearest_charging_zone(vehicle.zone)
    yield from drive_and_charge(
        sim,
        world.config,
        world.graph,
        vehicle,
        station_zone,
        world.stations[station_zone],
    )


def _vehicle_process(
    sim: Sim, world: _World, vehicle: _Vehicle
) -> Generator[Event[Any], Any, None]:
    """Run one vehicle's whole lifecycle until the horizon is reached."""
    while sim.now < world.config.duration:
        request = world.take_waiting_request()
        if request is None:
            vehicle.available = sim.event()
            yield world.idle_store.put(vehicle)
            request = yield vehicle.available
        yield from _serve(sim, world, vehicle, request)


def _request_process(
    sim: Sim, world: _World, request: _Request
) -> Generator[Event[Any], Any, None]:
    """Assign a request to a policy-chosen idle vehicle, or abandon it."""
    idle = world.idle_store.items
    if idle:
        chosen_id = world.policy(idle, request.origin, world.graph, sim.rng).vehicle_id
        vehicle: _Vehicle = yield world.idle_store.get(
            lambda candidate: candidate.vehicle_id == chosen_id
        )
        request.settled = True
        assert vehicle.available is not None
        vehicle.available.succeed(request)
        return

    world.pending.append(request)
    yield sim.delay(world.config.patience)
    if not request.settled:
        request.settled = True
        world.kpis.record_abandoned()


def _request_source(sim: Sim, world: _World) -> Generator[Event[Any], Any, None]:
    """Generate Poisson trip requests until the horizon."""
    config = world.config
    rng = sim.rng
    while True:
        yield sim.delay(rng.expovariate(config.request_rate))
        if sim.now >= config.duration:
            return
        origin = rng.randrange(config.num_zones)
        destination = rng.randrange(config.num_zones)
        sim.spawn(_request_process, world, _Request(origin, destination, sim.now))


def _simulate(sim: Sim, config: RideHailingConfig) -> RideHailingKPIs:
    """Build and run one ride-hailing simulation, returning its KPIs."""
    world = _World(sim, config)
    for vehicle_id in range(config.fleet_size):
        vehicle = _Vehicle(
            vehicle_id, vehicle_id % config.num_zones, config.battery_capacity
        )
        sim.spawn(_vehicle_process, world, vehicle)
    sim.spawn(_request_source, world)
    sim.run(until=config.duration)
    return world.kpis.finalize(
        fleet_size=config.fleet_size,
        horizon=config.duration,
        makespan=sim.now,
    )


def run_ride_hailing(stream: SeedStream, config: RideHailingConfig) -> RideHailingKPIs:
    """Run the ride-hailing model from a replication seed stream (the factory).

    Importable and closure-free so ``Experiment`` can submit it to any backend
    as an ``(importable callable, seed spec, config)`` reference
    (``specs/tech-stack.md`` §5).

    Args:
        stream: The replication's seed stream; ``stream.rng()`` seeds the run.
        config: The scenario to simulate.

    Returns:
        The run's headline KPIs.
    """
    return _simulate(Sim(rng=stream.rng()), config)


def run_sequential(seed: int, config: RideHailingConfig) -> RideHailingKPIs:
    """Run the ride-hailing model from a bare integer seed.

    The single-run entry point (behavioral tests, the sharded reference oracle):
    same seed and config give identical KPIs on any build.

    Args:
        seed: Master seed for the run's single random stream.
        config: The scenario to simulate.

    Returns:
        The run's headline KPIs.
    """
    return _simulate(Sim(seed=seed), config)
