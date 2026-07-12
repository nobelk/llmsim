"""Limited-capacity ``Resource``.

Models a pool of interchangeable servers: processes request a slot, hold it for
some service time, and release it, with waiters queued until capacity frees.
"""
