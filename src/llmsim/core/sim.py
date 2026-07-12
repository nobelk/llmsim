"""The ``Sim`` event loop.

Owns the future-event set (a ``heapq`` ordered by ``(time, priority, eid)``),
advances simulation time, and dispatches due events to their callbacks. A
``Sim`` and everything attached to it belong to exactly one thread; there are
no locks on this hot path.
"""
