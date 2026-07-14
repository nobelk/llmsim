# Migrating from SimPy 3

This guide is for SimPy 3 users porting an existing model to llmsim. llmsim
keeps SimPy's generator-as-process model — processes are generators, they
`yield` events, resources are context managers — so a port is mostly a
mechanical rename plus a handful of deliberate semantic changes. What llmsim
does **not** keep is API compatibility: per the project mission, there is no
compatibility shim or adapter layer, and none is planned. The clean break is
what buys the fully typed, `__slots__`-based core and the share-nothing
parallelism on top of it; [Why llmsim will outperform
SimPy](simpy-comparison.md) argues the *why* — this page covers the *how*.

Every code excerpt below is lifted verbatim from the benchmark model pairs in
`benchmarks/models/` (SimPy 3) and `benchmarks/llmsim_models/` (llmsim), which
run in CI with exact-KPI-equality checks between the two. A snippet-sync test
keeps this page byte-identical to those files, so the code you read here is
code that runs.

## Concept mapping

### Environment and event loop

| SimPy 3 | llmsim | Notes |
| --- | --- | --- |
| `simpy.Environment()` | `llmsim.Sim(seed=...)` | A `Sim` owns a seeded RNG (`sim.rng`) and belongs to exactly one thread. |
| `env.now` | `sim.now` | The float simulation clock, unchanged. |
| `env.run(until=...)` | `sim.run(until=...)` | `until` accepts a time or an event in both; omit it to run the schedule dry. |
| `env.step()` / `env.peek()` | `sim.step()` / `sim.peek()` | Manual stepping, unchanged. |
| `simpy.core.EmptySchedule` | `llmsim.EmptySchedule` | Raised by `step()` on an empty queue; importable from the top level. |

### Processes

| SimPy 3 | llmsim | Notes |
| --- | --- | --- |
| `env.process(fn(env, arg))` | `sim.spawn(fn, arg)` | You pass the *callable*, not a started generator; `spawn` injects the `Sim` as the first argument. |
| `simpy.Process` | `llmsim.Process` | Returned by `sim.spawn()`; still an event you can `yield` to join. |
| `env.timeout(delay, value)` | `sim.delay(delay, value)` | Renamed; same semantics, including the optional value. |
| `simpy.Timeout` | `llmsim.Timeout` | The event type `sim.delay()` returns. |
| `proc.interrupt(cause)` | `proc.interrupt(cause)` | Unchanged, including `proc.is_alive`. |
| `env.active_process` | `sim.active_process` | Unchanged. |

### Events and conditions

| SimPy 3 | llmsim | Notes |
| --- | --- | --- |
| `env.event()` | `sim.event()` | llmsim's `Event[T]` is generic in its success value. |
| `simpy.Event` | `llmsim.Event` | `succeed(value)`, `fail(exception)`, and `trigger(other)` keep their names; `event.callbacks` is still the public callback list. |
| `ev1 & ev2` / `ev1 \| ev2` | `ev1 & ev2` / `ev1 \| ev2` | Operator composition, unchanged. |
| `env.all_of()` / `env.any_of()` | `sim.all_of()` / `sim.any_of()` | Also available as `llmsim.AllOf` / `llmsim.AnyOf`. |
| `simpy.AllOf` / `simpy.AnyOf` | `llmsim.AllOf` / `llmsim.AnyOf` | Both yield a dict-like `ConditionValue`. |
| `simpy.Condition` | `llmsim.Condition` | **Semantic delta:** when several grouped events fail, llmsim aggregates all failures into one `ExceptionGroup` instead of surfacing only the first. |

### Interrupts and errors

| SimPy 3 | llmsim | Notes |
| --- | --- | --- |
| `simpy.Interrupt` | `llmsim.Interrupt` | Caught the same way; the interrupt's `.cause` carries whatever was passed to `interrupt()`. |
| `event.defused` | `event.defused` | **Semantic delta:** an explicit, always-present boolean attribute rather than SimPy 3's dynamically added one — see [What has no equivalent](#what-has-no-equivalent). |

### Resources

| SimPy 3 | llmsim | Notes |
| --- | --- | --- |
| `simpy.Resource(env, capacity)` | `llmsim.Resource(sim, capacity)` | `with resource.request() as req: yield req` works unchanged. |
| `simpy.PriorityResource` | `llmsim.PriorityResource` | `.request(priority=...)` unchanged. |
| `simpy.PreemptiveResource` | `llmsim.PreemptiveResource` | Preemption interrupts the victim with a `Preempted` cause, as in SimPy. |
| `simpy.Container` | `llmsim.Container` | `put(amount)` / `get(amount)` / `.level` unchanged. |
| `simpy.Store` | `llmsim.Store` | Generic `Store[T]`; `put(item)` / `get()` unchanged. |
| `simpy.PriorityStore` | `llmsim.PriorityStore` | Unchanged. |
| `simpy.FilterStore` | `llmsim.FilterStore` | `get(filter)` unchanged. |

### RNG and determinism

| SimPy 3 | llmsim | Notes |
| --- | --- | --- |
| module-level `random`, or a hand-seeded `random.Random(seed)` | `sim.rng` | Every `Sim` owns its own seeded `random.Random` stream; nothing in llmsim ever touches the global `random` state. |
| ad-hoc reproducibility | `(time, priority, eid)` event ordering | Both engines break ties deterministically; llmsim additionally guarantees the same `(seed, config)` gives identical results on every backend and build. |

### Real-time mode

| SimPy 3 | llmsim | Notes |
| --- | --- | --- |
| `simpy.rt.RealtimeEnvironment(factor=..., strict=...)` | `llmsim.rt.run(sim, factor=..., strict=...)` | Real time is a *run driver* applied to an ordinary `Sim`, not an environment subclass; falling behind in strict mode raises `llmsim.RealtimeDriftError` instead of `RuntimeError`. |

## What has no equivalent

These SimPy 3 names intentionally do not map to anything — dropping them is
part of the clean-break decision recorded in the project mission:

- **`BoundClass`** — SimPy's descriptor trick for constructing events through
  the environment. llmsim uses plain methods and plain constructors; there is
  nothing to port.
- **`StopProcess` / `env.exit(value)`** — long deprecated in SimPy itself.
  Use a plain `return value` inside the process generator.
- **`simpy.rt.RealtimeEnvironment`** (the class) — you never rebuild a model
  around a different environment type. Build the same `Sim` you would run
  normally and hand it to `llmsim.rt.run()` (see the table above).
- **SimPy 3's dynamic `defused` attribute** — SimPy 3 tracks defusal by
  attribute *presence* (`hasattr`). llmsim's `Event.defused` is an ordinary
  boolean that always exists; read and set it directly. Code that probed for
  the attribute has no equivalent and should test the flag instead.

## Worked port: M/M/1 queue

The smallest of the three canonical models: one server, Poisson arrivals,
exponential service. Full sources: `benchmarks/models/mm1.py` (SimPy 3) and
`benchmarks/llmsim_models/mm1.py` (llmsim).

Setup replaces the `Environment` plus a hand-seeded `random.Random` with a
single seeded `Sim`:

**SimPy 3**

<!-- snippet: benchmarks/models/mm1.py#setup -->
```python
rng = random.Random(seed)
env = simpy.Environment()
server = simpy.Resource(env, capacity=1)
total_wait = 0.0
total_service = 0.0
num_served = 0
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/mm1.py#setup -->
```python
sim = Sim(seed=seed)
rng = sim.rng
server = Resource(sim, capacity=1)
total_wait = 0.0
total_service = 0.0
num_served = 0
```

Two deltas: `Sim(seed=seed)` seeds the simulation's own RNG stream, so
`rng = sim.rng` replaces constructing a `random.Random` by hand, and llmsim
classes are imported directly (`from llmsim import Resource, Sim`) rather than
referenced through a `simpy.` module prefix.

The customer process shows the two renames every port hits — `env.now` →
`sim.now` and `env.timeout()` → `sim.delay()` — while the resource
request/release protocol is untouched:

**SimPy 3**

<!-- snippet: benchmarks/models/mm1.py#customer -->
```python
def customer() -> object:
    nonlocal total_wait, total_service, num_served
    arrived_at = env.now
    with server.request() as slot:
        yield slot
        total_wait += env.now - arrived_at
        service_time = rng.expovariate(service_rate)
        total_service += service_time
        num_served += 1
        yield env.timeout(service_time)
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/mm1.py#customer -->
```python
def customer(sim: Sim) -> Generator[Event[Any], Any, None]:
    nonlocal total_wait, total_service, num_served
    arrived_at = sim.now
    with server.request() as slot:
        yield slot
        total_wait += sim.now - arrived_at
        service_time = rng.expovariate(service_rate)
        total_service += service_time
        num_served += 1
        yield sim.delay(service_time)
```

The signature changes for two reasons. First, `sim.spawn()` always injects the
`Sim` as the process's first argument, so every llmsim process takes a `sim`
parameter instead of closing over a global `env`. Second, the benchmark port
is fully typed — `Generator[Event[Any], Any, None]` where the SimPy original
says `object` — because llmsim's public API is fully annotated and the
project's strict type gates cover its models. The annotations are optional in
your own code; `def customer(sim):` works the same.

Spawning shows the other structural change — you hand `spawn` the *function*,
and llmsim starts it, rather than calling the generator function yourself:

**SimPy 3**

<!-- snippet: benchmarks/models/mm1.py#arrivals -->
```python
def arrivals() -> object:
    for _ in range(num_customers):
        yield env.timeout(rng.expovariate(arrival_rate))
        env.process(customer())
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/mm1.py#arrivals -->
```python
def arrivals(sim: Sim) -> Generator[Event[Any], Any, None]:
    for _ in range(num_customers):
        yield sim.delay(rng.expovariate(arrival_rate))
        sim.spawn(customer)
```

And the entry point is a one-line-each swap:

**SimPy 3**

<!-- snippet: benchmarks/models/mm1.py#run -->
```python
env.process(arrivals())
env.run()
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/mm1.py#run -->
```python
sim.spawn(arrivals)
sim.run()
```

## Worked port: machine shop

The classic SimPy machine-shop example: machines make parts, break down at
random, and queue for shared repairers under a preemptive priority discipline.
It exercises interrupts, `PreemptiveResource`, and process-to-process
interaction. Full sources: `benchmarks/models/machine_shop.py` and
`benchmarks/llmsim_models/machine_shop.py`.

Class-based models port the same way as free functions. Note how the two
background processes are started:

**SimPy 3**

<!-- snippet: benchmarks/models/machine_shop.py#init -->
```python
def __init__(
    self,
    env: simpy.Environment,
    repairers: simpy.PreemptiveResource,
    rng: random.Random,
) -> None:
    self.env = env
    self.repairers = repairers
    self.rng = rng
    self.parts_made = 0
    self.broken = False
    self.process = env.process(self._work())
    env.process(self._break())
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/machine_shop.py#init -->
```python
def __init__(
    self, sim: Sim, repairers: PreemptiveResource, rng: random.Random
) -> None:
    self.sim = sim
    self.repairers = repairers
    self.rng = rng
    self.parts_made = 0
    self.broken = False
    self.process = sim.spawn(self._work)
    sim.spawn(self._break)
```

`env.process(self._work())` calls the generator method itself; `sim.spawn`
takes the bound method uncalled — `sim.spawn(self._work)` — and starts it.
(The constructor parameter list is also formatted more compactly in the port;
that is style, not semantics.)

The work loop is where interrupt handling migrates. `except simpy.Interrupt`
becomes `except Interrupt` with `llmsim.Interrupt`, and the preemptive
request with a priority is unchanged:

**SimPy 3**

<!-- snippet: benchmarks/models/machine_shop.py#work -->
```python
def _work(self) -> object:
    while True:
        remaining = _time_per_part(self.rng)
        while remaining > 0:
            started = self.env.now
            try:
                yield self.env.timeout(remaining)
                remaining = 0.0
                self.parts_made += 1
            except simpy.Interrupt:
                self.broken = True
                remaining -= self.env.now - started
                with self.repairers.request(priority=1) as repair:
                    yield repair
                    yield self.env.timeout(REPAIR_TIME)
                self.broken = False
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/machine_shop.py#work -->
```python
def _work(self, sim: Sim) -> Generator[Event[Any], Any, None]:
    while True:
        remaining = _time_per_part(self.rng)
        while remaining > 0:
            started = self.sim.now
            try:
                yield self.sim.delay(remaining)
                remaining = 0.0
                self.parts_made += 1
            except Interrupt:
                self.broken = True
                remaining -= self.sim.now - started
                with self.repairers.request(priority=1) as repair:
                    yield repair
                    yield self.sim.delay(REPAIR_TIME)
                self.broken = False
```

Because `spawn` injects the `Sim` even into bound methods, `_work` gains a
`sim` parameter; this model keeps using `self.sim` in the body (the two are
the same object), so the parameter simply absorbs the injection.

Process-to-process interaction — one process interrupting another through the
`Process` handle returned at spawn time — is unchanged:

**SimPy 3**

<!-- snippet: benchmarks/models/machine_shop.py#break -->
```python
def _break(self) -> object:
    while True:
        yield self.env.timeout(self.rng.expovariate(1.0 / MEAN_TIME_TO_FAILURE))
        if not self.broken:
            self.process.interrupt()
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/machine_shop.py#break -->
```python
def _break(self, sim: Sim) -> Generator[Event[Any], Any, None]:
    while True:
        yield self.sim.delay(self.rng.expovariate(1.0 / MEAN_TIME_TO_FAILURE))
        if not self.broken:
            self.process.interrupt()
```

The entry point repeats the M/M/1 setup pattern, this time with a
`PreemptiveResource` and a bounded run:

**SimPy 3**

<!-- snippet: benchmarks/models/machine_shop.py#run -->
```python
rng = random.Random(seed)
env = simpy.Environment()
repairers = simpy.PreemptiveResource(env, capacity=num_repairers)
machines = [_Machine(env, repairers, rng) for _ in range(num_machines)]
env.run(until=SHOP_DURATION)
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/machine_shop.py#run -->
```python
sim = Sim(seed=seed)
rng = sim.rng
repairers = PreemptiveResource(sim, capacity=num_repairers)
machines = [_Machine(sim, repairers, rng) for _ in range(num_machines)]
sim.run(until=SHOP_DURATION)
```

## Worked port: grid conveyor

A 100×100 grid of single-capacity conveyor segments; items enter at the
top-left and contend for shared cells along an L-shaped route. This is the
resource-contention-at-scale model: ten thousand `Resource` objects in one
simulation. Full sources: `benchmarks/models/grid_conveyor.py` and
`benchmarks/llmsim_models/grid_conveyor.py`. (The `Store` family does not
appear in any of the three canonical models; its mapping lives in the
[concept table](#resources).)

Building ten thousand resources is the same dict comprehension in both:

**SimPy 3**

<!-- snippet: benchmarks/models/grid_conveyor.py#setup -->
```python
rng = random.Random(seed)
env = simpy.Environment()
segments = {
    (row, col): simpy.Resource(env, capacity=1)
    for row in range(rows)
    for col in range(cols)
}
route = _route(rows, cols)
total_transit = 0.0
delivered = 0
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/grid_conveyor.py#setup -->
```python
sim = Sim(seed=seed)
rng = sim.rng
segments = {
    (row, col): Resource(sim, capacity=1)
    for row in range(rows)
    for col in range(cols)
}
route = _route(rows, cols)
total_transit = 0.0
delivered = 0
```

The item process — request a segment, transit, release, repeat down the
route — carries over with only the by-now-familiar renames (`sim` parameter,
`sim.now`, `sim.delay`):

**SimPy 3**

<!-- snippet: benchmarks/models/grid_conveyor.py#item -->
```python
def item() -> object:
    nonlocal total_transit, delivered
    entered_at = env.now
    for cell in route:
        with segments[cell].request() as slot:
            yield slot
            yield env.timeout(SEGMENT_TRANSIT)
    total_transit += env.now - entered_at
    delivered += 1
```

**llmsim**

<!-- snippet: benchmarks/llmsim_models/grid_conveyor.py#item -->
```python
def item(sim: Sim) -> Generator[Event[Any], Any, None]:
    nonlocal total_transit, delivered
    entered_at = sim.now
    for cell in route:
        with segments[cell].request() as slot:
            yield slot
            yield sim.delay(SEGMENT_TRANSIT)
    total_transit += sim.now - entered_at
    delivered += 1
```

The payoff at this scale is determinism you can lean on. Like SimPy, llmsim
processes events in `(time, priority, eid)` order, so ties never depend on
hash order or wall clock; beyond SimPy, the seeded `sim.rng` makes the whole
run a pure function of the seed — the same seed produces the same event trace
on every backend, worker count, and build, and CI enforces exact KPI equality
between this port and its SimPy reference. That guarantee is what the
parallel layers build on when you later scale a migrated model out; see
[Which parallelism do I need?](parallelism-decision-tree.md) when you are
ready for that step.
