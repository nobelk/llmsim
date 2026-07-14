# Core concepts

Everything in a sequential llmsim model is built from four ideas: the **Sim**
that owns the clock and the event queue, the **events** processes wait on, the
**processes** themselves, and the **conditions** that compose events.

## The Sim

[`Sim`][llmsim.core.sim.Sim] is the simulation: a clock (`sim.now`), a
priority queue of scheduled events, and a random number generator. A `Sim` and
everything attached to it belong to **exactly one thread** — the sequential
hot path takes no locks.

```python
sim = llmsim.Sim(seed=0)     # seeded RNG for reproducibility
sim = llmsim.Sim(rng=my_random.Random())   # or bring your own Random
```

`sim.run(until=...)` drives the loop; `until` may be `None` (run until the
schedule empties), a time, or an [`Event`][llmsim.core.events.Event] (run until
it fires and return its value).

## Events

An event is a value that becomes available at some simulated time. A process
`yield`s an event to suspend until the event fires; the yield expression then
evaluates to the event's value.

- [`sim.delay(t, value=None)`][llmsim.core.sim.Sim.delay] returns a
  [`Timeout`][llmsim.core.events.Timeout] that fires `t` units from now.
- [`sim.event()`][llmsim.core.sim.Sim.event] returns a fresh
  [`Event`][llmsim.core.events.Event] you trigger yourself — the building block
  for custom synchronization.

Events are generic in their result type: `Event[T]` fires with a value of type
`T`, so `value = yield some_event` is fully typed.

## Processes

A [`Process`][llmsim.core.process.Process] is a running generator (or
coroutine). Start one with
[`sim.spawn(fn, *args, **kwargs)`][llmsim.core.sim.Sim.spawn]; the `Sim` is
injected as `fn`'s first argument. A process is itself an event — you can
`yield` another process to wait for it to finish:

```python
def wash(sim):
    yield sim.delay(3.0)
    return "clean"


def owner(sim):
    result = yield sim.spawn(wash)   # wait for wash to complete
    assert result == "clean"


sim.spawn(owner)
```

### Interrupts

One process can interrupt another. The interrupted process sees an
[`Interrupt`][llmsim.core.errors.Interrupt] raised at its current `yield`:

```python
def driver(sim, worker):
    yield sim.delay(2.0)
    worker.interrupt("stop")


def worker(sim):
    try:
        yield sim.delay(100.0)     # a long wait...
    except llmsim.Interrupt as interrupt:
        print("interrupted:", interrupt.cause)   # ...cut short at t=2
```

## Conditions

Conditions wait on *sets* of events:

- [`sim.all_of(events)`][llmsim.core.sim.Sim.all_of] — an
  [`AllOf`][llmsim.core.conditions.AllOf] that fires when **every** event has
  fired (a barrier / join).
- [`sim.any_of(events)`][llmsim.core.sim.Sim.any_of] — an
  [`AnyOf`][llmsim.core.conditions.AnyOf] that fires when the **first** event
  fires (a race / timeout guard).

```python
def fetch_with_timeout(sim, work):
    done = sim.any_of([work, sim.delay(10.0)])
    result = yield done
    if work in result:
        return result[work]
    raise TimeoutError("work did not finish in 10 units")
```

Both are [`Condition`][llmsim.core.conditions.Condition]s and compose, so a
condition can itself be an operand of another.

## Errors

The engine's exceptions all derive from
[`SimulationError`][llmsim.core.errors.SimulationError].
[`EmptySchedule`][llmsim.core.errors.EmptySchedule] signals that a `run(until=event)`
can never complete because the queue drained first.
[`Interrupt`][llmsim.core.errors.Interrupt] is the process-interruption signal
above.
