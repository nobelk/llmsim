# PDES sharding

Parallel discrete-event simulation (PDES) splits **one** model across cores.
Where [replications](replications.md) parallelize *many runs*, sharding
parallelizes a *single large run* by partitioning it into logical processes
(shards) that advance concurrently and exchange timestamped messages.

llmsim uses **conservative** synchronization only: a shard advances just within
a provably safe time window derived from channel **lookahead**. Optimistic
(Time Warp) rollback is permanently rejected — generator frames cannot be
snapshotted.

Reach for sharding only when a single run is your bottleneck and the model has
natural boundaries with real transit delay across them (a conveyor between
stations, travel time between city zones). See
[Which parallelism do I need?](../parallelism-decision-tree.md).

## ShardedSim

[`ShardedSim`][llmsim.parallel.pdes.shard.ShardedSim] declares a fixed number of
shards; each is built by a function decorated with `@topo.shard(i)` that
receives its own `Sim` and a
[`ShardPorts`][llmsim.parallel.pdes.shard.ShardPorts] handle for wiring channels:

```python
topo = llmsim.ShardedSim(shards=2, master_seed=42)

@topo.shard(0)
def station_a(sim, ports):
    out = ports.out("a_to_b", lookahead=4.0)     # transit delay = lookahead
    def producer(sim):
        while True:
            yield sim.delay(1.0)
            out.send("part", delay=4.0)
    sim.spawn(producer)

@topo.shard(1)
def station_b(sim, ports):
    inbox = ports.inbox("a_to_b")
    def consumer(sim):
        while True:
            part = yield inbox.get()
    sim.spawn(consumer)

topo.run(until=100.0)                       # thread-per-shard
topo.run(until=100.0, mode="sequential")    # the reference oracle
```

Two rules make this deterministic:

- **Lookahead is transit delay.** A channel's `lookahead` is the minimum
  simulated time a message takes to cross it; it bounds how far ahead the
  receiving shard may safely run. Send delays must be `>= lookahead`.
- **`mode="sequential"` is the oracle.** The same topology run sequentially
  produces the reference trace; the threaded run is asserted **bitwise-equal**
  to it at every shard count.

## Lookahead economics

Sharding only pays when lookahead is a **large multiple** of the mean event
spacing — the safe window then carries real work per synchronization barrier.
When lookahead approaches the event spacing, the run is dominated by barriers
and is *slower* than sequential.

Use `llmsim.parallel.pdes.analyze()` on a sequential trace to estimate the
window economics **before** partitioning. The measured
shard-scaling and lookahead-degradation curves — including the regimes where
sharding loses — are on the [PDES scaling](../perf/pdes-scaling.md) page.

## Errors

Topology mistakes surface at construction / `run()`, never mid-run:
[`ShardError`][llmsim.parallel.pdes.shard.ShardError],
[`TopologyError`][llmsim.parallel.pdes.shard.TopologyError] (mis-wired channels), and
[`LookaheadError`][llmsim.parallel.pdes.channel.LookaheadError] (a send that violates a
channel's lookahead).
