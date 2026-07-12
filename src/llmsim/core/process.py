"""The process abstraction and its driver.

A process is a generator (SimPy-style ``yield`` of events) or an ``async def``
coroutine; a single driver advances both models by resuming the frame when the
event it is waiting on fires. Generators pin to their home thread.
"""
