"""Model partitioning into shards.

Splits one model into logical processes, each an independent ``Sim`` owned by a
single worker, and defines how a shard advances its local clock within the
current safe window.
"""
