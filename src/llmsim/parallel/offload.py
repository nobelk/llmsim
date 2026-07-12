"""``sim.offload()`` worker-pool integration.

Lets a running process hand a pure, CPU-bound computation to a worker pool and
suspend until the result returns, without breaking determinism or the
single-thread ownership of the originating ``Sim``.
"""
