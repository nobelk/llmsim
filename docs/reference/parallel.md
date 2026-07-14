# Parallel

The share-nothing parallelism surface: parallel replications of a whole model,
the execution-backend abstraction, single-run PDES sharding, and the compute
offload pool. Every symbol here is re-exported from the top-level `llmsim`
package.

## Parallel replications

::: llmsim.parallel.replicate.Experiment

::: llmsim.parallel.replicate.ReplicationResult

::: llmsim.parallel.replicate.run_replications

::: llmsim.parallel.replicate.ReplicationError

## Execution backends

::: llmsim.parallel.backends.ExecutionBackend

::: llmsim.parallel.backends.CancelToken

::: llmsim.parallel.backends.FactoryValidationError

::: llmsim.parallel.backends.TransportError

## PDES sharding

::: llmsim.parallel.pdes.shard.ShardedSim

::: llmsim.parallel.pdes.shard.ShardPorts

::: llmsim.parallel.pdes.shard.ShardError

::: llmsim.parallel.pdes.shard.TopologyError

::: llmsim.parallel.pdes.channel.LookaheadError

### Channels and run modes

::: llmsim.parallel.pdes.shard.RunMode

::: llmsim.parallel.pdes.channel.Channel

::: llmsim.parallel.pdes.channel.Inbox

::: llmsim.parallel.pdes.channel.Message

### Window analysis

`analyze()` estimates a partition's parallel-window economics from a sequential
trace **before** you shard — see [PDES sharding](../guide/pdes.md#lookahead-economics).

::: llmsim.parallel.pdes.analyze.analyze

::: llmsim.parallel.pdes.analyze.PdesAnalysis

## Compute offload

::: llmsim.parallel.offload.OffloadPool

::: llmsim.parallel.offload.OffloadEvent

::: llmsim.parallel.offload.NonStrictOffloadWarning
