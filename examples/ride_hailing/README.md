# Ride-hailing fleet example

An autonomous robotaxi fleet serving Poisson trip requests over a discrete
**zone graph**, built entirely on the public llmsim API. It demonstrates the
sequential core (5.1) and both parallelism showcases (5.2).

## Model

- **Zones** are nodes on a ring with **fixed inter-zone travel times** and a
  strictly positive minimum (`min_interzone_time`). That minimum is the channel
  lookahead the sharded variant uses — the reason the geometry is discrete.
- **Vehicles** are generator processes running the full lifecycle: idle → drive
  to pickup → carry the trip → drop off → reposition → recharge. Each tracks a
  state-of-charge depleted by travel.
- **Charging stations** are finite-capacity `Resource`s; a recharge blocks when
  its station is full.
- **Idle vehicles** wait in a `FilterStore`. A request pulls out the vehicle its
  **dispatch policy** ranks best across *all* zones — never restricted to the
  origin zone — with ties broken by ascending vehicle id.
- **Dispatch policies** (`policies.py`) sit behind one protocol:
  `closest_available` (nearest idle vehicle) and `power_of_d` (sample `d`, pick
  the nearest). Selection is part of the config, so it flows through the seed
  tree deterministically.
- **Requests** abandon if unassigned within a `patience` window.

## Files

| File | Role |
| --- | --- |
| `model.py` | Zone graph, vehicle/request processes, the `run_ride_hailing` factory. |
| `policies.py` | `DispatchPolicy` protocol, `closest_available`, `power_of_d`. |
| `kpis.py` | `RideHailingConfig` and `RideHailingKPIs` (frozen, picklable). |
| `study_fleet_sizing.py` | Fleet-sizing Monte Carlo via `Experiment` (5.2a). |
| `sharded.py` | Zone-sharded `ShardedSim` variant (5.2b). |

## Run it

```python
from examples.ride_hailing import RideHailingConfig, run_sequential

kpis = run_sequential(seed=20260712, config=RideHailingConfig())
print(kpis)
```

The module-level factory `run_ride_hailing(seed_stream, config)` is importable
and closure-free, so `Experiment` can submit it to the thread, interpreter, or
process backend unchanged.

See the worked docs page: **Ride-hailing gallery** in the llmsim docs, which
links the [Which parallelism do I need?](../../docs/parallelism-decision-tree.md)
decision tree.
