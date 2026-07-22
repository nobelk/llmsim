"""Zone-sharded ride-hailing PDES variant (roadmap 5.2b).

The Phase 3 showcase: the fleet is partitioned into zone-group **shards**, one
``Sim`` each, run thread-per-shard. Each shard serves its own requests from its
own fleet with the same deterministic ``closest_available`` dispatch as the core
model; a trip whose destination lies in *another* zone group becomes a **vehicle
migration** -- a channel message carrying plain ``(vehicle_id, soc, zone)`` data
with ``delay = trip_time``. Because every distinct-zone trip time is at least the
**minimum inter-zone travel time**, that minimum is the natural channel lookahead
(``ZoneGraph.min_lookahead``), and no cross-shard message can reorder against a
shard's local events.

Global cross-zone *dispatch* (ranking idle vehicles a shard does not own) is not
share-nothing-decomposable, so the sharded variant uses local dispatch plus
migration rather than the monolithic model's global ranking -- an honest PDES
decomposition, not a bitwise clone of the Group 1 model. The guarantee it proves
is the Phase 3 one: the threaded run is **bitwise-identical to the sequential
reference** (``mode="sequential"``) of the same topology, at 1/2/4 shards.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from examples.ride_hailing.kpis import RideHailingConfig
from examples.ride_hailing.model import (
    ZoneGraph,
    _Request,
    _Vehicle,
    drive_and_charge,
    take_waiting_request,
)
from examples.ride_hailing.policies import get_policy
from llmsim import Event, FilterStore, Resource, Sim
from llmsim.parallel.pdes import Channel, ShardedSim, ShardPorts
from llmsim.trace import Tracer, trace


class _ShardMetrics:
    """Per-shard KPI tally, summed across shards on merge."""

    __slots__ = ("served", "abandoned", "wait_sum", "trips", "migrations")

    def __init__(self) -> None:
        """Start an empty tally."""
        self.served = 0
        self.abandoned = 0
        self.wait_sum = 0.0
        self.trips = 0
        self.migrations = 0


@dataclass(frozen=True, slots=True)
class ShardedKPIs:
    """Merged headline outcomes of one zone-sharded ride-hailing run."""

    #: Requests served across all shards.
    served: int
    #: Requests that abandoned across all shards.
    abandoned: int
    #: Mean rider wait time (served requests only).
    mean_wait: float
    #: Completed trips across all shards.
    trips: int
    #: Cross-shard vehicle migrations.
    migrations: int


def _partition(num_zones: int, shards: int) -> list[int]:
    """Return the shard index owning each zone (contiguous groups)."""
    if num_zones % shards != 0:
        raise ValueError(
            f"num_zones ({num_zones}) must be divisible by shards ({shards})"
        )
    band = num_zones // shards
    return [zone // band for zone in range(num_zones)]


class _Shard:
    """Per-shard state: local fleet, stations, dispatch, and metrics."""

    __slots__ = (
        "index",
        "config",
        "graph",
        "zone_to_shard",
        "policy",
        "idle_store",
        "stations",
        "pending",
        "out_channels",
        "metrics",
    )

    def __init__(
        self,
        sim: Sim,
        index: int,
        config: RideHailingConfig,
        zone_to_shard: list[int],
        metrics: _ShardMetrics,
    ) -> None:
        self.index = index
        self.config = config
        self.graph = ZoneGraph(config)
        self.zone_to_shard = zone_to_shard
        self.policy = get_policy(config.policy, d=config.policy_d)
        self.idle_store: FilterStore[_Vehicle] = FilterStore(sim)
        local_charging = self._local_charging_zone()
        self.stations: dict[int, Resource] = {
            local_charging: Resource(sim, capacity=config.charging_capacity)
        }
        self.pending: deque[_Request] = deque()
        self.out_channels: dict[int, Channel] = {}
        self.metrics = metrics

    def _local_charging_zone(self) -> int:
        """Return this shard's single charging zone (its first zone)."""
        return self.zone_to_shard.index(self.index)

    def take_waiting_request(self) -> _Request | None:
        """Pop and settle the oldest still-waiting local request, or ``None``."""
        return take_waiting_request(self.pending)

    def record_served(self, wait: float) -> None:
        """Record a served request and its wait time."""
        self.metrics.served += 1
        self.metrics.wait_sum += wait

    def record_abandoned(self) -> None:
        """Record an abandoned request."""
        self.metrics.abandoned += 1

    def record_trip(self, *, migrated: bool) -> None:
        """Record a completed trip, flagging a cross-shard migration."""
        self.metrics.trips += 1
        if migrated:
            self.metrics.migrations += 1


def _recharge(
    sim: Sim, shard: _Shard, vehicle: _Vehicle
) -> Generator[Event[Any], Any, None]:
    """Recharge locally, blocking on the shard's (finite) charging station."""
    station_zone = shard._local_charging_zone()
    yield from drive_and_charge(
        sim,
        shard.config,
        shard.graph,
        vehicle,
        station_zone,
        shard.stations[station_zone],
    )


def _vehicle_loop(
    sim: Sim, shard: _Shard, vehicle: _Vehicle
) -> Generator[Event[Any], Any, None]:
    """Serve local requests; migrate to another shard on a cross-group trip."""
    config, graph = shard.config, shard.graph
    while True:
        # Recharge a depleted vehicle before it serves again -- whether it just
        # finished a local trip or arrived as a cross-shard migration. Keeping
        # this at the loop top (not only after a local trip) means migrated
        # vehicles recharge too, so the physics matches across both paths.
        if vehicle.soc < config.recharge_threshold:
            yield from _recharge(sim, shard, vehicle)

        request = shard.take_waiting_request()
        if request is None:
            vehicle.available = sim.event()
            yield shard.idle_store.put(vehicle)
            request = yield vehicle.available
        shard.record_served(sim.now - request.created)

        deadhead = graph.pickup_time(vehicle.zone, request.origin)
        if deadhead > 0:
            yield sim.delay(deadhead)
            vehicle.soc -= deadhead * config.consumption_per_time
            vehicle.zone = request.origin

        destination = request.destination
        trip = graph.trip_time(request.origin, destination, sim.rng)
        if shard.zone_to_shard[destination] == shard.index:
            yield sim.delay(trip)
            vehicle.soc -= trip * config.consumption_per_time
            vehicle.zone = destination
            shard.record_trip(migrated=False)
            continue

        # Cross-group trip: hand the vehicle off as plain data. The trip time is
        # the channel delay, and is >= the minimum inter-zone time (lookahead).
        target_shard = shard.zone_to_shard[destination]
        soc_after = vehicle.soc - trip * config.consumption_per_time
        shard.record_trip(migrated=True)
        shard.out_channels[target_shard].send(
            (vehicle.vehicle_id, soc_after, destination), delay=trip
        )
        return


def _request_process(
    sim: Sim, shard: _Shard, request: _Request
) -> Generator[Event[Any], Any, None]:
    """Assign a local request to a policy-chosen local vehicle, or abandon it."""
    idle = shard.idle_store.items
    if idle:
        chosen_id = shard.policy(idle, request.origin, shard.graph, sim.rng).vehicle_id
        vehicle: _Vehicle = yield shard.idle_store.get(
            lambda candidate: candidate.vehicle_id == chosen_id
        )
        request.settled = True
        assert vehicle.available is not None
        vehicle.available.succeed(request)
        return
    shard.pending.append(request)
    yield sim.delay(shard.config.patience)
    if not request.settled:
        request.settled = True
        shard.record_abandoned()


def _request_source(
    sim: Sim, shard: _Shard, local_zones: list[int], request_rate: float
) -> Generator[Event[Any], Any, None]:
    """Generate Poisson requests whose origin is owned by this shard.

    *request_rate* is this shard's *share* of the scenario's total demand
    (``config.request_rate / shards``), so the aggregate arrival rate is
    constant across shard counts -- the same workload, just partitioned.
    """
    config = shard.config
    rng = sim.rng
    while True:
        yield sim.delay(rng.expovariate(request_rate))
        if sim.now >= config.duration:
            return
        origin = local_zones[rng.randrange(len(local_zones))]
        destination = rng.randrange(config.num_zones)
        sim.spawn(_request_process, shard, _Request(origin, destination, sim.now))


def build_sharded_topology(
    config: RideHailingConfig, shards: int, seed: int, *, tracing: bool = False
) -> tuple[ShardedSim, dict[int, _ShardMetrics], dict[int, Tracer]]:
    """Build the zone-sharded topology, returning it with metrics and tracers.

    Args:
        config: The scenario (its ``num_zones`` must be divisible by ``shards``).
        shards: Number of zone-group shards.
        seed: Master seed for the sharded run.
        tracing: Attach a per-shard event tracer. Off by default so production
            runs pay no per-event tracing cost; the trace-equivalence test opts
            in. When off, the returned tracer dict is empty.

    Returns:
        ``(topology, per-shard metrics, per-shard tracers)``. The tracers back
        the bitwise trace-equivalence test; production runs ignore them.
    """
    zone_to_shard = _partition(config.num_zones, shards)
    topology = ShardedSim(shards, master_seed=seed)
    metrics: dict[int, _ShardMetrics] = {}
    tracers: dict[int, Tracer] = {}
    lookahead = ZoneGraph(config).min_lookahead()
    # Each shard is its zone-group's share of the scenario's total demand, so the
    # aggregate arrival rate is the same whatever the shard count.
    shard_request_rate = config.request_rate / shards

    def register(shard_index: int) -> None:
        local_zones = [
            zone for zone, owner in enumerate(zone_to_shard) if owner == shard_index
        ]
        others = [other for other in range(shards) if other != shard_index]
        per_shard_metrics = _ShardMetrics()
        metrics[shard_index] = per_shard_metrics

        def build(sim: Sim, ports: ShardPorts) -> None:
            if tracing:
                tracers[shard_index] = trace(sim)
            shard = _Shard(sim, shard_index, config, zone_to_shard, per_shard_metrics)
            for other in others:
                shard.out_channels[other] = ports.out(
                    f"migrate_{shard_index}_to_{other}", lookahead=lookahead
                )

            def make_receiver(source: int) -> None:
                inbox = ports.inbox(f"migrate_{source}_to_{shard_index}")

                def receiver(sim: Sim) -> Generator[Event[Any], Any, None]:
                    while True:
                        vehicle_id, soc, zone = yield inbox.get()
                        sim.spawn(_vehicle_loop, shard, _Vehicle(vehicle_id, zone, soc))

                sim.spawn(receiver)

            for other in others:
                make_receiver(other)

            # Home fleet: vehicles round-robin across this shard's zones.
            home_fleet = _home_fleet_size(config.fleet_size, shards, shard_index)
            for local_index in range(home_fleet):
                zone = local_zones[local_index % len(local_zones)]
                sim.spawn(
                    _vehicle_loop,
                    shard,
                    _Vehicle(
                        _global_vehicle_id(shards, shard_index, local_index),
                        zone,
                        config.battery_capacity,
                    ),
                )
            sim.spawn(_request_source, shard, local_zones, shard_request_rate)

        topology.shard(shard_index)(build)

    for shard_index in range(shards):
        register(shard_index)
    return topology, metrics, tracers


def _home_fleet_size(fleet_size: int, shards: int, shard_index: int) -> int:
    """Return how many vehicles start in *shard_index* (remainder spread low)."""
    return fleet_size // shards + (1 if shard_index < fleet_size % shards else 0)


def _global_vehicle_id(shards: int, shard_index: int, local_index: int) -> int:
    """Return a globally unique, stable vehicle id (shard-strided)."""
    return local_index * shards + shard_index


def _merge(metrics: dict[int, _ShardMetrics]) -> ShardedKPIs:
    """Sum per-shard metrics into merged :class:`ShardedKPIs`."""
    shards = metrics.values()
    served = sum(shard.served for shard in shards)
    wait_sum = sum(shard.wait_sum for shard in shards)
    mean_wait = wait_sum / served if served else 0.0
    return ShardedKPIs(
        served=served,
        abandoned=sum(shard.abandoned for shard in shards),
        mean_wait=round(mean_wait, 9),
        trips=sum(shard.trips for shard in shards),
        migrations=sum(shard.migrations for shard in shards),
    )


def run_sharded(
    config: RideHailingConfig,
    *,
    shards: int,
    seed: int = 20260712,
    mode: str = "threads",
) -> ShardedKPIs:
    """Run the zone-sharded ride-hailing model and return merged KPIs.

    Args:
        config: The scenario (its ``num_zones`` must be divisible by ``shards``).
        shards: Number of zone-group shards.
        seed: Master seed for the run.
        mode: ``"threads"`` (thread-per-shard) or ``"sequential"`` (the oracle).

    Returns:
        The merged headline KPIs across all shards.
    """
    topology, metrics, _ = build_sharded_topology(config, shards, seed)
    run_mode: Any = mode
    topology.run(until=config.duration, mode=run_mode)
    return _merge(metrics)
