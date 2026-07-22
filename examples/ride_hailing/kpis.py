"""Configuration and KPI types for the ride-hailing example.

Both types are frozen, ``__slots__`` dataclasses so a config crosses a pickle
boundary to a process/interpreter worker unchanged and a KPI result comes back
the same way -- the executor-payloads-are-references rule
(``specs/tech-stack.md`` §5). Every KPI float is rounded so same-seed and
trace-equivalence assertions are bit-stable across platforms.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Decimal places every KPI float is rounded to for cross-platform bit-stability.
KPI_PRECISION = 9


@dataclass(frozen=True, slots=True)
class RideHailingConfig:
    """A single, fully-specified ride-hailing scenario.

    The zone graph is derived deterministically from :attr:`num_zones` and the
    travel-time parameters (see :class:`~examples.ride_hailing.model.ZoneGraph`),
    so the whole scenario is captured by these plain, picklable fields.
    """

    #: Number of zones (graph nodes) arranged on a ring.
    num_zones: int = 6
    #: Number of robotaxis in the fleet.
    fleet_size: int = 8
    #: Poisson trip-request arrival rate (requests per unit time).
    request_rate: float = 1.2
    #: How long a request waits for assignment before abandoning.
    patience: float = 8.0
    #: Strictly positive minimum inter-zone travel time -- the PDES lookahead.
    min_interzone_time: float = 3.0
    #: Extra travel time per unit of ring distance between zones.
    interzone_step: float = 1.5
    #: Mean of the intra-zone (same-origin-and-destination) trip-time draw.
    intra_zone_mean: float = 2.0
    #: Full battery state-of-charge.
    battery_capacity: float = 100.0
    #: State-of-charge consumed per unit of travel time.
    consumption_per_time: float = 2.0
    #: Recharge when state-of-charge drops below this level.
    recharge_threshold: float = 25.0
    #: State-of-charge restored per unit of charging time.
    charge_rate: float = 20.0
    #: Zones that host a charging station.
    charging_zones: tuple[int, ...] = (0, 3)
    #: Number of vehicles a charging station serves at once.
    charging_capacity: int = 2
    #: Probability a vehicle repositions to a random zone after a drop-off.
    reposition_prob: float = 0.3
    #: Dispatch policy name (see :mod:`examples.ride_hailing.policies`).
    policy: str = "closest_available"
    #: Fan-out for the ``power_of_d`` policy (ignored otherwise).
    policy_d: int = 2
    #: Simulated time horizon.
    duration: float = 200.0


@dataclass(frozen=True, slots=True)
class RideHailingKPIs:
    """Headline outcomes of one ride-hailing run.

    A deterministic function of ``(seed, config)``: identical on any backend,
    worker count, or build.
    """

    #: Mean rider wait time from request to assignment (served requests only).
    mean_wait: float
    #: Number of requests served.
    served: int
    #: Number of requests that abandoned before assignment.
    abandoned: int
    #: Fraction of requests that abandoned.
    abandonment_rate: float
    #: Mean per-vehicle utilization (busy time / horizon).
    mean_utilization: float
    #: Simulated time of the last event.
    makespan: float


class KpiAccumulator:
    """Mutable per-run tally that :meth:`finalize` folds into a result."""

    __slots__ = ("waits", "abandoned", "busy_time")

    def __init__(self) -> None:
        """Start an empty tally."""
        #: Wait time of every served request.
        self.waits: list[float] = []
        #: Count of abandoned requests.
        self.abandoned = 0
        #: Total busy (non-idle) time summed across all vehicles.
        self.busy_time = 0.0

    def record_served(self, wait: float) -> None:
        """Record a served request that waited *wait* time for assignment."""
        self.waits.append(wait)

    def record_abandoned(self) -> None:
        """Record a request that abandoned before assignment."""
        self.abandoned += 1

    def record_busy(self, duration: float) -> None:
        """Add *duration* of vehicle busy time to the utilization tally."""
        self.busy_time += duration

    def finalize(
        self, *, fleet_size: int, horizon: float, makespan: float
    ) -> RideHailingKPIs:
        """Fold the tally into a rounded, immutable :class:`RideHailingKPIs`."""
        served = len(self.waits)
        total = served + self.abandoned
        mean_wait = sum(self.waits) / served if served else 0.0
        abandonment_rate = self.abandoned / total if total else 0.0
        utilization = self.busy_time / (fleet_size * horizon) if horizon else 0.0
        return RideHailingKPIs(
            mean_wait=round(mean_wait, KPI_PRECISION),
            served=served,
            abandoned=self.abandoned,
            abandonment_rate=round(abandonment_rate, KPI_PRECISION),
            mean_utilization=round(utilization, KPI_PRECISION),
            makespan=round(makespan, KPI_PRECISION),
        )
