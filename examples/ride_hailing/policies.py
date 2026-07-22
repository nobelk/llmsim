"""Pluggable idle-vehicle dispatch policies for the ride-hailing example.

The whole point of the protocol seam is that ``closest_available`` and
``power_of_d`` (and the sharded variant's cross-zone handoff) share one code
path. Every policy is a *pure ranking* over the live idle set: it never depends
on ``FilterStore`` ordering or completion order, and it breaks ties by ascending
vehicle id, so the same seed selects the same vehicle on every backend and shard
count (``specs/tech-stack.md`` §7, determinism).
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Protocol


class TravelGraph(Protocol):
    """The slice of the zone graph a dispatch policy needs to rank candidates."""

    def pickup_time(self, from_zone: int, to_zone: int) -> float:
        """Return the deadhead travel time from *from_zone* to *to_zone*."""
        ...


class Candidate(Protocol):
    """The slice of an idle vehicle a dispatch policy reads to rank it."""

    #: Stable identity used as the deterministic tie-break key.
    vehicle_id: int
    #: The zone the vehicle currently sits in.
    zone: int


class DispatchPolicy(Protocol):
    """Select one idle vehicle to serve a request originating in *origin_zone*.

    The candidate set is drawn from idle vehicles across *all* zones, never
    restricted to the request's origin zone; the policy ranks them by inter-zone
    travel time to the origin.
    """

    def __call__(
        self,
        candidates: Sequence[Candidate],
        origin_zone: int,
        graph: TravelGraph,
        rng: random.Random,
    ) -> Candidate:
        """Return the chosen candidate (never mutates *candidates*)."""
        ...


def _rank_key(
    candidate: Candidate, origin_zone: int, graph: TravelGraph
) -> tuple[float, int]:
    """Return the (deadhead time, vehicle id) sort key -- id breaks every tie."""
    return (graph.pickup_time(candidate.zone, origin_zone), candidate.vehicle_id)


def closest_available(
    candidates: Sequence[Candidate],
    origin_zone: int,
    graph: TravelGraph,
    rng: random.Random,
) -> Candidate:
    """Return the idle vehicle nearest *origin_zone* by inter-zone travel time.

    Ties (equal deadhead time) are broken by ascending vehicle id, so the choice
    is independent of the order the store happens to hold the candidates in.
    """
    return min(candidates, key=lambda vehicle: _rank_key(vehicle, origin_zone, graph))


class PowerOfD:
    """``power_of_d``: sample *d* idle candidates, then pick the nearest.

    Sampling draws from ``sim.rng`` over a *canonical* (id-sorted) view of the
    candidates, so the sample -- and therefore the choice -- is a deterministic
    function of the seed and does not depend on ``FilterStore`` ordering.
    """

    __slots__ = ("d",)

    def __init__(self, d: int) -> None:
        """Store the fan-out *d* (number of candidates to sample)."""
        if d < 1:
            raise ValueError(f"power_of_d fan-out must be >= 1, got {d}")
        self.d = d

    def __call__(
        self,
        candidates: Sequence[Candidate],
        origin_zone: int,
        graph: TravelGraph,
        rng: random.Random,
    ) -> Candidate:
        """Return the nearest of *d* candidates sampled from *candidates*."""
        canonical = sorted(candidates, key=lambda vehicle: vehicle.vehicle_id)
        sample_size = min(self.d, len(canonical))
        sampled = rng.sample(canonical, sample_size)
        return min(sampled, key=lambda vehicle: _rank_key(vehicle, origin_zone, graph))


def get_policy(name: str, *, d: int = 2) -> DispatchPolicy:
    """Resolve a policy name to a :class:`DispatchPolicy` implementation.

    Args:
        name: ``"closest_available"`` or ``"power_of_d"``.
        d: Fan-out for ``power_of_d`` (ignored otherwise).

    Returns:
        The selected dispatch policy.

    Raises:
        ValueError: If *name* is not a known policy.
    """
    if name == "closest_available":
        return closest_available
    if name == "power_of_d":
        return PowerOfD(d)
    raise ValueError(f"unknown dispatch policy: {name!r}")
