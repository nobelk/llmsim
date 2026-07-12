"""The ``ExecutionBackend`` abstraction.

One code path over ``ThreadPoolExecutor`` (free-threaded 3.14t),
``InterpreterPoolExecutor`` (GIL builds), and ``ProcessPoolExecutor``. Work is
submitted as an importable callable plus a seed spec and config -- never live
objects -- so all three backends behave identically.
"""
