"""The seed tree and per-replication RNG streams.

Derives child seeds from the master seed via a hash-based tree (SHA-256 ->
128-bit child seeds) so each ``(config, replication)`` gets a statistically
independent ``random.Random`` stream that is stable across runs.
"""
