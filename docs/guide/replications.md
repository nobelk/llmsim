# Parallel replications

The first parallelism tier, and the one to reach for first: run **many
independent runs** of the same model — different seeds, different configs — in
parallel across cores. Each replication is its own `Sim` with nothing shared,
so this is the share-nothing architecture at its purest.

Reach for this when your question is statistical ("what's the 95% CI on mean
wait time?", "how does throughput vary across fleet sizes?"). See
[Which parallelism do I need?](../parallelism-decision-tree.md) for the full
decision.

## Experiment

[`Experiment`][llmsim.parallel.replicate.Experiment] runs a **factory** across a
list of configs and a replication count. The factory is a *module-level
importable callable* — never a live object — called as `factory(stream, config)`,
where `stream` is a [`SeedStream`][llmsim.rand.streams.SeedStream] derived
deterministically from the master seed:

```python
# models.py  --  must be importable, not a local closure
def mm1_mean_wait(stream, config):
    sim = llmsim.Sim(rng=stream.rng())      # stream.rng() builds a fresh Random
    server = llmsim.Resource(sim, capacity=config["servers"])
    # ...build the model, run it...
    sim.run(until=1000.0)
    return mean_wait      # return KPIs, not raw traces
```

```python
from models import mm1_mean_wait

configs = [{"servers": 1}, {"servers": 2}, {"servers": 3}]
exp = llmsim.Experiment(mm1_mean_wait, configs, master_seed=42)
results = exp.run(replications=100)      # dict keyed by (config_index, rep_index)

for (cfg, rep), result in results.items():
    print(cfg, rep, result.value)
```

The result set is a `dict[(config_index, replication_index), ReplicationResult]`
— keyed by identity, **never by completion order**, so the same master seed
reproduces the same study byte-for-byte regardless of backend or worker count.

## Choosing a backend

`Experiment.run(backend=...)` accepts `"auto"` (the default), `"threads"`,
`"interpreters"`, or `"processes"`:

- **`"processes"`** is the workhorse — it scales regardless of payload shape and
  is unaffected by the free-threaded build's shared-object refcount contention.
  Prefer it for replication studies even on `3.14t`.
- **`"threads"`** *anti-scales* for DES event loops on `3.14t` today: the
  engine's and `random.py`'s hot paths hammer shared objects, and refcount
  cache-line contention outweighs the parallelism. `"auto"` picks threads on
  free-threaded builds — override to processes for real studies.
- **`"interpreters"`** (subinterpreters) sits between the two.

The measured curves and their slowdown regimes are on the
[Replication scaling](../perf/replication-scaling.md) page — every number there
is measured, with the regimes where the backend does *not* win stated
alongside.

## Bounding memory

Large per-replication outputs cross a pickle boundary on the process and
interpreter backends. Return KPIs rather than multi-MB traces, and pass
`spool=True` to hold results as zstd-compressed bytes decompressed lazily on
access:

```python
exp = llmsim.Experiment(model, configs, master_seed=42, spool=True)
```
