"""Sequential simulation core.

Houses the ``Sim`` event loop (a ``heapq`` ordered by ``(time, priority,
eid)``), the generic ``Event`` type, the generator/``async def`` process
driver, and the engine's exception hierarchy. This is the single fully typed,
``__slots__``-based sequential engine that all parallelism builds on.
"""
