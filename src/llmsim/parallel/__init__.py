"""Share-nothing parallelism.

Parallel execution comes from independent work distributed across cores, never
from locks on the sequential engine: the replication runner, the PDES sharding
of a single model, the offload worker pool, and the backend abstraction that
unifies threads, subinterpreters, and processes behind one code path.
"""
