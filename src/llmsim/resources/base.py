"""Common base for resource types.

Factors out the shared request/release queue mechanics (put/get event
bookkeeping, FIFO/priority ordering) reused by ``Resource``, ``Container``,
and ``Store``.
"""
