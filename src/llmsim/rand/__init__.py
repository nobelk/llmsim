"""Deterministic randomness.

Turns a single master seed into a tree of independent, reproducible random
streams keyed by ``(config, replication)``, so that the same seed yields
identical results on any backend, worker count, or build.
"""
