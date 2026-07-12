"""The generic ``Event[T]`` type and event scheduling primitives.

An event carries a value of type ``T`` on success, tracks its scheduled
``(time, priority, eid)`` sort key, and fans out to registered callbacks when
it is processed.
"""
