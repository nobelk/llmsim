"""Timestamped inter-shard channels.

The only locked structures in the parallel layer: ordered, delayed message
queues carrying events between shards, with the link lookahead that bounds how
far apart shard clocks may drift.
"""
