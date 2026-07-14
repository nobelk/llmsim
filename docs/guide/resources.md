# Resources and stores

Resources model contention for shared, finite capacity. A process `yield`s a
request and suspends until the request is granted; releasing lets the next
waiter through. Every primitive here belongs to a single `Sim` on a single
thread.

## Resource

[`Resource`][llmsim.resources.resource.Resource] is a counting semaphore: up to
`capacity` processes hold it at once. Use `request()` as a context manager so
the slot is always released, even on an exception or interrupt:

```python
teller = llmsim.Resource(sim, capacity=2)

def customer(sim, teller):
    with teller.request() as slot:
        yield slot                 # granted when a slot frees
        yield sim.delay(5.0)       # hold it while served
    # slot released here
```

### Priority and preemption

- [`PriorityResource`][llmsim.resources.resource.PriorityResource] — waiters are
  granted in priority order (lower number = higher priority):
  `resource.request(priority=0)`.
- [`PreemptiveResource`][llmsim.resources.resource.PreemptiveResource] — a
  higher-priority request can **evict** a lower-priority holder, which sees an
  [`Interrupt`][llmsim.core.errors.Interrupt] at its current yield.

## Container

[`Container`][llmsim.resources.container.Container] models a continuous or
discrete bulk quantity — fuel, cash, inventory. Processes
[`put(amount)`][llmsim.resources.container.Container.put] and
[`get(amount)`][llmsim.resources.container.Container.get]; each blocks until the
level allows it:

```python
tank = llmsim.Container(sim, capacity=100.0, init=50.0)

def pump(sim, tank):
    yield tank.get(20.0)     # blocks until >= 20 available
```

## Stores

A store holds discrete **items** rather than a count:

- [`Store`][llmsim.resources.store.Store] — FIFO
  [`put(item)`][llmsim.resources.store.Store.put] /
  [`get()`][llmsim.resources.store.Store.get].
- [`PriorityStore`][llmsim.resources.store.PriorityStore] — items come out in
  priority order.
- [`FilterStore`][llmsim.resources.store.FilterStore] — `get(filter=...)`
  returns the first item matching a predicate; the natural fit for
  dispatch-by-attribute (e.g. an idle-vehicle pool).

```python
idle = llmsim.FilterStore(sim)

def dispatch(sim, idle, zone):
    vehicle = yield idle.get(lambda v: v.zone == zone)   # nearest-in-zone
    # ...use vehicle, then return it...
    yield idle.put(vehicle)
```

All of these are re-exported at the top level (`llmsim.Resource`,
`llmsim.Container`, `llmsim.Store`, …); see the
[Resources API reference](../reference/resources.md) for full signatures.
