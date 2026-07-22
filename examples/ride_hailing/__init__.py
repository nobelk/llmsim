"""Autonomous ride-hailing fleet example (roadmap 5.1--5.2).

A robotaxi fleet serving Poisson trip requests over a discrete zone graph,
exercising the sequential core plus every parallelism tier: fleet-sizing Monte
Carlo via ``Experiment`` (5.2a) and a zone-sharded ``ShardedSim`` variant
(5.2b). The public entry points are the importable factory
:func:`run_ride_hailing` and the config/KPI dataclasses.
"""

from examples.ride_hailing.kpis import RideHailingConfig, RideHailingKPIs
from examples.ride_hailing.model import run_ride_hailing, run_sequential
from examples.ride_hailing.policies import DispatchPolicy, get_policy

__all__ = [
    "DispatchPolicy",
    "RideHailingConfig",
    "RideHailingKPIs",
    "get_policy",
    "run_ride_hailing",
    "run_sequential",
]
