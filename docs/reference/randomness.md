# Randomness

Deterministic seed derivation. A `SeedTree` splits one master seed into
independent, reproducible `SeedStream`s so every process, replication, and
shard draws from a stream that depends only on its path in the tree — never on
scheduling or completion order. Both are re-exported from the top-level
`llmsim` package.

::: llmsim.rand.streams.SeedTree

::: llmsim.rand.streams.SeedStream
