"""The replication runner -- the flagship parallel capability.

Runs N independent replications of a model across cores and collects their
results keyed by ``(config index, replication index)``, never by completion
order, so the outcome is identical regardless of how the work is scheduled.
Home to ``Experiment``, ``run_replications()``, and ``ReplicationResult``.
"""
